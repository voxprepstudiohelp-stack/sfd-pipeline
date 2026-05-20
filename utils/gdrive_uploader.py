# utils/gdrive_uploader.py
# GitHub: sfd-pipeline/utils/gdrive_uploader.py

import os, json
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/drive"]

def get_drive_service():
    creds_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    creds_info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)

def upload_or_replace(service, local_path: str, folder_id: str):
    filename = os.path.basename(local_path)

    # supportsAllDrives=True, includeItemsFromAllDrives=True 추가
    q = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    res = service.files().list(
        q=q,
        fields="files(id,name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    existing = res.get("files", [])

    media = MediaFileUpload(local_path, mimetype="text/csv", resumable=False)

    if existing:
        file_id = existing[0]["id"]
        service.files().update(
            fileId=file_id,
            media_body=media,
            supportsAllDrives=True          # 추가
        ).execute()
        print(f"  ✅ 덮어쓰기: {filename}")
    else:
        meta = {"name": filename, "parents": [folder_id]}
        service.files().create(
            body=meta,
            media_body=media,
            supportsAllDrives=True          # 추가
        ).execute()
        print(f"  ✅ 신규업로드: {filename}")

def upload_batch(file_folder_pairs: list):
    service = get_drive_service()
    for local_path, folder_id in file_folder_pairs:
        if os.path.exists(local_path) and folder_id:
            upload_or_replace(service, local_path, folder_id)
        else:
            print(f"  ⚠️ 건너뜀: {local_path}")
