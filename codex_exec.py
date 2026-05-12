from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


CODEX_BIN = "codex"
CODEX_SANDBOX = "danger-full-access"


@dataclass(frozen=True)
class TemplateSpec:
    """입력: 템플릿별 프롬프트 경로 설정. 출력: 스크립트/이미지 생성에 사용할 템플릿 메타데이터."""

    script_prompt: Path
    image_prompt: Path


TEMPLATES: dict[str, TemplateSpec] = {
    "explain_child": TemplateSpec(
        script_prompt=Path("prompt") / "SCRIPT_EXPLAN_CHILD.md",
        image_prompt=Path("prompt") / "IMAGE_EXPLAIN_CHILD.md",
    ),
    "3s_quiz": TemplateSpec(
        script_prompt=Path("prompt") / "SCRIPT_3S_QUIZ.md",
        image_prompt=Path("prompt") / "IMAGE_3S_QUIZ.md",
    ),
}


def template_keys() -> list[str]:
    """입력: 없음. 출력: CLI에서 선택 가능한 템플릿 키 목록."""
    return sorted(TEMPLATES.keys())


def resolve_template(root_dir: Path, template_key: str) -> TemplateSpec:
    """입력: 프로젝트 루트와 템플릿 키. 출력: 절대 경로로 변환된 TemplateSpec."""
    try:
        template = TEMPLATES[template_key]
    except KeyError:
        allowed = ", ".join(template_keys())
        raise ValueError(f"Unknown template {template_key!r}. Use one of: {allowed}") from None

    return TemplateSpec(
        script_prompt=root_dir / template.script_prompt,
        image_prompt=root_dir / template.image_prompt,
    )


def load_prompt(path: Path) -> str:
    """입력: 프롬프트 파일 경로. 출력: UTF-8로 읽은 프롬프트 전체 문자열."""
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def build_script_prompt(prompt_body: str, keyword: str, output_name: str) -> str:
    """입력: 스크립트 프롬프트, DB 키워드, 출력 파일명. 출력: codex exec용 스크립트 생성 프롬프트."""
    return f"""Use SCRIPT_TEMPLATE as the only writing rules document.

<SCRIPT_TEMPLATE>
{prompt_body}
</SCRIPT_TEMPLATE>

<KEYWORD>
{keyword}
</KEYWORD>

<OUTPUT_FILE>
{output_name}
</OUTPUT_FILE>

Generate the final script from KEYWORD by following SCRIPT_TEMPLATE.
Write only the generated script text to OUTPUT_FILE in the current directory.
Do not modify any other files.
"""


def build_image_prompt(prompt_body: str, script_text: str, output_name: str) -> str:
    """입력: 이미지 프롬프트, 생성된 스크립트, 출력 파일명. 출력: codex exec용 이미지 생성 프롬프트."""
    return f"""Use IMAGE_TEMPLATE as the only image generation rules document.

<IMAGE_TEMPLATE>
{prompt_body}
</IMAGE_TEMPLATE>

<GENERATED_SCRIPT>
{script_text}
</GENERATED_SCRIPT>

<OUTPUT_FILE>
{output_name}
</OUTPUT_FILE>

Generate exactly one raster image from GENERATED_SCRIPT by following IMAGE_TEMPLATE.
Write the image to OUTPUT_FILE in the current directory.
Prefer a native output size whose longest side is 1024px or smaller.
Do not modify any other files.
"""


def run_codex_exec(prompt: str, output_dir: Path) -> int:
    """입력: 최종 작업 프롬프트와 출력 폴더. 출력: codex exec 종료 코드."""
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        CODEX_BIN,
        "exec",
        "--sandbox",
        CODEX_SANDBOX,
        "--cd",
        str(output_dir),
        "--skip-git-repo-check",
        prompt,
    ]

    completed = subprocess.run(cmd, check=False, stdin=subprocess.DEVNULL)
    return completed.returncode
