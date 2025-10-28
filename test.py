import os
import time
import math  # 引入 math 模組
from typing import Annotated, List, Dict, Any
from typing_extensions import TypedDict
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
# from langchain_google_genai import ChatGoogleGenerativeAI # 這個變數未使用，可以刪除
from google import genai
from pydub import AudioSegment
from multiprocessing import Pool, cpu_count
from functools import partial
import threading
from collections import deque

# --- 安全性修正：從環境變數讀取 API 金鑰 ---
# 執行前，請在你的終端機設定環境變數：
# export GOOGLE_API_KEY="你的AIzaSy...金鑰"
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY 環境變數未設定。")

# ----------------------------------------

pwd = os.getcwd()

class AllState(TypedDict):
    messages: Annotated[list, add_messages]
    raw_audio_path: str
    workspace_path: str
    file_name: str
    # --- 新增 ---
    slice_summaries: List[str] # 用於 Map 階段的輸出
    final_summary: str         # 用於 Reduce 階段的輸出

# llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", api_key=api_key) # 未使用，已註解

class RateLimiter:
    """速率限制器，確保不超過 Gemini API 的限制"""
    
    def __init__(self, max_requests_per_minute=1800):  # 免費方案：保守設定，低於 2000 RPM 限制
        self.max_requests_per_minute = max_requests_per_minute
        self.requests = deque()
        self.lock = threading.Lock()
        print(f"🚦 速率限制器初始化：每分鐘最多 {max_requests_per_minute} 個請求")
    
    def wait_if_needed(self):
        """如果需要，等待直到可以發送下一個請求"""
        with self.lock:
            now = time.time()
            # 移除一分鐘前的請求記錄
            while self.requests and now - self.requests[0] > 60:
                self.requests.popleft()
            
            # 如果達到限制，等待
            if len(self.requests) >= self.max_requests_per_minute:
                sleep_time = 60 - (now - self.requests[0])
                if sleep_time > 0:
                    print(f"⏳ 速率限制：等待 {sleep_time:.1f} 秒...")
                    time.sleep(sleep_time)
                    # 重新計算
                    now = time.time()
                    while self.requests and now - self.requests[0] > 60:
                        self.requests.popleft()
            
            # 記錄這個請求
            self.requests.append(now)

# 全域速率限制器
rate_limiter = RateLimiter()

def create_dir(state: AllState):  # 建立工作目錄
    file_name = state["file_name"]
    # 使用 os.path.join 確保路徑相容性
    workspace_path = os.path.join(pwd, "workspace", file_name)
    raw_audio_path = os.path.join(pwd, "audio", file_name)

    os.makedirs(workspace_path, exist_ok=True)
    state["workspace_path"] = workspace_path
    state["raw_audio_path"] = raw_audio_path

    os.makedirs(os.path.join(workspace_path, "slice_audio"), exist_ok=True)
    os.makedirs(os.path.join(workspace_path, "transcript"), exist_ok=True)
    os.makedirs(os.path.join(workspace_path, "transcript_simplified"), exist_ok=True)
    print(f"📁 目錄已建立: {workspace_path}")
    return state

def slice_audio(state: AllState):  # 把mp3切片
    segment_length = 5 * 60 * 1000  # 5 minutes in milliseconds
    overlap_length = 20 * 1000      # 20 seconds in milliseconds

    file_path = state["raw_audio_path"]
    workspace_path = state["workspace_path"]
    slice_dir = os.path.join(workspace_path, "slice_audio")

    print(f"🔪 正在讀取音檔: {file_path}")
    # 修正：使用 from_file 更有彈性
    try:
        audio = AudioSegment.from_file(file_path)
    except Exception as e:
        print(f"Error loading audio file {file_path}: {e}")
        # 如果音檔載入失敗，我們應該停止流程，可以拋出異常
        raise
        
    if len(audio) == 0:
        print("⚠️ 警告：音檔長度為 0，將不進行切片。")
        return state

    

    # 修正：使用 math.ceil 確保計算正確
    num_segments = math.ceil(len(audio) / segment_length)
    print(f"🔪 音檔總長度: {len(audio) / 1000:.2f} 秒，將切分為 {num_segments} 個片段。")

    for i in range(num_segments):
        start = i * segment_length
        end = min(start + segment_length + overlap_length, len(audio))
        segment = audio[start:end]
        output_path = os.path.join(slice_dir, f"part_{i}.mp3")
        segment.export(output_path, format="mp3")
        
    print(f"🔪 切片完成，已儲存至 {slice_dir}")
    return state

