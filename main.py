import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

import pymysql
from dotenv import load_dotenv

from codex_exec import (
    build_image_prompt,
    build_news_script_prompt,
    build_script_prompt,
    load_prompt,
    resolve_template,
    run_codex_exec,
    template_keys,
)
from db_connector import (
    execute_write,
    fetch_one,
    mysql_connect_kwargs,
)
from utils.common_util import (
    build_keyword_stem,
    choose_output_stem,
    optimize_image_file,
    resolve_output_dir,
    resolve_script_file,
    resolve_target_date,
)


PUBLISH_CONTENT_SELECT_COLUMNS = """
    idx,
    category,
    keyword,
    content,
    image_paths,
    comment,
    target_date,
    threads_status,
    website_status
"""

PUBLISH_CONTENT_BY_DATE_QUERY = f"""
SELECT
{PUBLISH_CONTENT_SELECT_COLUMNS}
FROM n8n_publish_content
WHERE target_date = %(target_date)s
  AND category = %(category)s
  AND keyword IS NOT NULL
  AND TRIM(keyword) <> ''
ORDER BY idx DESC
LIMIT 1
"""

PUBLISH_CONTENT_BY_KEYWORD_DATE_QUERY = f"""
SELECT
{PUBLISH_CONTENT_SELECT_COLUMNS}
FROM n8n_publish_content
WHERE target_date = %(target_date)s
  AND keyword = %(keyword)s
  AND category = %(category)s
ORDER BY idx DESC
LIMIT 1
"""

PUBLISH_CONTENT_BY_IDX_QUERY = f"""
SELECT
{PUBLISH_CONTENT_SELECT_COLUMNS}
FROM n8n_publish_content
WHERE idx = %(idx)s
LIMIT 1
"""

INSERT_PUBLISH_CONTENT_QUERY = """
INSERT INTO n8n_publish_content (category, keyword, target_date)
VALUES (%(category)s, %(keyword)s, %(target_date)s)
"""

UPDATE_CONTENT_BY_IDX_QUERY = """
UPDATE n8n_publish_content
SET content = %(content)s
WHERE idx = %(idx)s
"""

UPDATE_IMAGE_PATHS_BY_IDX_QUERY = """
UPDATE n8n_publish_content
SET image_paths = %(image_paths)s
WHERE idx = %(idx)s
"""

NEWS_QUIZ_BY_SOURCE_URL_QUERY = """
SELECT
    mq_source_url,
    mq_title,
    mq_keyword,
    mq_keyword_description,
    mq_selection_reason
FROM mq_news_quiz
WHERE mq_source_url = %(source_url)s
LIMIT 1
"""

TEMPLATE_CATEGORIES = {
    "3s_quiz": "3초퀴즈",
    "explain_child": "자녀에게설명하기",
    "news_3s_quiz": "3초퀴즈",
    "news_explain_child": "자녀에게설명하기",
}

