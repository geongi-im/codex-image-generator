from __future__ import annotations

import pymysql
from pymysql.cursors import DictCursor


# 키워드 조회 쿼리는 코드에서 관리합니다. 실제 스키마가 바뀌면 이 상수를 수정하세요.
KEYWORD_QUERY = """
SELECT keyword
FROM content_keywords
WHERE DATE(keyword_date) = %(target_date)s
ORDER BY keyword_date DESC, id DESC
LIMIT 1
"""


def build_keyword_query_params(target_date: str) -> dict[str, str]:
    """입력: 조회 기준 날짜(YYYY-MM-DD). 출력: SQL에서 사용할 파라미터 딕셔너리."""
    return {"target_date": target_date}


def fetch_latest_keyword(db_config: dict, target_date: str) -> str:
    """입력: pymysql 접속 설정과 조회 날짜. 출력: 해당 날짜의 최신 키워드 문자열."""
    cfg = {**db_config, "cursorclass": DictCursor}
    params = build_keyword_query_params(target_date)

    with pymysql.connect(**cfg) as connection:
        with connection.cursor() as cursor:
            cursor.execute(KEYWORD_QUERY.strip(), params)
            row = cursor.fetchone()

    if not row:
        raise ValueError(f"No keyword row returned for target_date={target_date}.")

    if not isinstance(row, dict):
        raise ValueError("Expected DictCursor row (mapping).")

    keyword = next(iter(row.values()))
    if keyword is None or not str(keyword).strip():
        raise ValueError("Keyword text from MySQL is empty.")

    return str(keyword).strip()