def process_single_slice(args: tuple) -> Dict[str, Any]:
    """
    Map function: 處理單個音頻切片
    輸入: (slice_file_path, workspace_path, api_key)
    輸出: {slice_name, transcript, cleaned_text, summary}
    """
    slice_file_path, workspace_path, api_key = args
    
    # 初始化客戶端
    audio_client = genai.Client(api_key=api_key)
    
    slice_name = os.path.basename(slice_file_path)
    print(f"  > 正在處理 {slice_name}...")
    
    result = {
        'slice_name': slice_name,
        'transcript': '',
        'cleaned_text': '',
        'summary': '',
        'error': None
    }
    
    try:
        # 1. 上傳並轉錄
        myfile = audio_client.files.upload(file=slice_file_path)
        
        # 等待上傳完成
        max_retries = 60
        for _ in range(max_retries):
            myfile = audio_client.files.get(name=myfile.name)
            if myfile.state == "ACTIVE":
                break
            time.sleep(1)
        
        if myfile.state != "ACTIVE":
            result['error'] = f"檔案上傳失敗，狀態: {myfile.state}"
            return result
        
        # 轉錄 - 添加速率限制
        rate_limiter.wait_if_needed()
        prompt = 'Generate a transcript of the speech.'
        response = audio_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[prompt, myfile]
        )
        result['transcript'] = response.text
        
        # 2. 清理文本
        if result['transcript'].strip():
            # 添加速率限制
            rate_limiter.wait_if_needed()
            clean_prompt = f"""
            請你扮演一個逐字稿編輯。
            任務：清理以下的語音轉錄稿。
            規則：
            1. 刪除所有贅字和填充詞 (例如 "嗯", "啊", "那個", "就是", "你知道嗎", "like", "um", "ah" 等)。
            2. 刪除口吃或重複的詞語。
            3. 修正明顯的拼寫或文法錯誤。
            4. **不要總結**。保留原始的語句結構和所有核心資訊。
            5. **僅輸出**清理後的文字。

            原始轉錄稿：
            ---
            {result['transcript']}
            ---
            清理後的轉錄稿：
            """
            
            clean_response = audio_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[clean_prompt]
            )
            result['cleaned_text'] = clean_response.text
        else:
            result['cleaned_text'] = ""
        
        # 3. 生成摘要
        if result['cleaned_text'].strip():
            # 添加速率限制
            rate_limiter.wait_if_needed()
            summary_prompt = f"""
            請為以下文本生成一個簡潔的摘要，包含：
            1. 主要內容概述
            2. 關鍵要點（3-5個）
            3. 重要決策或結論（如果有的話）

            文本內容：
            ---
            {result['cleaned_text']}
            ---

            摘要：
            """
            
            summary_response = audio_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[summary_prompt]
            )
            result['summary'] = summary_response.text
        else:
            result['summary'] = ""
        
        print(f"  > ✅ {slice_name} 處理完成")
        
    except Exception as e:
        result['error'] = str(e)
        print(f"  > ❌ 處理 {slice_name} 時發生錯誤: {e}")
    
    return result

def map_reduce_process_slices(state: AllState):
    """
    MapReduce 主函數：並行處理所有音頻切片
    """
    workspace_path = state['workspace_path']
    slice_audio_dir = os.path.join(workspace_path, "slice_audio")
    transcript_dir = os.path.join(workspace_path, "transcript")
    simplified_dir = os.path.join(workspace_path, "transcript_simplified")
    summary_dir = os.path.join(workspace_path, "summaries")
    
    # 建立必要的目錄
    os.makedirs(transcript_dir, exist_ok=True)
    os.makedirs(simplified_dir, exist_ok=True)
    os.makedirs(summary_dir, exist_ok=True)
    
    # 取得所有切片檔案
    try:
        slice_files = [f for f in os.listdir(slice_audio_dir) if f.endswith('.mp3')]
        slice_files.sort(key=lambda x: int(x.split('_')[1].split('.')[0]))
    except Exception as e:
        print(f"Error reading slice files: {e}")
        return state
    
    if not slice_files:
        print("⚠️ 未找到任何音頻切片")
        return state
    
    print(f"🔄 開始 MapReduce 處理 {len(slice_files)} 個切片...")
    
    # 準備 Map 函數的參數
    slice_paths = [os.path.join(slice_audio_dir, f) for f in slice_files]
    map_args = [(path, workspace_path, api_key) for path in slice_paths]
    
    # 使用多進程並行處理 (Map 階段) - 免費方案保守設定
    # 每個進程會進行 3 次 API 調用（轉錄、清理、摘要），所以限制進程數
    max_concurrent_processes = min(4, cpu_count(), len(slice_files))  # 最多 4 個進程
    num_processes = max_concurrent_processes
    print(f"🚀 免費方案：使用 {num_processes} 個進程並行處理（最多 4 個）...")
    print(f"📊 預估每分鐘 API 調用：{num_processes * 3} 次（轉錄+清理+摘要）")
    
    with Pool(processes=num_processes) as pool:
        print(f"⏳ 開始處理 {len(slice_files)} 個音頻切片...")
        results = pool.map(process_single_slice, map_args)
    
    # 儲存結果並收集摘要 (Reduce 階段)
    all_summaries = []
    
    for result in results:
        slice_name = result['slice_name']
        base_name = slice_name.replace('.mp3', '')
        
        # 儲存轉錄稿
        if result['transcript']:
            transcript_path = os.path.join(transcript_dir, f"{base_name}.txt")
            with open(transcript_path, 'w', encoding='utf-8') as f:
                f.write(result['transcript'])
        
        # 儲存清理後的文本
        if result['cleaned_text']:
            simplified_path = os.path.join(simplified_dir, f"{base_name}.txt")
            with open(simplified_path, 'w', encoding='utf-8') as f:
                f.write(result['cleaned_text'])
        
        # 儲存單個摘要
        if result['summary']:
            summary_path = os.path.join(summary_dir, f"{base_name}_summary.txt")
            with open(summary_path, 'w', encoding='utf-8') as f:
                f.write(result['summary'])
            all_summaries.append(result['summary'])
        
        # 報告錯誤
        if result['error']:
            print(f"  > ❌ {slice_name}: {result['error']}")
    
    # 儲存所有摘要到 state 中供後續使用
    state['slice_summaries'] = all_summaries
    
    print(f"🎉 MapReduce 處理完成，共處理 {len(results)} 個切片")
    return state