MAX_CONTENT_CHARS = 500
NEWS_URL_PATTERN = re.compile(r"https?://\S+")
CONTENT_COPY_PATH_ENVS = {
    "explain_child": "CONTENT_COPY_PATH_EXPLAIN_CHILD",
    "3s_quiz": "CONTENT_COPY_PATH_3S_QUIZ",
    "news_explain_child": "CONTENT_COPY_PATH_EXPLAIN_CHILD",
    "news_3s_quiz": "CONTENT_COPY_PATH_3S_QUIZ",
}


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
        help="Keyword date to load or insert in MySQL using YYYY-MM-DD format. Defaults to today.",
    )
    parser.add_argument(
        "--keyword",
        help="Keyword to use directly. If provided, the row for --date is loaded or inserted.",
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


def has_field_value(value):
    """
    DB 필드에 실제 값이 채워져 있는지 확인합니다.

    input:
        value: DB에서 조회한 필드 값.
    output:
        값이 None이 아니고 공백 제거 후 비어 있지 않으면 True.
    """
    return value is not None and bool(str(value).strip())


def has_image_paths_value(value):
    """
    image_paths 필드에 실제 이미지 경로가 들어 있는지 확인합니다.

    input:
        value: DB에서 조회한 image_paths 필드 값.
    output:
        공백, 빈 JSON 배열, 빈 JSON 객체가 아니면 True.
    """
    if not has_field_value(value):
        return False

    text = str(value).strip()
    return text not in {"[]", "{}", '""'}


def get_direct_keyword(args):
    """
    CLI에서 직접 전달된 키워드를 정리합니다.

    input:
        args: CLI 실행 옵션 Namespace.
    output:
        직접 입력된 키워드 문자열. 값이 없으면 None.
    """
    if args.keyword and args.keyword.strip():
        return args.keyword.strip()
    return None


def resolve_template_category(template_key):
    """
    프롬프트 템플릿 키를 DB category 값으로 변환합니다.

    input:
        template_key: CLI로 받은 템플릿 키.
    output:
        n8n_publish_content.category에 저장할 한글 카테고리명.
    """
    try:
        return TEMPLATE_CATEGORIES[template_key]
    except KeyError:
        allowed = ", ".join(sorted(TEMPLATE_CATEGORIES))
        raise ValueError(f"Unknown template category {template_key!r}. Use one of: {allowed}") from None


def validate_content_length(content):
    """
    DB content 필드에 저장할 생성 텍스트 길이를 검증합니다.

    input:
        content: 생성된 스크립트 텍스트.
    output:
        없음. 500자 이상이면 ValueError를 발생시킵니다.
    """
    length = len(content)
    if length >= MAX_CONTENT_CHARS:
        raise ValueError(f"Generated content must be fewer than 500 characters. actual={length}")


def normalize_publish_content_row(row):
    """
    조회된 n8n_publish_content row의 키워드를 검증하고 정리합니다.

    input:
        row: DB에서 조회한 row 딕셔너리.
    output:
        keyword가 정리된 row 딕셔너리.
    """
    keyword = row.get("keyword")
    if keyword is None or not str(keyword).strip():
        raise ValueError("Keyword text from MySQL is empty.")

    row["keyword"] = str(keyword).strip()
    return row


def fetch_publish_content_by_date(db_config, target_date, category):
    """
    n8n_publish_content 테이블에서 지정 날짜와 카테고리의 최신 콘텐츠 row를 조회합니다.

    input:
        db_config: MySQL 접속 설정 딕셔너리.
        target_date: 조회 기준 날짜 문자열 (YYYY-MM-DD).
        category: 조회할 카테고리 문자열.
    output:
        idx, keyword, content, image_paths 등을 포함한 row 딕셔너리.
    """
    row = fetch_one(
        db_config,
        PUBLISH_CONTENT_BY_DATE_QUERY,
        {"category": category, "target_date": target_date},
    )
    if not row:
        raise ValueError(
            "No n8n_publish_content row returned for "
            f"target_date={target_date}, category={category}."
        )

    return normalize_publish_content_row(row)


def fetch_publish_content_by_keyword_date(db_config, keyword, target_date, category):
    """
    n8n_publish_content 테이블에서 지정 키워드와 날짜의 최신 row를 조회합니다.

    input:
        db_config: MySQL 접속 설정 딕셔너리.
        keyword: 조회할 키워드 문자열.
        target_date: 조회 기준 날짜 문자열 (YYYY-MM-DD).
        category: 조회할 카테고리 문자열.
    output:
        row 딕셔너리. 없으면 None.
    """
    row = fetch_one(
        db_config,
        PUBLISH_CONTENT_BY_KEYWORD_DATE_QUERY,
        {"category": category, "keyword": keyword, "target_date": target_date},
    )
    if not row:
        return None

    return normalize_publish_content_row(row)


def fetch_publish_content_by_idx(db_config, idx):
    """
    n8n_publish_content 테이블에서 idx가 일치하는 row를 조회합니다.

    input:
        db_config: MySQL 접속 설정 딕셔너리.
        idx: 조회할 n8n_publish_content 기본키.
    output:
        row 딕셔너리.
    """
    row = fetch_one(db_config, PUBLISH_CONTENT_BY_IDX_QUERY, {"idx": idx})
    if not row:
        raise ValueError(f"No n8n_publish_content row returned for idx={idx}.")

    return normalize_publish_content_row(row)


def extract_news_source_url(comment):
    """
    n8n_publish_content.comment 값에서 뉴스 URL을 추출합니다.

    input:
        comment: URL이 포함된 comment 필드 값.
    output:
        mq_news_quiz.mq_source_url 조회에 사용할 뉴스 URL 문자열.
    """
    text = str(comment or "").strip().replace("\\/", "/")
    match = NEWS_URL_PATTERN.search(text)
    if match:
        return match.group(0).rstrip(".,;:)]}'\"<>")

    if text.startswith("www."):
        trimmed = text.rstrip(".,;:)]}'\"<>")
        return f"https://{trimmed}"

    raise ValueError("No news URL found in n8n_publish_content.comment.")


def fetch_news_quiz_by_source_url(db_config, source_url):
    """
    뉴스 URL과 일치하는 mq_news_quiz row를 조회합니다.

    input:
        db_config: MySQL 접속 설정 딕셔너리.
        source_url: n8n_publish_content.comment에서 추출한 뉴스 URL.
    output:
        기사 제목, 뉴스 키워드, 키워드 설명, 선별 이유가 포함된 row 딕셔너리.
    """
    row = fetch_one(
        db_config,
        NEWS_QUIZ_BY_SOURCE_URL_QUERY,
        {"source_url": source_url},
    )
    if not row:
        raise ValueError(f"No mq_news_quiz row returned for mq_source_url={source_url}.")

    return row


def build_news_context_text(news_quiz_row):
    """
    mq_news_quiz row를 Codex 프롬프트에 전달할 짧은 컨텍스트로 변환합니다.

    input:
        news_quiz_row: mq_news_quiz에서 조회한 row 딕셔너리.
    output:
        구조화된 뉴스 컨텍스트 문자열.
    """
    fields = (
        ("뉴스 URL", news_quiz_row.get("mq_source_url")),
        ("뉴스기사제목", news_quiz_row.get("mq_title")),
        ("뉴스 추출 키워드", news_quiz_row.get("mq_keyword")),
        ("키워드 한줄 설명", news_quiz_row.get("mq_keyword_description")),
        ("뉴스 선별 이유", news_quiz_row.get("mq_selection_reason")),
    )
    return "\n".join(f"{label}: {str(value or '').strip()}" for label, value in fields)


def resolve_news_script_keyword(keyword, news_quiz_row):
    """
    뉴스 기반 스크립트에서 사용할 중심 키워드를 결정합니다.

    input:
        keyword: n8n_publish_content에서 조회한 키워드.
        news_quiz_row: mq_news_quiz에서 조회한 row 딕셔너리.
    output:
        뉴스 추출 키워드가 있으면 그 값을, 없으면 기존 키워드를 반환합니다.
    """
    news_keyword = news_quiz_row.get("mq_keyword")
    if news_keyword and str(news_keyword).strip():
        return str(news_keyword).strip()
    return keyword


def insert_publish_content_keyword_date(db_config, keyword, target_date, category):
    """
    n8n_publish_content 테이블에 키워드와 날짜만 가진 신규 row를 생성합니다.

    input:
        db_config: MySQL 접속 설정 딕셔너리.
        keyword: 신규 row에 저장할 키워드 문자열.
        target_date: 신규 row에 저장할 날짜 문자열 (YYYY-MM-DD).
        category: 신규 row에 저장할 카테고리 문자열.
    output:
        생성된 row 딕셔너리.
    """
    result = execute_write(
        db_config,
        INSERT_PUBLISH_CONTENT_QUERY,
        {"category": category, "keyword": keyword, "target_date": target_date},
    )
    return fetch_publish_content_by_idx(db_config, result["lastrowid"])


def update_content_by_idx(db_config, idx, content):
    """
    idx가 일치하는 행의 content 필드를 업데이트합니다.

    input:
        db_config: MySQL 접속 설정 딕셔너리.
        idx: 업데이트 대상 n8n_publish_content 행의 기본키.
        content: content 필드에 저장할 생성 스크립트.
    output:
        업데이트된 행 수.
    """
    result = execute_write(
        db_config,
        UPDATE_CONTENT_BY_IDX_QUERY,
        {"idx": idx, "content": content},
    )
    return result["affected_rows"]


def update_image_paths_by_idx(db_config, idx, image_paths):
    """
    idx가 일치하는 행의 image_paths 필드를 업데이트합니다.

    input:
        db_config: MySQL 접속 설정 딕셔너리.
        idx: 업데이트 대상 n8n_publish_content 행의 기본키.
        image_paths: image_paths 필드에 저장할 이미지 파일명 또는 경로 문자열.
    output:
        업데이트된 행 수.
    """
    result = execute_write(
        db_config,
        UPDATE_IMAGE_PATHS_BY_IDX_QUERY,
        {"idx": idx, "image_paths": image_paths},
    )
    return result["affected_rows"]


def load_target_content_row(args, db_config):
    """
    키워드가 직접 주어지지 않았을 때 작업 대상 DB row를 조회합니다.

    input:
        args: CLI 실행 옵션 Namespace.
        db_config: MySQL 접속 설정 딕셔너리.
    output:
        지정 날짜와 템플릿 카테고리의 최신 n8n_publish_content row 딕셔너리.
    """
    target_date = resolve_target_date(args.date)
    category = resolve_template_category(args.template)
    return fetch_publish_content_by_date(db_config, target_date, category)


def load_or_insert_direct_keyword_row(args, db_config, keyword):
    """
    직접 입력된 키워드와 날짜에 해당하는 row를 조회하고, 없으면 새로 생성합니다.

    input:
        args: CLI 실행 옵션 Namespace.
        db_config: MySQL 접속 설정 딕셔너리.
        keyword: 직접 입력된 키워드 문자열.
    output:
        조회 또는 생성된 n8n_publish_content row 딕셔너리.
    """
    target_date = resolve_target_date(args.date)
    category = resolve_template_category(args.template)
    target_row = fetch_publish_content_by_keyword_date(db_config, keyword, target_date, category)
    if target_row:
        print_target_row_status(target_row)
        return target_row

    target_row = insert_publish_content_keyword_date(db_config, keyword, target_date, category)
    print(
        "db_row_inserted: "
        f"idx={target_row.get('idx')} "
        f"category={target_row.get('category')} "
        f"keyword={target_row.get('keyword')} "
        f"target_date={target_row.get('target_date')}"
    )
    return target_row


def print_target_row_status(target_row):
    """
    자동 조회된 DB row의 작업 상태를 콘솔에 출력합니다.

    input:
        target_row: n8n_publish_content에서 조회한 row 딕셔너리.
    output:
        idx, keyword, content/image_paths 세팅 여부를 stdout에 출력합니다.
    """
    content_set = has_field_value(target_row.get("content"))
    image_paths_set = has_image_paths_value(target_row.get("image_paths"))
    print(
        "db_row: "
        f"idx={target_row.get('idx')} "
        f"keyword={target_row.get('keyword')} "
        f"content_set={content_set} "
        f"image_paths_set={image_paths_set}"
    )


def write_existing_script_file(output_stem, output_dir, script_text):
    """
    DB에 이미 저장된 content를 출력 폴더의 스크립트 파일로 저장합니다.

    input:
        output_stem: 생성 파일명에 사용할 stem.
        output_dir: 스크립트 파일을 저장할 출력 폴더 경로.
        script_text: DB content 필드에 저장되어 있던 스크립트 문자열.
    output:
        저장된 스크립트 파일 Path 객체.
    """
    if not script_text or not script_text.strip():
        raise ValueError("DB content is empty.")

    output_dir.mkdir(parents=True, exist_ok=True)
    script_path = output_dir / f"{output_stem}_script.txt"
    script_path.write_text(script_text.strip(), encoding="utf-8")
    return script_path


def update_generated_script_content(db_config, script_path, target_row):
    """
    생성된 스크립트 파일 내용을 DB content 필드에 저장합니다.

    input:
        db_config: MySQL 접속 설정 딕셔너리.
        script_path: 생성된 스크립트 텍스트 파일 경로.
        target_row: 업데이트 대상 DB row. idx 기준으로 업데이트합니다.
    output:
        DB에서 업데이트된 행 수.
    """
    script_text = script_path.read_text(encoding="utf-8").strip()
    if not script_text:
        raise ValueError(f"Script file is empty: {script_path}")
    validate_content_length(script_text)

    return update_content_by_idx(db_config, target_row["idx"], script_text)


def update_generated_image_path(db_config, image_path, target_row):
    """
    생성된 이미지 파일명을 DB image_paths 필드에 저장합니다.

    input:
        db_config: MySQL 접속 설정 딕셔너리.
        image_path: 생성된 이미지 파일 경로.
        target_row: 업데이트 대상 DB row. idx 기준으로 업데이트합니다.
    output:
        DB에서 업데이트된 행 수.
    """
    image_paths = json.dumps([image_path.name], ensure_ascii=False)
    return update_image_paths_by_idx(db_config, target_row["idx"], image_paths)


def resolve_content_copy_dir(template_key):
    copy_path_env = CONTENT_COPY_PATH_ENVS[template_key]
    copy_path_text = os.environ.get(copy_path_env, "").strip()
    if not copy_path_text:
        return None

    copy_dir = Path(copy_path_text)
    if not copy_dir.is_absolute():
        raise ValueError(f"{copy_path_env} must be an absolute path: {copy_path_text}")

    try:
        copy_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(f"Failed to prepare {copy_path_env}: {copy_dir}") from exc

    return copy_dir


def copy_generated_image(image_path, copy_dir):
    if copy_dir is None:
        return None

    destination = copy_dir / image_path.name
    try:
        shutil.copy2(image_path, destination)
    except OSError as exc:
        raise RuntimeError(f"Failed to copy generated image to {destination}") from exc

    return destination


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


def generate_news_script_file(keyword, news_context, output_stem, script_prompt_body, output_dir):
    """
    뉴스 컨텍스트를 포함해 Codex CLI로 스크립트 텍스트 파일을 생성합니다.

    input:
        keyword: 스크립트 생성에 사용할 키워드.
        news_context: 기사 제목과 키워드 설명 등 뉴스 기반 컨텍스트.
        output_stem: 생성 파일명에 사용할 stem.
        script_prompt_body: 뉴스 기반 스크립트 생성 프롬프트 본문.
        output_dir: 스크립트 파일을 저장할 출력 폴더 경로.
    output:
        생성된 스크립트 파일 Path 객체.
    """
    output_name = f"{output_stem}_script.txt"
    prompt = build_news_script_prompt(script_prompt_body, keyword, news_context, output_name)
    exit_code = run_codex_exec(prompt=prompt, output_dir=output_dir)
    if exit_code != 0:
        raise RuntimeError(f"codex exec failed while generating news script. exit_code={exit_code}")

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
        output_dir.mkdir(parents=True, exist_ok=True)

        db_config = mysql_connect_kwargs()
        target_row = None
        keyword = get_direct_keyword(args)

        if keyword:
            target_row = load_or_insert_direct_keyword_row(args, db_config, keyword)
        else:
            target_row = load_target_content_row(args, db_config)
            keyword = target_row["keyword"]
            print_target_row_status(target_row)

        output_stem = choose_output_stem(
            output_dir=output_dir,
            base_stem=build_keyword_stem(keyword),
            mode=args.mode,
        )

        script_path = None
        db_content_set = bool(target_row and has_field_value(target_row.get("content")))
        db_image_paths_set = bool(target_row and has_image_paths_value(target_row.get("image_paths")))

        if args.mode in {"all", "script"}:
            if db_content_set:
                script_path = write_existing_script_file(
                    output_stem,
                    output_dir,
                    str(target_row.get("content")),
                )
                print(f"script: {script_path} (from_db_content)")
                print("db_content_updated: skipped (already set)")
            elif template.uses_news_context:
                news_url = extract_news_source_url(target_row.get("comment"))
                news_quiz_row = fetch_news_quiz_by_source_url(db_config, news_url)
                script_prompt_body = load_prompt(template.script_prompt)
                script_path = generate_news_script_file(
                    keyword=resolve_news_script_keyword(keyword, news_quiz_row),
                    news_context=build_news_context_text(news_quiz_row),
                    output_stem=output_stem,
                    script_prompt_body=script_prompt_body,
                    output_dir=output_dir,
                )
                validate_content_length(script_path.read_text(encoding="utf-8").strip())
                print(f"script: {script_path}")
                updated_rows = update_generated_script_content(
                    db_config=db_config,
                    script_path=script_path,
                    target_row=target_row,
                )
                print(f"db_content_updated: {updated_rows}")
            else:
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
                    script_path=script_path,
                    target_row=target_row,
                )
                print(f"db_content_updated: {updated_rows}")

        if args.mode in {"all", "image"}:
            if db_image_paths_set:
                print(f"image: skipped (already set: {target_row.get('image_paths')})")
                print("db_image_paths_updated: skipped (already set)")
                return 0

            if args.mode == "image":
                if args.script_file:
                    script_path = resolve_script_file(root_dir, args.script_file)
                elif db_content_set:
                    script_path = write_existing_script_file(
                        output_stem,
                        output_dir,
                        str(target_row.get("content")),
                    )
                    print(f"script: {script_path} (from_db_content)")
                else:
                    raise ValueError("--mode image requires --script-file or existing DB content.")
            elif script_path is None:
                raise ValueError("Script generation did not produce a script file.")

            content_copy_dir = resolve_content_copy_dir(args.template)
            image_prompt_body = load_prompt(template.image_prompt)
            image_path = generate_image_file(
                output_stem=output_stem,
                image_prompt_body=image_prompt_body,
                script_path=script_path,
                output_dir=output_dir,
            )
            print(f"image: {image_path}")

            copied_image_path = copy_generated_image(image_path, content_copy_dir)
            if copied_image_path:
                print(f"image_copied: {copied_image_path}")

            updated_rows = update_generated_image_path(
                db_config=db_config,
                image_path=image_path,
                target_row=target_row,
            )
            print(f"db_image_paths_updated: {updated_rows}")

        return 0
    except (FileNotFoundError, ValueError, RuntimeError, pymysql.MySQLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
