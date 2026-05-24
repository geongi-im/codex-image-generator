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


def fetch_one(db_config, query, params=None):
    """
    단일 row 조회 쿼리를 실행합니다.

    input:
        db_config: MySQL 접속 설정 딕셔너리.
        query: 실행할 SELECT 쿼리 문자열.
        params: 쿼리 파라미터 딕셔너리.
    output:
        조회된 row 딕셔너리. 없으면 None.
    """
    with connect_mysql(db_config) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query.strip(), params or {})
            return cursor.fetchone()


def execute_write(db_config, query, params=None):
    """
    INSERT, UPDATE, DELETE 쿼리를 실행하고 커밋합니다.

    input:
        db_config: MySQL 접속 설정 딕셔너리.
        query: 실행할 쓰기 쿼리 문자열.
        params: 쿼리 파라미터 딕셔너리.
    output:
        affected_rows와 lastrowid를 담은 딕셔너리.
    """
    with connect_mysql(db_config) as connection:
        with connection.cursor() as cursor:
            affected_rows = cursor.execute(query.strip(), params or {})
            lastrowid = cursor.lastrowid
        connection.commit()

    return {
        "affected_rows": int(affected_rows),
        "lastrowid": lastrowid,
    }
