from pathlib import Path
import os
import shutil
import subprocess


CODEX_BIN = "codex"
CODEX_SANDBOX = "danger-full-access"


class TemplateSpec:
    """프롬프트 템플릿 경로 묶음입니다."""

    def __init__(self, script_prompt, image_prompt):
        """
        스크립트 프롬프트와 이미지 프롬프트 경로를 보관합니다.

        input:
            script_prompt: 스크립트 생성 프롬프트 파일 경로.
            image_prompt: 이미지 생성 프롬프트 파일 경로.
        output:
            TemplateSpec 인스턴스의 내부 상태를 초기화합니다.
        """
        self.script_prompt = script_prompt
        self.image_prompt = image_prompt


TEMPLATES = {
    "explain_child": TemplateSpec(
        script_prompt=Path("prompt") / "SCRIPT_EXPLAN_CHILD.md",
        image_prompt=Path("prompt") / "IMAGE_EXPLAIN_CHILD.md",
    ),
    "3s_quiz": TemplateSpec(
        script_prompt=Path("prompt") / "SCRIPT_3S_QUIZ.md",
        image_prompt=Path("prompt") / "IMAGE_3S_QUIZ.md",
    ),
}


def template_keys():
    """
    사용할 수 있는 템플릿 키 목록을 반환합니다.

    input:
        없음.
    output:
        템플릿 키 문자열 목록.
    """
    return sorted(TEMPLATES.keys())


def resolve_template(root_dir, template_key):
    """
    템플릿 키에 맞는 프롬프트 파일 경로를 프로젝트 절대 경로로 변환합니다.

    input:
        root_dir: 프로젝트 루트 디렉터리 경로.
        template_key: 사용할 템플릿 키.
    output:
        절대 경로가 설정된 TemplateSpec 인스턴스.
    """
    try:
        template = TEMPLATES[template_key]
    except KeyError:
        allowed = ", ".join(template_keys())
        raise ValueError(f"Unknown template {template_key!r}. Use one of: {allowed}") from None

    return TemplateSpec(
        script_prompt=root_dir / template.script_prompt,
        image_prompt=root_dir / template.image_prompt,
    )


def load_prompt(path):
    """
    프롬프트 파일을 UTF-8 텍스트로 읽어 반환합니다.

    input:
        path: 읽어올 프롬프트 파일 경로.
    output:
        프롬프트 파일 전체 문자열.
    """
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def build_script_prompt(prompt_body, keyword, output_name):
    """
    Codex CLI에 전달할 스크립트 생성용 최종 프롬프트를 만듭니다.

    input:
        prompt_body: 스크립트 생성 규칙이 담긴 프롬프트 본문.
        keyword: 스크립트 생성에 사용할 키워드.
        output_name: 생성된 스크립트를 저장할 파일명.
    output:
        codex exec에 전달할 최종 프롬프트 문자열.
    """
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
The entire generated script must be fewer than 500 characters total, including spaces and line breaks.
This 500-character limit is mandatory even if SCRIPT_TEMPLATE describes per-post limits.
Write only the generated script text to OUTPUT_FILE in the current directory.
Do not modify any other files.
"""


def build_image_prompt(prompt_body, script_text, output_name):
    """
    Codex CLI에 전달할 이미지 생성용 최종 프롬프트를 만듭니다.

    input:
        prompt_body: 이미지 생성 규칙이 담긴 프롬프트 본문.
        script_text: 이미지 생성의 기준이 되는 완성 스크립트.
        output_name: 생성된 이미지를 저장할 파일명.
    output:
        codex exec에 전달할 최종 프롬프트 문자열.
    """
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
Use the built-in image generation tool only.
Do not create or execute local code to draw the image.
Do not use SVG, HTML, canvas, Pillow, matplotlib, charts, screenshots, vector primitives, or SVG-to-PNG conversion.
If the built-in image generation tool is unavailable, fail without creating OUTPUT_FILE.
Write the image to OUTPUT_FILE in the current directory.
Prefer a native output size whose longest side is 1024px or smaller.
Do not modify any other files.
"""


def run_codex_exec(prompt, output_dir):
    """
    지정한 출력 폴더에서 codex exec 명령을 실행합니다.

    input:
        prompt: codex exec에 전달할 작업 프롬프트.
        output_dir: 생성 파일이 저장될 작업 디렉터리.
    output:
        codex exec 프로세스 종료 코드.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        *resolve_codex_command(),
        "exec",
        "--sandbox",
        CODEX_SANDBOX,
        "--cd",
        str(output_dir),
        "--skip-git-repo-check",
        "-",
    ]

    completed = subprocess.run(cmd, check=False, input=prompt, text=True, encoding="utf-8")
    return completed.returncode


def resolve_codex_command():
    """
    현재 OS에서 실행 가능한 Codex CLI 명령 배열을 반환합니다.

    input:
        없음.
    output:
        subprocess.run에 넘길 Codex CLI 명령 배열.
    """
    if os.name == "nt":
        cmd_path = shutil.which("codex.cmd")
        if cmd_path:
            base_dir = Path(cmd_path).resolve().parent
            script_path = base_dir / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            node_path = base_dir / "node.exe"
            if script_path.exists():
                if node_path.exists():
                    return [str(node_path), str(script_path)]

                system_node = shutil.which("node.exe") or shutil.which("node")
                if system_node:
                    return [system_node, str(script_path)]

        exe_path = shutil.which("codex.exe")
        if exe_path:
            return [exe_path]

    return [shutil.which(CODEX_BIN) or CODEX_BIN]
