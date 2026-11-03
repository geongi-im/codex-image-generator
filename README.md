# codex-image-generator

MySQL에 저장된 키워드를 기준으로 짧은 스크립트와 이미지를 생성하고, 생성 결과를 다시 DB에 저장하는 Codex CLI 자동화 도구입니다.

## 주요 기능

- `n8n_publish_content` 테이블에서 대상 키워드 조회
- 키워드가 직접 입력되면 해당 날짜와 카테고리 row 조회 또는 신규 생성
- 선택한 프롬프트 템플릿으로 스크립트 생성
- 생성된 스크립트 또는 기존 DB content로 이미지 생성
- 생성된 content와 image_paths를 MySQL에 업데이트
- 뉴스 기반 템플릿(`news_explain_child`, `news_3s_quiz`)은 `comment`의 뉴스 URL과 `mq_news_quiz` 정보를 함께 사용해 스크립트와 이미지를 생성
- 생성 이미지를 1024px 이하, 1MB 미만을 목표로 최적화

## 요구사항

- Python 3.10 이상 권장
- MySQL 접속 정보와 `n8n_publish_content` 테이블
- Codex CLI 실행 환경 (스크립트 생성, 기본 이미지 생성)
- 이미지를 Antigravity CLI로 생성하려면 `agy` 설치와 로그인 (`IMAGE_PROVIDER=agy`)
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
CONTENT_COPY_PATH_EXPLAIN_CHILD=
CONTENT_COPY_PATH_3S_QUIZ=
IMAGE_PROVIDER=codex
GEMINI_API_KEY=
GEMINI_IMAGE_MODEL=gemini-3.1-flash-image
```

이미지 생성 결과를 템플릿별 폴더에도 복사하려면 템플릿에 맞는 환경변수에 시스템 절대경로를 입력합니다. 값이 비어 있으면 해당 템플릿 결과는 복사하지 않습니다.

```env
CONTENT_COPY_PATH_EXPLAIN_CHILD=C:\absolute\copy\explain_child
CONTENT_COPY_PATH_3S_QUIZ=C:\absolute\copy\3s_quiz
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

뉴스 기반 템플릿은 `n8n_publish_content.comment`의 뉴스 URL을 기준으로 `mq_news_quiz.mq_source_url`이 일치하는 row를 조회한 뒤, 기사 제목/뉴스 키워드/키워드 설명/선별 이유를 반영해 생성합니다.

