#!/usr/bin/env python3
"""
Voice-to-Text Smart Note Agent 使用範例

這個腳本展示如何使用 MapReduce 架構處理音頻檔案
"""

import os
import sys
from test import app, AllState

def main():
    """主函數：示範如何使用系統"""
    
    print("🎵 Voice-to-Text Smart Note Agent 使用範例")
    print("=" * 50)
    
    # 檢查音頻檔案
    audio_dir = "audio"
    if not os.path.exists(audio_dir):
        print(f"❌ 錯誤：找不到 {audio_dir} 目錄")
        print("請先創建 audio 目錄並放入音頻檔案")
        return
    
    # 列出可用的音頻檔案
    audio_files = [f for f in os.listdir(audio_dir) if f.endswith(('.mp3', '.wav', '.m4a'))]
    
    if not audio_files:
        print(f"❌ 錯誤：在 {audio_dir} 目錄中找不到音頻檔案")
        print("支援格式：.mp3, .wav, .m4a")
        return
    
    print(f"📁 找到 {len(audio_files)} 個音頻檔案：")
    for i, file in enumerate(audio_files, 1):
        print(f"  {i}. {file}")
    
    # 讓使用者選擇檔案
    try:
        choice = input(f"\n請選擇要處理的檔案 (1-{len(audio_files)})：")
        file_index = int(choice) - 1
        
        if file_index < 0 or file_index >= len(audio_files):
            print("❌ 無效的選擇")
            return
        
        selected_file = audio_files[file_index]
        print(f"✅ 已選擇：{selected_file}")
        
    except (ValueError, KeyboardInterrupt):
        print("\n❌ 操作已取消")
        return
    
    # 設定初始狀態
    init_state: AllState = {
        "messages": [], 
        "file_name": selected_file,
        "slice_summaries": [],
        "final_summary": ""
    }
    
    # 檢查音頻檔案是否存在
    audio_path = os.path.join(audio_dir, selected_file)
    if not os.path.exists(audio_path):
        print(f"❌ 錯誤：找不到音頻檔案 {audio_path}")
        return
    
    print(f"\n🚀 開始處理音頻檔案：{selected_file}")
    print("⏳ 這可能需要幾分鐘時間，請耐心等待...")
    
    try:
        # 執行處理流程
        response = app.invoke(init_state)
        
        print("\n🎉 處理完成！")
        print(f"📂 結果已儲存至：{response['workspace_path']}")
        
        # 顯示結果摘要
        if 'final_summary' in response and response['final_summary']:
            print("\n📝 最終摘要預覽：")
            print("-" * 30)
            print(response['final_summary'][:200] + "..." if len(response['final_summary']) > 200 else response['final_summary'])
            print("-" * 30)
        
        # 顯示檔案結構
        workspace_path = response['workspace_path']
        print(f"\n📁 輸出檔案結構：")
        for root, dirs, files in os.walk(workspace_path):
            level = root.replace(workspace_path, '').count(os.sep)
            indent = ' ' * 2 * level
            print(f"{indent}{os.path.basename(root)}/")
            subindent = ' ' * 2 * (level + 1)
            for file in files[:5]:  # 只顯示前5個檔案
                print(f"{subindent}{file}")
            if len(files) > 5:
                print(f"{subindent}... 還有 {len(files) - 5} 個檔案")
        
    except Exception as e:
        print(f"❌ 處理過程中發生錯誤：{e}")
        print("請檢查 API 金鑰設定和網路連線")

if __name__ == "__main__":
    main()
