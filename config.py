# config.py — 경로 및 Google Drive 폴더 ID 중앙 관리
# 파일위치(GitHub): sfd-pipeline/config.py

import os

# ── 로컬 임시 경로 (GitHub Actions runner: Ubuntu /tmp)
BASE        = "/tmp/sfd"
LATEST_DIR  = f"{BASE}/outputs/latest"
HISTORY_DIR = f"{BASE}/outputs/history"
INPUT_DIR   = f"{BASE}/inputs"

# ── Google Drive 폴더 ID (GitHub Secrets에서 주입)
GDRIVE_LATEST_FOLDER_ID  = os.environ.get("GDRIVE_LATEST_FOLDER_ID", "")
GDRIVE_HISTORY_FOLDER_ID = os.environ.get("GDRIVE_HISTORY_FOLDER_ID", "")
GDRIVE_INPUT_FOLDER_ID   = os.environ.get("GDRIVE_INPUT_FOLDER_ID", "")