def reduce_final_summary(state: AllState):
    """
    Reduce 函數：將所有切片摘要合併成最終摘要
    """
    if 'slice_summaries' not in state or not state['slice_summaries']:
        print("⚠️ 沒有找到切片摘要，跳過最終摘要生成")
        return state
    
    workspace_path = state['workspace_path']
    summary_dir = os.path.join(workspace_path, "summaries")
    
    print("🔄 開始生成最終摘要...")
    
    # 合併所有摘要
    combined_summaries = "\n\n".join(state['slice_summaries'])
    
    # 生成最終摘要
    final_summary_prompt = f"""
    請基於以下各個片段的摘要，生成一個完整的、結構化的最終摘要。
    
    要求：
    1. 提供整體內容的主旨概述
    2. 整理並合併所有關鍵要點（去除重複）
    3. 識別重要的決策、結論或行動項目
    4. 保持邏輯順序和連貫性
    5. 使用清晰的標題和結構
    
    各片段摘要：
    ---
    {combined_summaries}
    ---
    
    最終摘要：
    """
    
    try:
        # 添加速率限制
        rate_limiter.wait_if_needed()
        audio_client = genai.Client(api_key=api_key)
        response = audio_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[final_summary_prompt]
        )
        
        # 儲存最終摘要
        final_summary_path = os.path.join(summary_dir, "final_summary.txt")
        with open(final_summary_path, 'w', encoding='utf-8') as f:
            f.write(response.text)
        
        state['final_summary'] = response.text
        print("✅ 最終摘要生成完成")
        
    except Exception as e:
        print(f"❌ 生成最終摘要時發生錯誤: {e}")
        state['final_summary'] = "摘要生成失敗"
    
    return state

# Build the state graph
graph_builder = StateGraph(AllState)
graph_builder.add_node("create_dir", create_dir)
graph_builder.add_node("slice_audio", slice_audio)
graph_builder.add_node("map_reduce_process", map_reduce_process_slices)
graph_builder.add_node("reduce_final_summary", reduce_final_summary)

graph_builder.set_entry_point("create_dir")
graph_builder.add_edge("create_dir", "slice_audio")
graph_builder.add_edge("slice_audio", "map_reduce_process")
graph_builder.add_edge("map_reduce_process", "reduce_final_summary")
graph_builder.set_finish_point("reduce_final_summary")
app = graph_builder.compile()

# main execution
file_name = input("請輸入音檔名稱，例如：cnn.mp3: ")
init_state: AllState = {"messages": [], "file_name": file_name}

# 檢查初始音檔是否存在
initial_audio_path = os.path.join(pwd, "audio", file_name)
if not os.path.exists(initial_audio_path):
    print(f"❌ 錯誤: 找不到初始音檔 {initial_audio_path}")
    print("請確認 'audio' 資料夾存在，且 'cnn.mp3' 檔案在裡面。")
else:
    print(f"🚀 開始執行 LangGraph 流程 for {file_name}...")
    response = app.invoke(init_state)
    print("🏁 流程執行完畢。")
    print(f"📂 最終工作目錄: {response['workspace_path']}")