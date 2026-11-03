from agy_exec import generate_image_with_agy
from codex_exec import generate_image_with_codex
from gemini_api_exec import generate_image_with_gemini_api


# 이미지 provider 선택과 등록만 담당하는 공통 모듈입니다. 실제 생성 로직은 호출 주체별 파일에 있습니다.
#   codex      -> codex_exec.py
#   agy        -> agy_exec.py
#   gemini_api -> gemini_api_exec.py
#
# 모든 provider 함수는 (prompt, output_dir, output_name, aspect_ratio=None)을 받아
# output_dir / output_name 경로에 이미지를 만들고 그 경로를 반환합니다. 실패하면 예외를 발생시킵니다.
# aspect_ratio를 지정할 수 없는 provider는 이 값을 무시합니다.

IMAGE_PROVIDER_ENV = "IMAGE_PROVIDER"
DEFAULT_IMAGE_PROVIDER = "codex"

IMAGE_PROVIDERS = {
    "codex": generate_image_with_codex,
    "agy": generate_image_with_agy,
    "gemini_api": generate_image_with_gemini_api,
}


def image_provider_keys():
    """
    사용할 수 있는 이미지 provider 키 목록을 반환합니다.

    input:
        없음.
    output:
        provider 키 문자열 목록.
    """
    return sorted(IMAGE_PROVIDERS.keys())


def resolve_image_provider(name):
    """
    provider 이름에 맞는 이미지 생성 함수를 반환합니다.

    input:
        name: IMAGE_PROVIDER 환경변수 값. 비어 있으면 기본값(codex)을 사용합니다.
    output:
        (prompt, output_dir, output_name, aspect_ratio=None)을 받아 이미지 파일 경로를 반환하는 함수.
    """
    key = (name or "").strip().lower() or DEFAULT_IMAGE_PROVIDER
    try:
        return IMAGE_PROVIDERS[key]
    except KeyError:
        allowed = ", ".join(image_provider_keys())
        raise ValueError(f"Unknown {IMAGE_PROVIDER_ENV} {name!r}. Use one of: {allowed}") from None
