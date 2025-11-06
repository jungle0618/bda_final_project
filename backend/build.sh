#!/usr/bin/env bash
# exit on error
set -o errexit

# 步驟 1：(移除) FFmpeg 安裝步驟
# 我們不再需要 apt-get，因為 Render 已內建 FFmpeg

# 步驟 2：安裝 Python 依賴
echo "Installing Python dependencies..."
pip install -r requirements.txt

echo "Build script finished."