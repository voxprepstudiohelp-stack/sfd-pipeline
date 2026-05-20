# utils/gdrive_uploader.py — OAuth2 Refresh Token 버전
# GitHub: sfd-pipeline/utils/gdrive_uploader.py

import os, json
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

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

def upload_or_replace(service, local_path: str, folder_id: str):
    filename = os.path.basename(local_path)
    q = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    res = service.files().list(q=q, fields="files(id,name)").execute()
    existing = res.get("files", [])
    media = MediaFileUpload(local_path, mimetype="text/csv", resumable=False)
    if existing:
        service.files().update(
            fileId=existing[0]["id"],
            media_body=media
        ).execute()
        print(f"  ✅ 덮어쓰기: {filename}")
    else:
        meta = {"name": filename, "parents": [folder_id]}
        service.files().create(body=meta, media_body=media).execute()
        print(f"  ✅ 신규업로드: {filename}")

def upload_batch(file_folder_pairs: list):
    service = get_drive_service()
    for local_path, folder_id in file_folder_pairs:
        if os.path.exists(local_path) and folder_id:
            upload_or_replace(service, local_path, folder_id)
        else:
            print(f"  ⚠️ 건너뜀: {local_path}")
