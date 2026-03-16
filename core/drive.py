"""Google Drive 업로드 모듈."""

import logging
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = PROJECT_ROOT / "credentials.json"
TOKEN_FILE = PROJECT_ROOT / "token.json"


def _get_credentials() -> Credentials | None:
    """Google Drive OAuth 인증 정보를 가져온다."""
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json())
            return creds
        except Exception as e:
            logger.warning("토큰 갱신 실패: %s", e)

    if not CREDENTIALS_FILE.exists():
        logger.error(
            "credentials.json 없음. Google Cloud Console에서 다운로드 필요. "
            "README.md 참조."
        )
        return None

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CREDENTIALS_FILE), SCOPES
    )
    creds = flow.run_local_server(port=0)
    TOKEN_FILE.write_text(creds.to_json())
    logger.info("Google Drive 인증 완료, 토큰 저장됨")
    return creds


def upload_file(
    file_path: Path,
    folder_id: str | None = None,
) -> str | None:
    """파일을 Google Drive에 업로드한다.

    Returns:
        업로드된 파일의 Drive ID, 실패 시 None
    """
    creds = _get_credentials()
    if not creds:
        return None

    try:
        service = build("drive", "v3", credentials=creds)

        file_metadata: dict = {"name": file_path.name}
        if folder_id:
            file_metadata["parents"] = [folder_id]

        media = MediaFileUpload(
            str(file_path), mimetype="audio/mpeg", resumable=True
        )

        file = (
            service.files()
            .create(body=file_metadata, media_body=media, fields="id,webViewLink")
            .execute()
        )

        file_id = file.get("id")
        link = file.get("webViewLink", "")
        logger.info("Drive 업로드 완료: %s → %s", file_path.name, link)
        return file_id

    except Exception as e:
        logger.error("Drive 업로드 실패 (%s): %s", file_path.name, e)
        return None


def ensure_folder(folder_name: str, parent_id: str | None = None) -> str | None:
    """Drive에 폴더가 없으면 생성하고 ID를 반환한다."""
    creds = _get_credentials()
    if not creds:
        return None

    try:
        service = build("drive", "v3", credentials=creds)

        # 기존 폴더 검색
        query = (
            f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder'"
            f" and trashed=false"
        )
        if parent_id:
            query += f" and '{parent_id}' in parents"

        results = service.files().list(q=query, fields="files(id)").execute()
        files = results.get("files", [])

        if files:
            return files[0]["id"]

        # 새 폴더 생성
        metadata: dict = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            metadata["parents"] = [parent_id]

        folder = service.files().create(body=metadata, fields="id").execute()
        folder_id = folder.get("id")
        logger.info("Drive 폴더 생성: %s (id=%s)", folder_name, folder_id)
        return folder_id

    except Exception as e:
        logger.error("Drive 폴더 생성 실패: %s", e)
        return None
