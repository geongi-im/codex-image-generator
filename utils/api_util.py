import requests
from typing import List, Optional, Union
import os
from PIL import Image
import io
from dotenv import load_dotenv
from utils.logger_util import LoggerUtil

load_dotenv()

class ApiError(Exception):
    """API 호출 관련 커스텀 예외"""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"API Error (Status: {status_code}): {message}")

class ApiUtil:
    def __init__(self):
        base_url = os.getenv("BASE_URL")
        if not base_url:
            raise EnvironmentError("환경 변수 'BASE_URL'가 설정되어 있지 않습니다.")

        base_url = base_url.rstrip("/")
        self.api_base_url = f"{base_url}/api"
        self.headers = {
            "Accept": "application/json"
        }
        self.max_file_size = 1 * 1024 * 1024  # 1MB
        self.max_width = 800  # 최대 너비
        self.logger = LoggerUtil().get_logger()

    def _compress_image(self, image_path: str):
        """이미지 압축"""
        try:
            with Image.open(image_path) as img:
                # 이미지 크기 조정
                if img.width > self.max_width:
                    ratio = self.max_width / img.width
                    new_height = int(img.height * ratio)
                    img = img.resize((self.max_width, new_height), Image.Resampling.LANCZOS)

                # 이미지 품질 조정
                buffer = io.BytesIO()
                format = img.format if img.format else 'PNG'

                if format == 'PNG':
                    img.save(buffer, format=format, optimize=True)
                else:
                    img.save(buffer, format=format, quality=85, optimize=True)

                compressed_image = buffer.getvalue()

                # 압축 후에도 크기가 큰 경우 추가 압축
                quality = 85
                while len(compressed_image) > self.max_file_size and quality > 30:
                    buffer = io.BytesIO()
                    img.save(buffer, format='JPEG', quality=quality, optimize=True)
                    compressed_image = buffer.getvalue()
                    quality -= 10

                self.logger.info(f"이미지 압축 완료: {image_path} (크기: {len(compressed_image)/1024:.1f}KB)")
                return compressed_image, format.lower()
        except Exception as e:
            self.logger.error(f"이미지 압축 실패: {image_path} - {str(e)}")
            raise

    def create_post(self, title: str, content: str, category: str, writer: str, image_paths: Optional[List[str]] = None, thumbnail_image_path: str = None):
        """게시글 생성 API 호출 (이미지/썸네일 유무와 관계없이 단일 흐름)"""
        url = f"{self.api_base_url}/board-research"

        try:
            data = {
                "title": title,
                "content": content,
                "category": category,
                "writer": writer
            }

            files = {}
            intended_images = bool(image_paths)

            # 본문 이미지 처리
            if image_paths:
                self.logger.info(f"게시글 생성 시작 (이미지 포함) - 제목: {title}")
                for i, image_path in enumerate(image_paths):
                    if os.path.exists(image_path):
                        try:
                            compressed_image, format = self._compress_image(image_path)
                            original_filename = os.path.basename(image_path)
                            files[f"image[{i}]"] = (original_filename, compressed_image, f"image/{format}")
                            self.logger.debug(f"이미지 {i+1} 추가: {original_filename}")
                        except Exception as e:
                            self.logger.error(f"이미지 처리 실패: {image_path} - {str(e)}")
                            continue
                    else:
                        self.logger.warning(f"이미지 경로가 존재하지 않습니다: {image_path}")

            # 썸네일 이미지 처리 (있으면 추가)
            if thumbnail_image_path and os.path.exists(thumbnail_image_path):
                try:
                    compressed_image, format = self._compress_image(thumbnail_image_path)
                    thumbnail_filename = os.path.basename(thumbnail_image_path)
                    files["thumbnail_image"] = (thumbnail_filename, compressed_image, f"image/{format}")
                    self.logger.debug(f"썸네일 이미지 추가: {thumbnail_filename}")
                except Exception as e:
                    self.logger.error(f"썸네일 이미지 처리 실패: {thumbnail_image_path} - {str(e)}")
            elif thumbnail_image_path:
                self.logger.warning(f"썸네일 경로가 존재하지 않습니다: {thumbnail_image_path}")

            # 사용자가 이미지 업로드를 의도했지만, 실사용할 파일이 하나도 없는 경우 에러
            if intended_images and not any(k.startswith("image[") for k in files.keys()) and "thumbnail_image" not in files:
                error_msg = "처리 가능한 이미지가 없습니다."
                self.logger.error(error_msg)
                raise ApiError(400, error_msg)

            response = None

            # multipart/form-data 또는 JSON 전송 결정
            if files:
                try:
                    headers = self.headers.copy()
                    form_data = {key: (None, str(value)) for key, value in data.items()}
                    form_data.update(files)
                    self.logger.debug(f"API 요청 데이터: {data}")
                    self.logger.debug(f"파일 데이터: {[f'{k}: {v[0]}' for k, v in files.items()]}")
                    self.logger.debug(f"최종 전송 데이터: {[(k, v[0] if isinstance(v, tuple) else v) for k, v in form_data.items()]}")

                    response = requests.post(
                        url,
                        headers=headers,
                        files=form_data,
                        timeout=30
                    )

                    self.logger.debug(f"응답 상태 코드: {response.status_code}")
                    self.logger.debug(f"응답 헤더: {dict(response.headers)}")
                finally:
                    files.clear()
            else:
                self.logger.info(f"게시글 생성 시작 (이미지 없음) - 제목: {title}")
                response = requests.post(url, headers=self.headers, json=data)

            # 응답 확인 및 한글 디코딩
            try:
                response.encoding = 'utf-8'
                response_data = response.json()

                self.logger.debug(f"API 응답: {response_data}")

                if not response_data.get('success', False):
                    error_msg = f"게시글 생성 실패\n제목: {title}\n카테고리: {category}\n응답: {response.text}"
                    self.logger.error(error_msg)
                    raise ApiError(response.status_code, error_msg)

                self.logger.info(f"게시글 생성 성공 - 제목: {title}")

                # 이미지 URL 확인 로직
                if intended_images and not response_data.get('data', {}).get('image_urls'):
                    self.logger.warning(f"이미지가 포함된 게시글이지만 image_urls가 비어있습니다. - 제목: {title}")
                elif intended_images:
                    self.logger.info(f"이미지 URL: {response_data.get('data', {}).get('image_urls')}")

                return response_data

            except ValueError:
                error_msg = f"JSON 응답 파싱 실패\n제목: {title}\n카테고리: {category}\n응답: {response.text}"
                self.logger.error(error_msg)
                raise ApiError(response.status_code, error_msg)

        except requests.RequestException as e:
            error_msg = f"API 요청 중 오류 발생\n제목: {title}\n카테고리: {category}\n오류: {str(e)}"
            self.logger.error(error_msg)
            raise ApiError(500, error_msg)

    # 회원 지정 발송 한 번에 보낼 수 있는 아이디 수 (서버 PushService::USER_IDS_MAX 와 같게)
    PUSH_USER_IDS_MAX = 500

    def send_push_to_users(self, user_ids: Union[str, List[str]], title: str, body: Optional[str] = None,
                           link: Optional[str] = None, dedupe_key: Optional[str] = None):
        """앱 푸시 회원 지정 발송 API 호출 (POST /api/push/send-users)

        지정한 회원 중 활성 회원 + 마케팅 정보 수신 동의 + 알림을 켠 기기가 있는 회원에게만 보낸다.
        .env 의 PUSH_API_KEY 를 X-Push-Key 헤더로 보낸다.

        Args:
            user_ids: 받을 회원 아이디(mq_member.mq_user_id). 한 명이면 문자열로 줘도 된다. 최대 500개
            title: 알림 제목 (필수, 100자 이내)
            body: 알림 본문 (500자 이내)
            link: 알림을 눌렀을 때 열 주소. 우리 사이트 경로(/board-research/123) 또는 우리 사이트 주소
            dedupe_key: 같은 키로는 한 번만 발송된다. 재시도해도 중복 발송되지 않게 날짜/대상 등을 넣어 만든다.
                        받는 회원이 다르면 키도 달라야 한다. 예) "topsector:2026-11-11:hong123"

        Returns:
            서버 응답 dict. data.result 로 결과를 구분한다.
              accepted  (202) 발송 시작. 기기별 결과는 서버 mq_push_logs 의 data.log_idx 행에 남는다.
              no_target (200) 받을 수 있는 회원이 없어 보내지 않음
              duplicate (409) 같은 dedupe_key 로 이미 보냄. 재시도 상황이므로 에러로 보지 않는다.
            data.skipped_user_ids 에는 지정했지만 받지 못하는 아이디가 들어 있다.
            (없는 아이디, 탈퇴/정지, 마케팅 미동의, 알림을 켠 기기 없음)

        Raises:
            ApiError: 키 미설정, 대상/제목 누락, 인증 실패(401), 입력값 오류(422),
                      요청 과다(429, 분당 60회), 서버 FCM 미설정(503), 네트워크 오류 등
        """
        url = f"{self.api_base_url}/push/send-users"

        push_api_key = os.getenv("PUSH_API_KEY")
        if not push_api_key:
            error_msg = "환경 변수 'PUSH_API_KEY'가 설정되어 있지 않습니다."
            self.logger.error(error_msg)
            raise ApiError(400, error_msg)

        if isinstance(user_ids, str):
            user_ids = [user_ids]
        user_ids = [u.strip() for u in (user_ids or []) if u and u.strip()]
        if not user_ids:
            error_msg = "푸시를 받을 회원 아이디가 없습니다."
            self.logger.error(error_msg)
            raise ApiError(400, error_msg)
        if len(user_ids) > self.PUSH_USER_IDS_MAX:
            error_msg = f"한 번에 보낼 수 있는 회원은 {self.PUSH_USER_IDS_MAX}명까지입니다. (요청: {len(user_ids)}명)"
            self.logger.error(error_msg)
            raise ApiError(400, error_msg)

        if not title or not title.strip():
            error_msg = "푸시 제목이 비어 있습니다."
            self.logger.error(error_msg)
            raise ApiError(400, error_msg)

        data = {"user_ids": user_ids, "title": title}
        if body is not None:
            data["body"] = body
        if link is not None:
            data["link"] = link
        if dedupe_key is not None:
            data["dedupe_key"] = dedupe_key

        headers = self.headers.copy()
        headers["X-Push-Key"] = push_api_key

        self.logger.info(f"푸시 발송 요청 - 대상: {len(user_ids)}명, 제목: {title}, dedupe_key: {dedupe_key}")

        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
        except requests.RequestException as e:
            error_msg = f"푸시 API 요청 중 오류 발생\n제목: {title}\n오류: {str(e)}"
            self.logger.error(error_msg)
            raise ApiError(500, error_msg)

        response.encoding = 'utf-8'
        try:
            response_data = response.json()
        except ValueError:
            error_msg = f"푸시 API JSON 응답 파싱 실패\n제목: {title}\n상태 코드: {response.status_code}\n응답: {response.text[:500]}"
            self.logger.error(error_msg)
            raise ApiError(response.status_code, error_msg)

        data_part = response_data.get('data') or {}
        result = data_part.get('result')

        if response.status_code == 409 and result == 'duplicate':
            self.logger.info(f"이미 발송된 푸시라 건너뜀 - dedupe_key: {dedupe_key}")
            return response_data

        if not response_data.get('success', False):
            error_msg = f"푸시 발송 실패\n제목: {title}\n상태 코드: {response.status_code}\n응답: {response.text[:500]}"
            self.logger.error(error_msg)
            raise ApiError(response.status_code, error_msg)

        self.logger.info(
            f"푸시 발송 {result} - 제목: {title}, 대상 기기: {data_part.get('target_count')}, log_idx: {data_part.get('log_idx')}"
        )
        skipped = data_part.get('skipped_user_ids') or []
        if skipped:
            self.logger.info(f"푸시를 받지 못하는 회원 {len(skipped)}명 (미동의/기기 없음 등): {skipped}")
        return response_data

if __name__ == "__main__":
    # API 테스트
    api = ApiUtil()

    # 테스트할 이미지 경로
    image_paths = [
        "img/opm_kospi_20241209.jpg",
        "img/opm_kosdaq_20241209.jpg"
    ]

    # 테스트 데이터
    test_data = {
        "title": "API 이미지 전송 테스트",
        "content": "이미지 전송 테스트를 위한 게시글입니다.",
        "category": "거래량",
        "writer": "테스터"
    }

    try:
        # API 호출 테스트
        result = api.create_post(
            title=test_data["title"],
            content=test_data["content"],
            category=test_data["category"],
            writer=test_data["writer"],
            image_paths=image_paths
        )
        print("API 호출 결과:", result)

    except ApiError as e:
        print(f"API 에러 발생: {e}")
    except Exception as e:
        print(f"예상치 못한 에러 발생: {e}")
