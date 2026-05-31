# utils/gdrive_uploader.py — OAuth2 Refresh Token 버전
import os
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# ======================================
# 경로 설정
# ======================================
_HERE          = Path(__file__).resolve().parent
_PIPELINE_ROOT = _HERE.parent
_LATEST        = _PIPELINE_ROOT / "outputs" / "latest"

# SFD_BASE_DIR 환경변수 우선 (GitHub Actions), 없으면 로컬 경로
_BASE = Path(os.environ.get("SFD_BASE_DIR", str(_PIPELINE_ROOT)))
_LATEST_DIR = _BASE / "outputs" / "latest"

# ======================================
# Drive 서비스 초기화
# ======================================
def get_drive_service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GDRIVE_REFRESH_TOKEN"],
        client_id=os.environ["GDRIVE_CLIENT_ID"],
        client_secret=os.environ["GDRIVE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    creds.refresh(Request())
    return build("drive", "v3", credentials=creds)


# ======================================
# 파일 업로드 (업데이트 or 신규 생성)
# ======================================
def get_mimetype(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {
        ".csv":  "text/csv",
        ".json": "application/json",
        ".txt":  "text/plain",
    }.get(ext, "application/octet-stream")


def upload_or_replace(service, local_path: str, folder_id: str):
    filename = os.path.basename(local_path)
    q = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    res = service.files().list(q=q, fields="files(id,name)").execute()
    existing = res.get("files", [])

    mimetype = get_mimetype(filename)
    media = MediaFileUpload(local_path, mimetype=mimetype, resumable=False)

    if existing:
        service.files().update(
            fileId=existing[0]["id"],
            media_body=media
        ).execute()
        print(f"  [업데이트] {filename}")
    else:
        meta = {"name": filename, "parents": [folder_id]}
        service.files().create(body=meta, media_body=media).execute()
        print(f"  [신규생성] {filename}")


def upload_batch(file_folder_pairs: list):
    service = get_drive_service()
    ok, skip = 0, 0
    for local_path, folder_id in file_folder_pairs:
        if os.path.exists(local_path) and folder_id:
            upload_or_replace(service, local_path, folder_id)
            ok += 1
        else:
            print(f"  [스킵] {local_path}")
            skip += 1
    print(f"[Upload] 완료: OK={ok} / SKIP={skip}")


# ======================================
# 업로드 대상 파일 목록
# ======================================
if __name__ == "__main__":
    LATEST_FOLDER_ID  = os.environ.get("GDRIVE_LATEST_FOLDER_ID", "")
    HISTORY_FOLDER_ID = os.environ.get("GDRIVE_HISTORY_FOLDER_ID", "")

    d = str(_LATEST_DIR)

    UPLOAD_TARGETS = [
        # CSV 출력물
        (f"{d}/sfd_prev_close_latest.csv",          LATEST_FOLDER_ID),
        (f"{d}/sfd_master_signal_latest.csv",        LATEST_FOLDER_ID),
        (f"{d}/sfd_technical_latest.csv",            LATEST_FOLDER_ID),
        (f"{d}/sfd_oscillation_latest.csv",          LATEST_FOLDER_ID),
        (f"{d}/sfd_news_latest.csv",                 LATEST_FOLDER_ID),
        (f"{d}/sfd_rerating_latest.csv",             LATEST_FOLDER_ID),
        (f"{d}/sfd_fundamental_latest.csv",          LATEST_FOLDER_ID),
        (f"{d}/sfd_sector_latest.csv",               LATEST_FOLDER_ID),
        (f"{d}/sfd_investor_flow_latest.csv",        LATEST_FOLDER_ID),
        (f"{d}/sfd_backtest_latest.csv",             LATEST_FOLDER_ID),
        (f"{d}/sfd_final_latest.csv",                LATEST_FOLDER_ID),
        (f"{d}/sfd_event_calendar.csv",              LATEST_FOLDER_ID),
        # JSON 출력물
        (f"{d}/sfd_event_summary.json",              LATEST_FOLDER_ID),
        (f"{d}/sfd_no_trade_tickers.json",           LATEST_FOLDER_ID),  # BM-5 신규
        (f"{d}/guardian_alerts.json",                LATEST_FOLDER_ID),
        (f"{d}/portfolio_status.json",               LATEST_FOLDER_ID),
    ]

    print(f"[Upload] SFD Drive 업로드 시작 | 대상: {len(UPLOAD_TARGETS)}건")
    upload_batch(UPLOAD_TARGETS)