```powershell
python main.py --template news_explain_child --date 2026-06-26
python main.py --template news_3s_quiz --date 2026-06-26
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

# 뉴스 기반 템플릿으로 스크립트와 이미지 생성
python main.py --mode all --template news_explain_child --date 2026-06-26
python main.py --mode all --template news_3s_quiz --date 2026-06-26
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

현재 지원하는 템플릿은 네 가지입니다.

- `explain_child`
  - `prompt/SCRIPT_EXPLAN_CHILD.md`
  - `prompt/IMAGE_EXPLAIN_CHILD.md`
- `3s_quiz`
  - `prompt/SCRIPT_3S_QUIZ.md`
  - `prompt/IMAGE_3S_QUIZ.md`
- `news_explain_child`
  - `prompt/SCRIPT_NEWS_EXPLAIN_CHILD.md`
  - `prompt/IMAGE_NEWS_EXPLAIN_CHILD.md`
- `news_3s_quiz`
  - `prompt/SCRIPT_NEWS_3S_QUIZ.md`
  - `prompt/IMAGE_NEWS_3S_QUIZ.md`

`news_explain_child`는 기존 `자녀에게설명하기` 카테고리 row를 조회하고, `news_3s_quiz`는 기존 `3초퀴즈` 카테고리 row를 조회합니다. 두 템플릿 모두 기존 템플릿과 같은 생성 흐름을 사용하므로 `--keyword`로 지정한 row가 없으면 신규 row를 만들고, 생성된 스크립트와 이미지 파일명은 각각 `content`, `image_paths`에 저장합니다.

## DB 동작

코드는 `n8n_publish_content` 테이블의 다음 컬럼을 사용합니다.

- `idx`
- `category`
- `keyword`
- `content`
- `image_paths`
- `comment`
- `target_date`
- `threads_status`
- `website_status`

`--keyword`가 없으면 `target_date` 기준 최신 keyword row를 조회합니다. `--keyword`가 있으면 `category`, `keyword`, `target_date`가 일치하는 row를 찾고, 없으면 새 row를 생성합니다.

스크립트 생성 후에는 `content` 컬럼을 업데이트합니다. 이미지 생성 후에는 생성된 파일명을 JSON 배열 문자열로 만들어 `image_paths` 컬럼에 저장합니다.

뉴스 기반 템플릿은 추가로 다음 흐름을 사용합니다.

1. `n8n_publish_content.comment`에서 뉴스 URL을 추출합니다.
2. 추출한 URL과 `mq_news_quiz.mq_source_url`이 일치하는 row를 조회합니다.
3. `mq_title`, `mq_keyword`, `mq_keyword_description`, `mq_selection_reason`을 프롬프트 컨텍스트로 전달합니다.
4. 생성한 스크립트는 `n8n_publish_content.content`에 저장하고, 생성한 이미지 파일명은 `image_paths`에 저장합니다.

뉴스 기반 템플릿은 `comment`에 뉴스 URL이 있어야 스크립트를 새로 생성할 수 있습니다. `--keyword`로 새 row가 삽입되었지만 `comment`가 비어 있으면 뉴스 컨텍스트를 찾을 수 없어 생성 단계에서 실패합니다.

## 이미지 생성 provider

이미지를 어떤 도구로 생성할지 `.env`의 `IMAGE_PROVIDER`로 고릅니다. 값이 비어 있으면 `codex`를 사용합니다. 스크립트 텍스트 생성은 항상 Codex CLI를 사용하며 이 설정과 무관합니다.

| 값 | 동작 |
|---|---|
| `codex` | `codex exec`의 내장 이미지 생성 도구를 사용합니다. 기본값입니다. |
| `agy` | Antigravity CLI(`agy -p`)로 생성합니다. |
| `gemini_api` | Gemini API를 직접 호출해 생성합니다. `GEMINI_API_KEY`가 필요합니다. |

`agy`를 쓰려면 먼저 `agy`를 설치하고, 터미널에서 `agy`를 한 번 실행해 Google 계정으로 로그인해 둡니다. 설치 직후 열려 있던 터미널은 PATH가 갱신되지 않을 수 있는데, PATH에 없으면 `%LOCALAPPDATA%\agy\bin\agy.exe`를 자동으로 찾습니다.

`agy` 사용 시 주의할 점입니다.

- `agy`는 이미지를 `~/.gemini/antigravity-cli/brain/<세션>/` 아래에 JPEG로 저장합니다. 실행 후 새로 생긴 이미지 중 가장 최근 파일을 출력 폴더로 복사하고, 기존과 같이 PNG로 최적화합니다. 이 세션 폴더는 자동으로 지워지지 않습니다.
- 이미지 생성 모델의 사용량 한도(쿼터)가 소진되면 이미지가 만들어지지 않고 실패합니다. 이때 한도 초과 메시지는 `agy`의 세션 로그에만 남을 수 있습니다.
- 프롬프트가 에이전트를 거치므로 스크립트 대사가 일부 바뀌어 그려질 수 있습니다.

`gemini_api` 사용 시 주의할 점입니다.

- 모델은 `GEMINI_IMAGE_MODEL`로 바꿀 수 있습니다. 비워 두면 `gemini-3.1-flash-image`를 사용합니다. 더 저렴한 `gemini-3.1-flash-lite-image`도 쓸 수 있지만 1K 해상도만 지원합니다.
- 템플릿별 가로세로 비율(`explain_child`, `news_explain_child`는 16:9, `3s_quiz`, `news_3s_quiz`는 4:5)을 API 파라미터로 전달합니다. 비율은 `codex_exec.py`의 `TEMPLATES`에서 바꿉니다.
- 호출마다 이미지 한 장 분량의 요금이 부과됩니다. 요청이 실패하면 HTTP 상태와 응답 일부가 오류 메시지에 포함됩니다.

provider 선택과 등록은 `image_providers.py` 한 파일에서 하고, 실제 생성 로직은 호출 주체별 파일로 나뉘어 있습니다.

| provider | 구현 파일 |
|---|---|
| `codex` | `codex_exec.py` (`generate_image_with_codex`) |
| `agy` | `agy_exec.py` (`generate_image_with_agy`) |
| `gemini_api` | `gemini_api_exec.py` (`generate_image_with_gemini_api`) |

이미지를 만드는 방식(CLI 실행, LLM 호출, API 호출 등)과 상관없이 모든 provider 함수는 같은 규약을 따릅니다. 새 provider를 추가하려면 호출 주체에 맞는 `*_exec.py` 파일에 `(prompt, output_dir, output_name, aspect_ratio=None)`을 받아 `output_dir / output_name` 경로에 이미지를 만들고 그 경로를 반환하는 함수를 작성한 뒤, `image_providers.py`의 `IMAGE_PROVIDERS`에 등록합니다. 실패하면 예외를 발생시킵니다. 비율을 지정할 수 없는 provider는 `aspect_ratio`를 무시합니다.

## 출력

기본 출력 경로는 `output/`입니다. 파일명은 현재 시각과 키워드를 기준으로 만들어집니다.

- 스크립트: `{timestamp}_{keyword}_script.txt`
- 이미지: `{timestamp}_{keyword}.png`

`CONTENT_COPY_PATH_EXPLAIN_CHILD` 또는 `CONTENT_COPY_PATH_3S_QUIZ` 환경변수가 설정되어 있으면 이미지 생성과 최적화가 끝난 뒤 현재 템플릿에 맞는 절대경로 폴더로 같은 파일명을 복사합니다. DB에는 기존처럼 생성된 이미지 파일명만 저장합니다.

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
