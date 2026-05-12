import os
from contextlib import contextmanager

import pymysql
from pymysql.cursors import DictCursor


REQUIRED_MYSQL_ENV = (
    "MYSQL_HOST",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DATABASE",
)

LATEST_KEYWORD_QUERY = """
SELECT keyword
FROM n8n_publish_content
WHERE target_date = %(target_date)s
  AND keyword IS NOT NULL
  AND TRIM(keyword) <> ''
ORDER BY idx DESC
LIMIT 1
"""

KEYWORD_EXISTS_QUERY = """
SELECT EXISTS(
    SELECT 1
    FROM n8n_publish_content
    WHERE keyword = %(keyword)s
) AS exists_flag
"""

UPDATE_CONTENT_QUERY = """
UPDATE n8n_publish_content
SET content = %(content)s
WHERE keyword = %(keyword)s
ORDER BY idx DESC
LIMIT 1
"""

UPDATE_IMAGE_PATHS_QUERY = """
UPDATE n8n_publish_content
SET image_paths = %(image_paths)s
WHERE keyword = %(keyword)s
ORDER BY idx DESC
LIMIT 1
"""


def mysql_connect_kwargs():
    """
    환경변수에서 MySQL 접속 설정을 읽어 반환합니다.

    input:
        없음. .env 또는 시스템 환경변수의 MYSQL_* 값을 사용합니다.
    output:
        pymysql.connect에 전달할 접속 설정 딕셔너리.
    """
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


@contextmanager
def connect_mysql(db_config):
    """
    DictCursor를 사용하는 MySQL 연결 컨텍스트를 생성합니다.

    input:
        db_config: pymysql.connect에 전달할 접속 설정 딕셔너리.
    output:
        with 문에서 사용할 MySQL connection 객체.
    """
    cfg = {**db_config, "cursorclass": DictCursor}
    connection = pymysql.connect(**cfg)
    try:
        yield connection
    finally:
        connection.close()


def fetch_latest_keyword(db_config, target_date):
    """
    n8n_publish_content 테이블에서 지정 날짜의 최신 키워드를 조회합니다.

    input:
        db_config: MySQL 접속 설정 딕셔너리.
        target_date: 조회 기준 날짜 문자열 (YYYY-MM-DD).
    output:
        조회된 최신 키워드 문자열.
    """
    with connect_mysql(db_config) as connection:
        with connection.cursor() as cursor:
            cursor.execute(LATEST_KEYWORD_QUERY.strip(), {"target_date": target_date})
            row = cursor.fetchone()

    if not row:
        raise ValueError(f"No keyword row returned for target_date={target_date}.")

    keyword = row.get("keyword")
    if keyword is None or not str(keyword).strip():
        raise ValueError("Keyword text from MySQL is empty.")

    return str(keyword).strip()


def keyword_exists(db_config, keyword):
    """
    n8n_publish_content 테이블에 특정 키워드가 존재하는지 확인합니다.

    input:
        db_config: MySQL 접속 설정 딕셔너리.
        keyword: 존재 여부를 확인할 키워드.
    output:
        키워드가 존재하면 True, 없으면 False.
    """
    with connect_mysql(db_config) as connection:
        with connection.cursor() as cursor:
            cursor.execute(KEYWORD_EXISTS_QUERY.strip(), {"keyword": keyword})
            row = cursor.fetchone()

    return bool(row and row.get("exists_flag"))


def is_duplicate_keyword(db_config, keyword):
    """
    특정 키워드가 이미 등록된 중복 키워드인지 확인합니다.

    input:
        db_config: MySQL 접속 설정 딕셔너리.
        keyword: 중복 여부를 확인할 키워드.
    output:
        이미 등록된 키워드이면 True, 아니면 False.
    """
    return keyword_exists(db_config, keyword)


def update_content_by_keyword(db_config, keyword, content):
    """
    키워드가 일치하는 최신 행의 content 필드를 업데이트합니다.

    input:
        db_config: MySQL 접속 설정 딕셔너리.
        keyword: 업데이트 대상 행을 찾기 위한 키워드.
        content: content 필드에 저장할 생성 스크립트.
    output:
        업데이트된 행 수.
    """
    with connect_mysql(db_config) as connection:
        with connection.cursor() as cursor:
            affected_rows = cursor.execute(
                UPDATE_CONTENT_QUERY.strip(),
                {"keyword": keyword, "content": content},
            )
        connection.commit()

    return int(affected_rows)


def update_image_paths_by_keyword(db_config, keyword, image_paths):
    """
    키워드가 일치하는 최신 행의 image_paths 필드를 업데이트합니다.

    input:
        db_config: MySQL 접속 설정 딕셔너리.
        keyword: 업데이트 대상 행을 찾기 위한 키워드.
        image_paths: image_paths 필드에 저장할 이미지 파일명 또는 경로 문자열.
    output:
        업데이트된 행 수.
    """
    with connect_mysql(db_config) as connection:
        with connection.cursor() as cursor:
            affected_rows = cursor.execute(
                UPDATE_IMAGE_PATHS_QUERY.strip(),
                {"keyword": keyword, "image_paths": image_paths},
            )
        connection.commit()

    return int(affected_rows)
