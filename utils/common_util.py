from datetime import datetime
from pathlib import Path
import re

from PIL import Image


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


def resolve_target_date(date_text):
    """
    날짜 문자열을 DB 조회에 사용할 YYYY-MM-DD 형식으로 변환합니다.

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
        output_dir_text: CLI 또는 설정에서 받은 출력 폴더 경로 문자열.
    output:
        절대 경로로 변환된 출력 폴더 Path 객체.
    """
    output_dir = Path(output_dir_text)
    if not output_dir.is_absolute():
        output_dir = root_dir / output_dir
    return output_dir


def resolve_script_file(root_dir, script_file_text):
    """
    스크립트 파일 경로를 절대 경로로 변환하고 존재 여부를 확인합니다.

    input:
        root_dir: 프로젝트 루트 디렉터리 경로.
        script_file_text: CLI 또는 설정에서 받은 스크립트 파일 경로 문자열.
    output:
        존재가 확인된 스크립트 파일 Path 객체.
    """
    script_file = Path(script_file_text)
    if not script_file.is_absolute():
        script_file = root_dir / script_file
    if not script_file.exists():
        raise FileNotFoundError(f"Script file not found: {script_file}")
    return script_file


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
