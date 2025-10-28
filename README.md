# Voice-to-Text Smart Note Agent

基於 MapReduce 架構的智慧語音轉文字與筆記生成系統，使用 Gemini API 實現自動化語音處理。

## 🚀 快速開始

```bash
# 1. 安裝依賴
pip install -r requirements.txt

# 2. 設定 API 金鑰
export GEMINI_API_KEY="你的API金鑰"

# 3. 放入音頻檔案
cp your_audio.mp3 audio/

# 4. 執行程式
python example_usage.py
```

## 📋 功能特色

- **並行處理**: 使用 MapReduce 架構並行處理音頻切片
- **智能轉錄**: Gemini 2.5 Flash API 高精度語音轉文字
- **文本清理**: 自動去除語助詞、口吃、重複詞語
- **結構化摘要**: 生成包含重點、待辦、決策的 Markdown 筆記
- **速率控制**: 自動控制 API 調用，避免超出免費方案限制

## 🏗️ 技術架構

### MapReduce 流程
```
音頻上傳 → 切片(5分鐘) → Map(並行處理) → Reduce(合併摘要)
```

### 核心模組
- **音頻處理**: pydub 切片處理
- **語音轉文字**: Gemini 2.5 Flash API
- **文本清理**: 自定義清理邏輯
- **摘要生成**: MapReduce 模式
- **速率控制**: 自定義 RateLimiter

## 📁 目錄結構

```
final_project/
├── audio/                    # 音頻檔案目錄
├── workspace/               # 工作目錄
│   └── {file_name}/
│       ├── slice_audio/     # 音頻切片
│       ├── transcript/      # 原始轉錄稿
│       ├── transcript_simplified/  # 清理後文本
│       └── summaries/       # 摘要檔案
├── test.py                  # 主程式
├── example_usage.py         # 互動式範例
└── requirements.txt         # 依賴套件
```

## 🔧 使用方法

### 方法一：互動式範例（推薦）
```bash
python example_usage.py
```

### 方法二：直接執行
```bash
# 修改 test.py 中的檔案名稱
file_name = 'your_audio.mp3'
python test.py
```

## ⚙️ 設定選項

### 音頻切片參數
```python
segment_length = 5 * 60 * 1000  # 5分鐘片段
overlap_length = 20 * 1000     # 20秒重疊
```

### 並行處理設定
```python
max_concurrent_processes = 4  # 最多4個進程
```

### 速率限制
```python
max_requests_per_minute = 1800  # 每分鐘請求數
```

## 📊 效能參考

| 音頻長度 | 切片數量 | 處理時間 | API 調用 |
|---------|---------|---------|---------|
| 10 分鐘  | 2 個     | 2-3 分鐘 | 6 次    |
| 30 分鐘  | 6 個     | 5-8 分鐘 | 18 次   |
| 60 分鐘  | 12 個    | 10-15 分鐘 | 36 次  |

## 🔍 故障排除

### 常見問題
1. **API 金鑰錯誤**: 檢查 `GEMINI_API_KEY, OPENAI_API_KEY` 環境變數
2. **音頻載入失敗**: 確認檔案在 `audio/` 目錄且格式正確
3. **速率限制**: 系統會自動等待，這是正常現象
4. **記憶體不足**: 減少並行進程數或處理較短音頻

### 測試功能
```bash
python test_rate_limit.py    # 測試速率限制
python test_mapreduce.py     # 測試 MapReduce
```

## 📝 輸出格式

### 摘要範例
```markdown
# 會議摘要

## 主要內容概述
本次會議討論了 AI 專案開發進度...

## 關鍵要點
1. 模型訓練將於 11 月底完成
2. 需要增加資料集規模
3. 團隊需要額外人力支援

## 重要決策
- 決定採用新的訓練架構
- 預算增加 20% 用於硬體升級
```

## 🛠️ 技術選型

- **語音轉文字**: Gemini 2.5 Flash API
- **並行處理**: multiprocessing.Pool
- **流程控制**: LangGraph
- **音頻處理**: pydub
- **速率控制**: 自定義 RateLimiter

## 📈 未來發展

- [ ] Web Dashboard 介面
- [ ] LINE/Discord Bot 整合
- [ ] 多語言支援
- [ ] 即時語音處理
- [ ] 個人化模板

## 📄 授權

MIT License

---

**注意**: 使用前請確保已設定正確的 API 金鑰，並遵守相關服務的使用條款。