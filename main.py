from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import pymysql
from dotenv import load_dotenv
from PIL import Image

from codex_exec import (
    build_image_prompt,
    build_script_prompt,
    load_prompt,
    resolve_template,
    run_codex_exec,
    template_keys,
)
from db_access import fetch_latest_keyword


REQUIRED_MYSQL_ENV = (
    "MYSQL_HOST",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DATABASE",
)

TARGET_IMAGE_MAX_SIDE = 1024
MAX_IMAGE_BYTES = 1_000_000

HANGUL_INITIALS = (
    "g",
    "kk",
    "n",
    "d",
    "tt",
    "r",
    "m",
    "b",
    "pp",
    "s",
    "ss",
    "",
    "j",
    "jj",
    "ch",
    "k",
    "t",
    "p",
    "h",
)
HANGUL_VOWELS = (
    "a",
    "ae",
    "ya",
    "yae",
    "eo",
    "e",
    "yeo",
    "ye",
    "o",
    "wa",
    "wae",
    "oe",
    "yo",
    "u",
    "wo",
    "we",
    "wi",
    "yu",
    "eu",
    "ui",
    "i",
)
HANGUL_FINALS = (
    "",
    "k",
    "k",
    "k",
    "n",
    "n",
    "n",
    "t",
    "l",
    "k",
    "m",
    "l",
    "l",
    "l",
    "p",
    "l",
    "m",
    "p",
    "p",
    "t",
    "t",
    "ng",
    "t",
    "t",
    "k",
    "t",
    "p",
    "t",
)


