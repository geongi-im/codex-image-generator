from pathlib import Path
import os
import shutil
import subprocess
import time


AGY_BIN = "agy"
AGY_MODEL = "gemini-3.8-flash-low"
AGY_PRINT_TIMEOUT = "420s"
AGY_PROCESS_TIMEOUT_SECONDS = 480
AGY_BRAIN_DIR = Path.home() / ".gemini" / "antigravity-cli" / "brain"
AGY_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
AGY_OUTPUT_TAIL_CHARS = 500


def generate_image_with_agy(prompt, output_dir, output_name, aspect_ratio=None):
    """
    Antigravity CLI(agy)로 이미지를 생성하고 output_dir / output_name 으로 복사합니다.

    agy는 이미지를 지정한 폴더가 아니라 AGY_BRAIN_DIR 아래 세션 폴더에 저장하고,
    실패해도 종료 코드 0으로 끝납니다. 그래서 실행 이후 새로 생긴 이미지를 찾아서 복사합니다.
    복사된 파일은 JPEG일 수 있으며, 이후 optimize_image_file 이 PNG로 변환합니다.

    input:
        prompt: 이미지 생성 프롬프트.
        output_dir: 이미지를 저장할 폴더.
        output_name: 저장할 이미지 파일명.
        aspect_ratio: 사용하지 않습니다.
    output:
        output_dir / output_name 경로. 이미지가 만들어지지 않으면 RuntimeError를 발생시킵니다.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = time.time() - 1

    cmd = [
        resolve_agy_command(),
        "-p",
        prompt,
        "--model",
        AGY_MODEL,
        "--print-timeout",
        AGY_PRINT_TIMEOUT,
    ]
    try:
        completed = subprocess.run(
            cmd,
            cwd=output_dir,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=AGY_PROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"agy timed out while generating image. timeout={AGY_PROCESS_TIMEOUT_SECONDS}s") from None
    except OSError as exc:
        raise RuntimeError(f"failed to run agy CLI. Install it and log in first. detail={exc}") from None

    if completed.returncode != 0:
        raise RuntimeError(
            f"agy failed while generating image. exit_code={completed.returncode} "
            f"{summarize_agy_output(completed)}"
        )

    generated_path = find_agy_generated_image(started_at)
    if generated_path is None:
        raise RuntimeError(f"agy did not produce an image. {summarize_agy_output(completed)}")

    destination = output_dir / output_name
    shutil.copy2(generated_path, destination)
    return destination


def resolve_agy_command():
    """
    실행할 agy 실행 파일 경로를 반환합니다.

    PATH에서 먼저 찾고, 없으면 설치 스크립트 기본 위치(%LOCALAPPDATA%\\agy\\bin\\agy.exe)를 확인합니다.
    설치 직후 열려 있던 터미널이나 예약 작업에는 PATH가 반영되지 않을 수 있기 때문입니다.

    input:
        없음.
    output:
        subprocess.run에 넘길 agy 실행 파일 경로 문자열.
    """
    found = shutil.which(AGY_BIN)
    if found:
        return found

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        installed = Path(local_app_data) / "agy" / "bin" / "agy.exe"
        if installed.exists():
            return str(installed)

    return AGY_BIN


def find_agy_generated_image(started_at):
    """
    started_at 이후 agy 세션 폴더에 새로 생긴 이미지 중 가장 최근 파일을 찾습니다.

    agy가 이미지를 한 번 만든 뒤 수정본을 다시 만들면 여러 장이 생기므로, 마지막 파일을 최종본으로 봅니다.

    input:
        started_at: 이 시각(time.time 기준) 이후에 수정된 파일만 대상으로 합니다.
    output:
        가장 최근 이미지 Path. 없으면 None.
    """
    if not AGY_BRAIN_DIR.exists():
        return None

    candidates = []
    for session_dir in AGY_BRAIN_DIR.iterdir():
        if not session_dir.is_dir() or session_dir.stat().st_mtime < started_at:
            continue
        for path in session_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in AGY_IMAGE_SUFFIXES and path.stat().st_mtime >= started_at:
                candidates.append(path)

    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def summarize_agy_output(completed):
    """
    agy 실행 결과의 stdout/stderr 끝부분을 오류 메시지용 문자열로 만듭니다.

    input:
        completed: subprocess.CompletedProcess 결과.
    output:
        stdout/stderr 끝부분을 이어 붙인 문자열.
    """
    stdout = (completed.stdout or "").strip()[-AGY_OUTPUT_TAIL_CHARS:]
    stderr = (completed.stderr or "").strip()[-AGY_OUTPUT_TAIL_CHARS:]
    return f"stdout={stdout!r} stderr={stderr!r}"
