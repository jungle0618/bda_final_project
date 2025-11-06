#!/usr/bin/env bash
# exit on error
set -o errexit

# 步驟 1：安裝系統依賴 (FFmpeg)
# -------------------------------
echo "Updating apt and installing ffmpeg..."
apt-get update
apt-get install -y ffmpeg

# 步驟 2：安裝 Python 依賴
# -------------------------------
echo "Installing Python dependencies..."
pip install -r requirements.txt

echo "Build script finished."