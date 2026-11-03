import base64
import json
import os
import urllib.error
import urllib.request


GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
GEMINI_IMAGE_MODEL_ENV = "GEMINI_IMAGE_MODEL"
DEFAULT_GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_API_TIMEOUT_SECONDS = 300
GEMINI_ERROR_TAIL_CHARS = 500


def generate_image_with_gemini_api(prompt, output_dir, output_name, aspect_ratio=None):
    """
    Gemini API(generateContent)를 직접 호출해 이미지를 생성합니다.

    API 키는 GEMINI_API_KEY, 모델은 GEMINI_IMAGE_MODEL(기본 gemini-3.1-flash-image)에서 읽습니다.
    응답 이미지는 JPEG일 수 있으며, 이후 optimize_image_file 이 PNG로 변환합니다.

    input:
        prompt: 이미지 생성 프롬프트.
        output_dir: 이미지를 저장할 폴더.
        output_name: 저장할 이미지 파일명.
        aspect_ratio: 이미지 가로세로 비율 문자열(예: "16:9", "4:5"). None이면 모델이 정합니다.
    output:
        output_dir / output_name 경로. 호출 실패나 이미지 없는 응답이면 RuntimeError를 발생시킵니다.
    """
    api_key = (os.environ.get(GEMINI_API_KEY_ENV) or "").strip()
    if not api_key:
        raise ValueError(f"{GEMINI_API_KEY_ENV} is required to generate images with the Gemini API.")
    model = (os.environ.get(GEMINI_IMAGE_MODEL_ENV) or "").strip() or DEFAULT_GEMINI_IMAGE_MODEL

    generation_config = {"responseModalities": ["IMAGE"]}
    if aspect_ratio:
        generation_config["imageConfig"] = {"aspectRatio": aspect_ratio}
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }
    request = urllib.request.Request(
        GEMINI_API_URL.format(model=model),
        data=json.dumps(body).encode("utf-8"),
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=GEMINI_API_TIMEOUT_SECONDS) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[-GEMINI_ERROR_TAIL_CHARS:]
        raise RuntimeError(f"Gemini API request failed. model={model} status={exc.code} body={detail!r}") from None
    except OSError as exc:
        raise RuntimeError(f"Gemini API request failed. model={model} detail={exc}") from None

    image_bytes = extract_gemini_image_bytes(data)
    if image_bytes is None:
        raise RuntimeError(f"Gemini API returned no image. model={model} {summarize_gemini_response(data)}")

    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / output_name
    destination.write_bytes(image_bytes)
    return destination


def extract_gemini_image_bytes(data):
    """
    Gemini API 응답에서 첫 번째 이미지 바이트를 꺼냅니다.

    input:
        data: generateContent 응답 JSON을 파싱한 딕셔너리.
    output:
        이미지 바이트. 이미지 파트가 없으면 None.
    """
    for candidate in data.get("candidates") or []:
        for part in (candidate.get("content") or {}).get("parts") or []:
            inline = part.get("inlineData")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
    return None


def summarize_gemini_response(data):
    """
    이미지가 없는 Gemini API 응답을 오류 메시지용 문자열로 요약합니다.

    input:
        data: generateContent 응답 JSON을 파싱한 딕셔너리.
    output:
        차단 사유, 종료 사유, 응답 텍스트 앞부분을 이어 붙인 문자열.
    """
    block_reason = (data.get("promptFeedback") or {}).get("blockReason")
    candidates = data.get("candidates") or []
    finish_reason = candidates[0].get("finishReason") if candidates else None
    texts = [
        part["text"]
        for candidate in candidates
        for part in (candidate.get("content") or {}).get("parts") or []
        if part.get("text")
    ]
    text = " ".join(texts)[:GEMINI_ERROR_TAIL_CHARS]
    return f"blockReason={block_reason} finishReason={finish_reason} text={text!r}"