def mysql_connect_kwargs() -> dict[str, object]:
    """입력: 환경변수. 출력: pymysql.connect에 전달할 MySQL 접속 설정."""
    missing = [name for name in REQUIRED_MYSQL_ENV if not os.environ.get(name, "").strip()]
    if missing:
        raise ValueError("Missing required environment variable(s): " + ", ".join(missing))

    return {
        "host": os.environ["MYSQL_HOST"].strip(),
        "port": int(os.environ.get("MYSQL_PORT", "3306")),
        "user": os.environ["MYSQL_USER"].strip(),
        "password": os.environ["MYSQL_PASSWORD"].strip(),
        "database": os.environ["MYSQL_DATABASE"].strip(),
        "charset": (os.environ.get("MYSQL_CHARSET") or "utf8mb4").strip(),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    """입력: 명령줄 인자 리스트. 출력: 실행 옵션 Namespace."""
    parser = argparse.ArgumentParser(
        description="Generate script text and/or an image from a DB keyword using a selected prompt template."
    )
    parser.add_argument(
        "--template",
        default="explain_child",
        choices=template_keys(),
        help="Template pair to use.",
    )
    parser.add_argument(
        "--mode",
        default="all",
        choices=("all", "script", "image"),
        help="Run script generation only, image generation only, or both.",
    )
    parser.add_argument(
        "--date",
        help="Keyword date to load from MySQL in YYYY-MM-DD format. Defaults to today.",
    )
    parser.add_argument(
        "--keyword",
        help="Keyword to use directly. If provided, MySQL keyword lookup is skipped.",
    )
    parser.add_argument(
        "--script-file",
        help="Generated script text file to use for --mode image.",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory for generated script/image files. Relative paths are resolved from project root.",
    )
    return parser.parse_args(argv)


def resolve_target_date(date_text: str | None) -> str:
    """입력: 선택 날짜 문자열. 출력: DB 조회에 사용할 YYYY-MM-DD 날짜 문자열."""
    if not date_text:
        return datetime.now().date().isoformat()

    try:
        return datetime.strptime(date_text, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ValueError("--date must use YYYY-MM-DD format.") from exc


def resolve_output_dir(root_dir: Path, output_dir_text: str) -> Path:
    """입력: 프로젝트 루트와 출력 폴더 문자열. 출력: 절대 출력 폴더 경로."""
    output_dir = Path(output_dir_text)
    if not output_dir.is_absolute():
        output_dir = root_dir / output_dir
    return output_dir


def resolve_script_file(root_dir: Path, script_file_text: str) -> Path:
    """입력: 프로젝트 루트와 스크립트 파일 문자열. 출력: 절대 스크립트 파일 경로."""
    script_file = Path(script_file_text)
    if not script_file.is_absolute():
        script_file = root_dir / script_file
    if not script_file.exists():
        raise FileNotFoundError(f"Script file not found: {script_file}")
    return script_file


def resolve_keyword(args: argparse.Namespace) -> str:
    """입력: CLI 인자. 출력: 직접 입력 키워드 또는 DB에서 조회한 키워드."""
    if args.keyword and args.keyword.strip():
        return args.keyword.strip()

    db_kwargs = mysql_connect_kwargs()
    target_date = resolve_target_date(args.date)
    return fetch_latest_keyword(db_kwargs, target_date)


def romanize_hangul(text: str) -> str:
    """입력: 한글 포함 문자열. 출력: 파일명에 쓰기 쉬운 간단한 ASCII 로마자 문자열."""
    pieces: list[str] = []
    for char in text:
        code = ord(char)
        if 0xAC00 <= code <= 0xD7A3:
            offset = code - 0xAC00
            initial = offset // 588
            vowel = (offset % 588) // 28
            final = offset % 28
            pieces.append(
                HANGUL_INITIALS[initial] + HANGUL_VOWELS[vowel] + HANGUL_FINALS[final]
            )
        else:
            pieces.append(char)
    return "".join(pieces)


def build_keyword_stem(keyword: str) -> str:
    """입력: 생성 키워드. 출력: 짧고 직관적인 ASCII 파일명 stem."""
    romanized = romanize_hangul(keyword).lower()
    stem = re.sub(r"[^a-z0-9]+", "_", romanized).strip("_")
    stem = re.sub(r"_+", "_", stem)
    if not stem:
        stem = "keyword"
    return stem[:32].strip("_") or "keyword"


def build_timestamp_prefix() -> str:
    """입력: 없음. 출력: 파일명 앞에 붙일 yymmdd_hhmmss 형식 문자열."""
    return datetime.now().strftime("%y%m%d_%H%M%S")


def choose_output_stem(output_dir: Path, base_stem: str, mode: str) -> str:
    """입력: 출력 폴더, 키워드 기반 stem, 실행 모드. 출력: timestamp가 포함된 충돌 없는 stem."""
    suffixes = []
    if mode in {"all", "script"}:
        suffixes.append("_script.txt")
    if mode in {"all", "image"}:
        suffixes.append(".png")

    timestamped_stem = f"{build_timestamp_prefix()}_{base_stem}"
    stem = timestamped_stem
    index = 2
    while any((output_dir / f"{stem}{suffix}").exists() for suffix in suffixes):
        stem = f"{timestamped_stem}_{index}"
        index += 1
    return stem


def generate_script_file(
    *,
    keyword: str,
    output_stem: str,
    script_prompt_body: str,
    output_dir: Path,
) -> Path:
    """입력: 키워드와 템플릿 정보. 출력: codex가 생성한 스크립트 파일 경로."""
    output_name = f"{output_stem}_script.txt"
    prompt = build_script_prompt(script_prompt_body, keyword, output_name)
    exit_code = run_codex_exec(prompt=prompt, output_dir=output_dir)
    if exit_code != 0:
        raise RuntimeError(f"codex exec failed while generating script. exit_code={exit_code}")

    script_path = output_dir / output_name
    if not script_path.exists():
        raise FileNotFoundError(f"Expected generated script file not found: {script_path}")
    return script_path


def generate_image_file(
    *,
    output_stem: str,
    image_prompt_body: str,
    script_path: Path,
    output_dir: Path,
) -> Path:
    """입력: 이미지 프롬프트와 생성 스크립트 파일. 출력: codex가 생성한 이미지 파일 경로."""
    script_text = script_path.read_text(encoding="utf-8").strip()
    if not script_text:
        raise ValueError(f"Script file is empty: {script_path}")

    output_name = f"{output_stem}.png"
    prompt = build_image_prompt(image_prompt_body, script_text, output_name)
    exit_code = run_codex_exec(prompt=prompt, output_dir=output_dir)
    if exit_code != 0:
        raise RuntimeError(f"codex exec failed while generating image. exit_code={exit_code}")

    image_path = output_dir / output_name
    if not image_path.exists():
        raise FileNotFoundError(f"Expected generated image file not found: {image_path}")
    optimize_image_file(image_path)
    return image_path


def save_png_optimized(image: Image.Image, path: Path, colors: int | None = None) -> None:
    """입력: PIL 이미지와 색상 수. 출력: 최적화된 PNG 파일 저장."""
    output = image.convert("RGB")
    if colors is not None:
        output = output.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    output.save(path, format="PNG", optimize=True, compress_level=9)


def optimize_image_file(path: Path) -> None:
    """입력: 생성 이미지 경로. 출력: 1024px 이하, 1MB 미만이 되도록 원본 파일을 최적화."""
    with Image.open(path) as source:
        image = source.convert("RGB")

    max_side = max(image.size)
    if max_side > TARGET_IMAGE_MAX_SIDE:
        scale = TARGET_IMAGE_MAX_SIDE / max_side
        resized_size = (
            max(1, round(image.width * scale)),
            max(1, round(image.height * scale)),
        )
        image = image.resize(resized_size, Image.Resampling.LANCZOS)

    save_png_optimized(image, path)
    if path.stat().st_size < MAX_IMAGE_BYTES:
        return

    for colors in (256, 192, 128, 96, 64, 48, 32):
        save_png_optimized(image, path, colors=colors)
        if path.stat().st_size < MAX_IMAGE_BYTES:
            return

    while path.stat().st_size >= MAX_IMAGE_BYTES and max(image.size) > 640:
        resized_size = (
            max(1, round(image.width * 0.9)),
            max(1, round(image.height * 0.9)),
        )
        image = image.resize(resized_size, Image.Resampling.LANCZOS)
        save_png_optimized(image, path, colors=64)


def main(argv: list[str] | None = None) -> int:
    """입력: 선택 명령줄 인자. 출력: 프로그램 종료 코드."""
    args = parse_args(argv or sys.argv[1:])
    root_dir = Path(__file__).resolve().parent

    try:
        load_dotenv(root_dir / ".env")
        template = resolve_template(root_dir, args.template)
        output_dir = resolve_output_dir(root_dir, args.output_dir)

        script_path: Path | None = None
        keyword: str | None = None
        output_stem: str | None = None
        if args.mode in {"all", "script"}:
            keyword = resolve_keyword(args)
            output_dir.mkdir(parents=True, exist_ok=True)
            output_stem = choose_output_stem(
                output_dir=output_dir,
                base_stem=build_keyword_stem(keyword),
                mode=args.mode,
            )
            script_prompt_body = load_prompt(template.script_prompt)
            script_path = generate_script_file(
                keyword=keyword,
                output_stem=output_stem,
                script_prompt_body=script_prompt_body,
                output_dir=output_dir,
            )
            print(f"script: {script_path}")

        if args.mode in {"all", "image"}:
            if args.mode == "image":
                if not args.script_file:
                    raise ValueError("--mode image requires --script-file.")
                script_path = resolve_script_file(root_dir, args.script_file)
                stem_source = args.keyword.strip() if args.keyword and args.keyword.strip() else script_path.stem
                if stem_source.endswith("_script"):
                    stem_source = stem_source[: -len("_script")]
                output_dir.mkdir(parents=True, exist_ok=True)
                output_stem = choose_output_stem(
                    output_dir=output_dir,
                    base_stem=build_keyword_stem(stem_source),
                    mode=args.mode,
                )
            elif script_path is None:
                raise ValueError("Script generation did not produce a script file.")

            if output_stem is None:
                raise ValueError("Output file name stem was not resolved.")

            image_prompt_body = load_prompt(template.image_prompt)
            image_path = generate_image_file(
                output_stem=output_stem,
                image_prompt_body=image_prompt_body,
                script_path=script_path,
                output_dir=output_dir,
            )
            print(f"image: {image_path}")

        return 0
    except (FileNotFoundError, ValueError, RuntimeError, pymysql.MySQLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
