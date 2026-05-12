import argparse
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
from db_connector import (
    fetch_latest_keyword,
    keyword_exists,
    mysql_connect_kwargs,
    update_content_by_keyword,
    update_image_paths_by_keyword,
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


def parse_args(argv):
    """
    명령줄 인자를 파싱하여 실행 옵션을 만듭니다.

    input:
        argv: sys.argv에서 프로그램명을 제외한 인자 목록.
    output:
        argparse.Namespace 형태의 실행 옵션.
    """
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


def resolve_target_date(date_text):
    """
    CLI로 받은 날짜값을 DB 조회용 날짜 문자열로 변환합니다.

    input:
        date_text: YYYY-MM-DD 형식의 날짜 문자열. 값이 없으면 오늘 날짜를 사용합니다.
    output:
        YYYY-MM-DD 형식의 날짜 문자열.
    """
    if not date_text:
        return datetime.now().date().isoformat()

    try:
        return datetime.strptime(date_text, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ValueError("--date must use YYYY-MM-DD format.") from exc


def resolve_output_dir(root_dir, output_dir_text):
    """
    출력 폴더 문자열을 절대 경로로 변환합니다.

    input:
        root_dir: 프로젝트 루트 디렉터리 경로.
        output_dir_text: CLI로 받은 출력 폴더 경로 문자열.
    output:
        절대 경로로 변환된 출력 폴더 Path 객체.
    """
    output_dir = Path(output_dir_text)
    if not output_dir.is_absolute():
        output_dir = root_dir / output_dir
    return output_dir


def resolve_script_file(root_dir, script_file_text):
    """
    이미지 생성에 사용할 스크립트 파일 경로를 확인합니다.

    input:
        root_dir: 프로젝트 루트 디렉터리 경로.
        script_file_text: CLI로 받은 스크립트 파일 경로 문자열.
    output:
        존재가 확인된 스크립트 파일 Path 객체.
    """
    script_file = Path(script_file_text)
    if not script_file.is_absolute():
        script_file = root_dir / script_file
    if not script_file.exists():
        raise FileNotFoundError(f"Script file not found: {script_file}")
    return script_file


def resolve_keyword(args, db_config):
    """
    직접 입력 키워드 또는 DB 조회 키워드를 결정합니다.

    input:
        args: CLI 실행 옵션 Namespace.
        db_config: MySQL 접속 설정 딕셔너리.
    output:
        콘텐츠 생성에 사용할 키워드 문자열.
    """
    if args.keyword and args.keyword.strip():
        return args.keyword.strip()

    target_date = resolve_target_date(args.date)
    return fetch_latest_keyword(db_config, target_date)


def update_generated_script_content(db_config, keyword, script_path):
    """
    생성된 스크립트 파일 내용을 DB content 필드에 저장합니다.

    input:
        db_config: MySQL 접속 설정 딕셔너리.
        keyword: 업데이트 대상 행을 찾기 위한 키워드.
        script_path: 생성된 스크립트 텍스트 파일 경로.
    output:
        DB에서 업데이트된 행 수.
    """
    script_text = script_path.read_text(encoding="utf-8").strip()
    if not script_text:
        raise ValueError(f"Script file is empty: {script_path}")
    return update_content_by_keyword(db_config, keyword=keyword, content=script_text)


def update_generated_image_path(db_config, keyword, image_path):
    """
    생성된 이미지 파일명을 DB image_paths 필드에 저장합니다.

    input:
        db_config: MySQL 접속 설정 딕셔너리.
        keyword: 업데이트 대상 행을 찾기 위한 키워드.
        image_path: 생성된 이미지 파일 경로.
    output:
        DB에서 업데이트된 행 수.
    """
    return update_image_paths_by_keyword(
        db_config,
        keyword=keyword,
        image_paths=image_path.name,
    )


def romanize_hangul(text):
    """
    한글 문자열을 파일명에 사용할 수 있는 간단한 로마자 문자열로 변환합니다.

    input:
        text: 한글 또는 영문이 포함된 원본 문자열.
    output:
        ASCII 로마자 중심으로 변환된 문자열.
    """
    pieces = []
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


def build_keyword_stem(keyword):
    """
    키워드 기반의 짧은 파일명 stem을 생성합니다.

    input:
        keyword: 콘텐츠 생성에 사용한 키워드.
    output:
        영문, 숫자, 밑줄로만 구성된 파일명 stem 문자열.
    """
    romanized = romanize_hangul(keyword).lower()
    stem = re.sub(r"[^a-z0-9]+", "_", romanized).strip("_")
    stem = re.sub(r"_+", "_", stem)
    if not stem:
        stem = "keyword"
    return stem[:32].strip("_") or "keyword"


def build_timestamp_prefix():
    """
    파일명 앞에 붙일 현재 시각 기반 prefix를 생성합니다.

    input:
        없음.
    output:
        yymmdd_hhmmss 형식의 시간 문자열.
    """
    return datetime.now().strftime("%y%m%d_%H%M%S")


def choose_output_stem(output_dir, base_stem, mode):
    """
    출력 폴더에서 충돌하지 않는 최종 파일명 stem을 선택합니다.

    input:
        output_dir: 생성 파일을 저장할 출력 폴더 경로.
        base_stem: 키워드에서 만든 기본 파일명 stem.
        mode: 실행 모드 문자열 (all, script, image).
    output:
        timestamp와 키워드 stem이 포함된 충돌 없는 파일명 stem.
    """
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


def generate_script_file(keyword, output_stem, script_prompt_body, output_dir):
    """
    Codex CLI를 실행하여 스크립트 텍스트 파일을 생성합니다.

    input:
        keyword: 스크립트 생성에 사용할 키워드.
        output_stem: 생성 파일명에 사용할 stem.
        script_prompt_body: 스크립트 생성 프롬프트 본문.
        output_dir: 스크립트 파일을 저장할 출력 폴더 경로.
    output:
        생성된 스크립트 파일 Path 객체.
    """
    output_name = f"{output_stem}_script.txt"
    prompt = build_script_prompt(script_prompt_body, keyword, output_name)
    exit_code = run_codex_exec(prompt=prompt, output_dir=output_dir)
    if exit_code != 0:
        raise RuntimeError(f"codex exec failed while generating script. exit_code={exit_code}")

    script_path = output_dir / output_name
    if not script_path.exists():
        raise FileNotFoundError(f"Expected generated script file not found: {script_path}")
    return script_path


def generate_image_file(output_stem, image_prompt_body, script_path, output_dir):
    """
    Codex CLI를 실행하여 이미지 파일을 생성하고 최적화합니다.

    input:
        output_stem: 생성 파일명에 사용할 stem.
        image_prompt_body: 이미지 생성 프롬프트 본문.
        script_path: 이미지 생성 기준이 되는 스크립트 파일 경로.
        output_dir: 이미지 파일을 저장할 출력 폴더 경로.
    output:
        생성된 이미지 파일 Path 객체.
    """
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


def save_png_optimized(image, path, colors=None):
    """
    PIL 이미지를 최적화된 PNG 파일로 저장합니다.

    input:
        image: 저장할 PIL Image 객체.
        path: PNG 파일을 저장할 경로.
        colors: 색상 수를 줄일 때 사용할 팔레트 색상 수. 값이 없으면 원본 RGB를 유지합니다.
    output:
        지정한 경로에 PNG 파일을 저장합니다.
    """
    output = image.convert("RGB")
    if colors is not None:
        output = output.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    output.save(path, format="PNG", optimize=True, compress_level=9)


def optimize_image_file(path):
    """
    생성된 이미지 파일을 1024px 이하, 1MB 미만이 되도록 최적화합니다.

    input:
        path: 최적화할 이미지 파일 경로.
    output:
        같은 경로의 이미지 파일을 최적화된 PNG로 덮어씁니다.
    """
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


def main(argv=None):
    """
    CLI 진입점으로 전체 스크립트/이미지 생성 흐름을 실행합니다.

    input:
        argv: 테스트나 외부 호출에서 전달할 명령줄 인자 목록. 값이 없으면 sys.argv를 사용합니다.
    output:
        프로그램 종료 코드. 성공 시 0, 처리 실패 시 2, 사용자 중단 시 130.
    """
    args = parse_args(argv or sys.argv[1:])
    root_dir = Path(__file__).resolve().parent

    try:
        load_dotenv(root_dir / ".env")
        template = resolve_template(root_dir, args.template)
        output_dir = resolve_output_dir(root_dir, args.output_dir)

        db_config = None
        script_path = None
        keyword = None
        output_stem = None

        if args.mode in {"all", "script"}:
            db_config = mysql_connect_kwargs()
            keyword = resolve_keyword(args, db_config)
            if not keyword_exists(db_config, keyword):
                print(f"warning: keyword not found in n8n_publish_content: {keyword}", file=sys.stderr)

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

            updated_rows = update_generated_script_content(
                db_config=db_config,
                keyword=keyword,
                script_path=script_path,
            )
            print(f"db_content_updated: {updated_rows}")

        if args.mode in {"all", "image"}:
            if args.mode == "image":
                if not args.script_file:
                    raise ValueError("--mode image requires --script-file.")
                script_path = resolve_script_file(root_dir, args.script_file)
                keyword = args.keyword.strip() if args.keyword and args.keyword.strip() else None
                stem_source = keyword or script_path.stem
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

            if keyword:
                if db_config is None:
                    db_config = mysql_connect_kwargs()
                updated_rows = update_generated_image_path(
                    db_config=db_config,
                    keyword=keyword,
                    image_path=image_path,
                )
                print(f"db_image_paths_updated: {updated_rows}")
            else:
                print("db_image_paths_updated: skipped (no keyword)")

        return 0
    except (FileNotFoundError, ValueError, RuntimeError, pymysql.MySQLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
