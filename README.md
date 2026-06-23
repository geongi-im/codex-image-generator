# codex-image-generator

MySQL에 저장된 키워드를 기준으로 짧은 스크립트와 이미지를 생성하고, 생성 결과를 다시 DB에 저장하는 Codex CLI 자동화 도구입니다.

## 주요 기능

- `n8n_publish_content` 테이블에서 대상 키워드 조회
- 키워드가 직접 입력되면 해당 날짜와 카테고리 row 조회 또는 신규 생성
- 선택한 프롬프트 템플릿으로 스크립트 생성
- 생성된 스크립트 또는 기존 DB content로 이미지 생성
- 생성된 content와 image_paths를 MySQL에 업데이트
- 생성 이미지를 1024px 이하, 1MB 미만을 목표로 최적화

## 요구사항

- Python 3.10 이상 권장
- MySQL 접속 정보와 `n8n_publish_content` 테이블
- Codex CLI 실행 환경
- Python 패키지: `requirements.txt`

## 설치

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

`.env`에 MySQL 접속 정보를 입력합니다.

```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=
MYSQL_PASSWORD=
MYSQL_DATABASE=
MYSQL_CHARSET=utf8mb4
CONTENT_COPY_PATH=
```

이미지 생성 결과를 다른 폴더에도 복사하려면 `CONTENT_COPY_PATH`에 시스템 절대경로를 입력합니다. 값이 비어 있으면 복사하지 않습니다.

```env
CONTENT_COPY_PATH=C:\absolute\copy\path
```

## 사용법

기본 실행은 오늘 날짜와 기본 템플릿(`explain_child`) 카테고리에 맞는 최신 키워드 row를 조회한 뒤 스크립트와 이미지를 모두 생성합니다.

```powershell
python main.py
```

키워드를 직접 지정하면 해당 날짜와 템플릿 카테고리에 맞는 row를 조회하고, 없으면 새 row를 만든 뒤 생성 작업을 진행합니다.

```powershell
python main.py --keyword "APEC"
```

특정 날짜와 템플릿 카테고리에 맞는 키워드를 사용합니다.

```powershell
python main.py --date 2026-05-24
```

스크립트만 생성합니다.

```powershell
python main.py --mode script --keyword "S&P500"
```

이미지만 생성합니다. `--mode image`에서는 `--script-file`을 지정하거나 DB에 기존 content가 있어야 합니다.

```powershell
python main.py --mode image --script-file output\sample_script.txt
```

출력 폴더를 지정합니다. 상대 경로는 프로젝트 루트 기준으로 해석됩니다.

```powershell
python main.py --output-dir output
```

`3s_quiz` 템플릿으로 전체 생성합니다.

```powershell
python main.py --template 3s_quiz
```

crontab처럼 키워드를 미리 알 수 없는 자동 실행에서는 템플릿만 지정해 이미지를 생성합니다. 날짜를 생략하면 실행일 기준 오늘 날짜를 사용합니다.

```powershell
python main.py --mode image --template explain_child
python main.py --mode image --template 3s_quiz
```

자주 쓰는 조합 명령입니다.

```powershell
# 특정 날짜와 키워드로 전체 생성
python main.py --date 2026-05-24 --keyword "APEC"

# 특정 템플릿, 날짜, 키워드로 전체 생성
python main.py --template 3s_quiz --date 2026-05-24 --keyword "APEC"

# 특정 템플릿과 출력 폴더를 지정해 스크립트만 생성
python main.py --mode script --template 3s_quiz --keyword "APEC" --output-dir output\quiz

# 기존 스크립트 파일로 이미지만 생성하고 출력 폴더 지정
python main.py --mode image --script-file output\sample_script.txt --output-dir output\image

# DB에 기존 content가 있는 row를 기준으로 이미지만 생성
python main.py --mode image --date 2026-05-24 --keyword "APEC"

# 키워드를 지정하지 않고 날짜와 템플릿 카테고리로 이미지만 생성
python main.py --mode image --template explain_child --date 2026-05-24
python main.py --mode image --template 3s_quiz --date 2026-05-24

# 특정 템플릿, 날짜, 키워드, 기존 스크립트 파일로 이미지만 생성
python main.py --mode image --template 3s_quiz --date 2026-05-24 --keyword "APEC" --script-file output\sample_script.txt
```

## CLI 옵션

```text
--template      사용할 프롬프트 템플릿입니다. 기본값: explain_child
--mode          실행 범위입니다. all, script, image 중 선택합니다. 기본값: all
--date          조회 또는 생성 기준 날짜입니다. YYYY-MM-DD 형식이며 기본값은 오늘입니다.
--keyword       직접 사용할 키워드입니다. 생략하면 --date와 --template 카테고리 기준 최신 row를 사용합니다.
--script-file   image 모드에서 사용할 기존 스크립트 파일입니다.
--output-dir    생성 파일을 저장할 폴더입니다. 기본값: output
```

## 템플릿

현재 지원하는 템플릿은 두 가지입니다.

- `explain_child`
  - `prompt/SCRIPT_EXPLAN_CHILD.md`
  - `prompt/IMAGE_EXPLAIN_CHILD.md`
- `3s_quiz`
  - `prompt/SCRIPT_3S_QUIZ.md`
  - `prompt/IMAGE_3S_QUIZ.md`

## DB 동작

코드는 `n8n_publish_content` 테이블의 다음 컬럼을 사용합니다.

- `idx`
- `category`
- `keyword`
- `content`
- `image_paths`
- `target_date`
- `threads_status`
- `website_status`

`--keyword`가 없으면 `target_date` 기준 최신 keyword row를 조회합니다. `--keyword`가 있으면 `category`, `keyword`, `target_date`가 일치하는 row를 찾고, 없으면 새 row를 생성합니다.

스크립트 생성 후에는 `content` 컬럼을 업데이트합니다. 이미지 생성 후에는 생성된 파일명을 JSON 배열 문자열로 만들어 `image_paths` 컬럼에 저장합니다.

## 출력

기본 출력 경로는 `output/`입니다. 파일명은 현재 시각과 키워드를 기준으로 만들어집니다.

- 스크립트: `{timestamp}_{keyword}_script.txt`
- 이미지: `{timestamp}_{keyword}.png`

`CONTENT_COPY_PATH` 환경변수가 설정되어 있으면 이미지 생성과 최적화가 끝난 뒤 같은 파일명을 해당 절대경로 폴더로 복사합니다. DB에는 기존처럼 생성된 이미지 파일명만 저장합니다.

이미 존재하는 파일과 충돌하면 뒤에 번호가 붙습니다.

## 프로젝트 구조

```text
.
├── main.py                 # CLI 진입점과 전체 생성 흐름
├── codex_exec.py           # Codex CLI 프롬프트 구성 및 실행
├── db_connector.py         # MySQL 연결과 쿼리 실행
├── requirements.txt        # Python 의존성
├── prompt/                 # 스크립트/이미지 생성 프롬프트 템플릿
└── utils/                  # 출력 파일명, 이미지 최적화, 보조 유틸
```

## 확인 명령

```powershell
python main.py --help
```
