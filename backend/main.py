import os
import time
import math
import re
from typing import Annotated, List, Dict, Any, Optional
from typing_extensions import TypedDict
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
import google.generativeai as genai 

from google.api_core import exceptions as google_exceptions
from pydub import AudioSegment
from multiprocessing import Pool, cpu_count
from collections import deque
import threading
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
import shutil
# 導入 pytube
try:
    from pytubefix import YouTube
    from pytubefix.cli import on_progress
except ImportError:
    print("⚠️ 請安裝 pytubefix: pip install pytubefix")
    raise

# FastAPI app 初始化
fastapi_app = FastAPI(title="Audio Processing API")

# 添加 CORS 中間件
frontend_url = "https://bda-final-project-1.onrender.com"

# 允許的來源列表 (我們也加入本地開發常用的網址)
origins = [
    frontend_url,
    "http://localhost",
    "http://localhost:8080",
    "http://localhost:5173",  # 如果您本地使用 Vite
    "http://127.0.0.1:5500" # 如果您本地使用 VSCode Live Server
]

# 正確的設定
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,     # ⚠️ 這裡就是修改的地方
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
api_key = os.environ.get("GEMINI_API_KEY")
pwd = os.getcwd()

class AllState(TypedDict):
    messages: Annotated[list, add_messages]
    raw_audio_path: str
    workspace_path: str
    file_name: str
    slice_summaries: List[str]
    final_summary: str

class YouTubeRequest(BaseModel):
    """YouTube 網址請求模型"""
    url: str

class RateLimiter:
    """速率限制器，確保不超過 Gemini API 的限制"""
    
    def __init__(self, max_requests_per_minute=10):
        self.max_requests_per_minute = max_requests_per_minute
        self.requests = deque()
        self.lock = threading.Lock()
        print(f"🚦 速率限制器初始化：每分鐘最多 {max_requests_per_minute} 個請求")
    
    def wait_if_needed(self):
        """如果需要，等待直到可以發送下一個請求"""
        with self.lock:
            now = time.time()
            while self.requests and now - self.requests[0] > 60:
                self.requests.popleft()
            
            if len(self.requests) >= self.max_requests_per_minute:
                sleep_time = 60 - (now - self.requests[0]) + 1
                if sleep_time > 0:
                    print(f"⏳ 速率限制：等待 {sleep_time:.1f} 秒...")
                    time.sleep(sleep_time)
                    now = time.time()
                    while self.requests and now - self.requests[0] > 60:
                        self.requests.popleft()
            
            self.requests.append(now)

# 全域速率限制器
rate_limiter = RateLimiter()

def parse_retry_delay(error_dict: dict) -> float:
    """從錯誤響應中解析 retryDelay"""
    try:
        details = error_dict.get('error', {}).get('details', [])
        for detail in details:
            if detail.get('@type') == 'type.googleapis.com/google.rpc.RetryInfo':
                retry_delay = detail.get('retryDelay', '60s')
                if isinstance(retry_delay, str) and retry_delay.endswith('s'):
                    return float(retry_delay[:-1])
        return 60.0
    except Exception as e:
        print(f"⚠️ 解析 retryDelay 失敗: {e}，使用預設值 60 秒")
        return 60.0

def api_call_with_retry(func, *args, max_retries=5, **kwargs):
    """帶重試邏輯的 API 調用包裝器"""
    retry_count = 0
    
    while retry_count <= max_retries:
        try:
            rate_limiter.wait_if_needed()
            return func(*args, **kwargs)
            
        except Exception as e:
            error_str = str(e)
            
            if '429' in error_str or 'RESOURCE_EXHAUSTED' in error_str or 'quota' in error_str.lower():
                retry_count += 1
                
                if retry_count > max_retries:
                    print(f"❌ 已達到最大重試次數 ({max_retries})，放棄請求")
                    raise
                
                retry_delay = 60.0
                
                if hasattr(e, 'details') and isinstance(e.details, str):
                    try:
                        import json
                        error_dict = json.loads(e.details)
                        retry_delay = parse_retry_delay(error_dict)
                    except:
                        pass
                
                if retry_delay == 60.0 and 'retry in' in error_str.lower():
                    try:
                        match = re.search(r'retry in (\d+(?:\.\d+)?)s', error_str, re.IGNORECASE)
                        if match:
                            retry_delay = float(match.group(1))
                    except:
                        pass
                
                print(f"⚠️ 遇到配額限制錯誤 (重試 {retry_count}/{max_retries})")
                print(f"⏳ 等待 {retry_delay:.1f} 秒後重試...")
                time.sleep(retry_delay + 1)
                
            else:
                print(f"❌ 遇到非配額錯誤: {error_str}")
                raise
    
    raise Exception(f"API 調用失敗，已重試 {max_retries} 次")

def sanitize_filename(filename: str) -> str:
    """清理檔名，移除不合法字元"""
    # 移除或替換不合法字元
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # 限制長度
    if len(filename) > 200:
        filename = filename[:200]
    return filename

def download_youtube_audio(youtube_url: str) -> tuple[str, str]:
    """
    從 YouTube 下載純音訊檔案
    
    返回: (file_path, file_name)
    """
    try:
        print(f"📺 開始下載 YouTube 影片: {youtube_url}")
        
        # 建立 YouTube 物件
        yt = YouTube(youtube_url, on_progress_callback=on_progress)
        
        # 取得影片資訊
        video_title = sanitize_filename(yt.title)
        print(f"📹 影片標題: {yt.title}")
        print(f"⏱️ 影片長度: {yt.length} 秒")
        
        # 確保 audio 目錄存在
        audio_dir = os.path.join(pwd, "audio")
        os.makedirs(audio_dir, exist_ok=True)
        
        # 取得純音訊串流（最高品質）
        audio_stream = yt.streams.filter(only_audio=True).order_by('abr').desc().first()
        
        if not audio_stream:
            raise Exception("無法找到音訊串流")
        
        print(f"🎵 音訊品質: {audio_stream.abr}")
        
        # 下載音訊
        print(f"⬇️ 開始下載音訊...")
        downloaded_file = audio_stream.download(
            output_path=audio_dir,
            filename_prefix="yt_"
        )
        
        # 重新命名為 .mp3 (如果不是的話)
        file_name = f"yt_{video_title}.mp3"
        final_path = os.path.join(audio_dir, file_name)
        
        # 如果下載的檔案不是 mp3，進行轉換
        if not downloaded_file.endswith('.mp3'):
            print(f"🔄 轉換音訊格式為 MP3...")
            audio = AudioSegment.from_file(downloaded_file)
            audio.export(final_path, format="mp3")
            # 刪除原始檔案
            os.remove(downloaded_file)
        else:
            # 如果已經是 mp3，只需重新命名
            if downloaded_file != final_path:
                shutil.move(downloaded_file, final_path)
        
        print(f"✅ YouTube 音訊下載完成: {file_name}")
        return final_path, file_name
        
    except Exception as e:
        print(f"❌ YouTube 下載失敗: {str(e)}")
        raise Exception(f"YouTube 下載失敗: {str(e)}")

def create_dir(state: AllState):
    file_name = state["file_name"]
    workspace_path = os.path.join(pwd, "workspace", file_name)
    raw_audio_path = os.path.join(pwd, "audio", file_name)

    os.makedirs(workspace_path, exist_ok=True)
    state["workspace_path"] = workspace_path
    state["raw_audio_path"] = raw_audio_path

    os.makedirs(os.path.join(workspace_path, "slice_audio"), exist_ok=True)
    os.makedirs(os.path.join(workspace_path, "transcript"), exist_ok=True)
    print(f"📁 目錄已建立: {workspace_path}")
    return state

def slice_audio(state: AllState):
    segment_length = 5 * 60 * 1000  # 5 minutes
    overlap_length = 20 * 1000      # 20 seconds

    file_path = state["raw_audio_path"]
    workspace_path = state["workspace_path"]
    slice_dir = os.path.join(workspace_path, "slice_audio")

    print(f"🔪 正在讀取音檔: {file_path}")
    try:
        audio = AudioSegment.from_file(file_path)
    except Exception as e:
        print(f"❌ 載入音檔失敗: {file_path}: {e}")
        raise
        
    if len(audio) == 0:
        print("⚠️ 警告：音檔長度為 0，將不進行切片。")
        return state

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
    """Map function: 處理單個音頻切片"""
    slice_file_path, workspace_path, api_key = args
    
    audio_client = genai.Client(api_key=api_key)
    
    slice_name = os.path.basename(slice_file_path)
    print(f"  > 正在處理 {slice_name}...")
    
    result = {
        'slice_name': slice_name,
        'transcript': '',
        'summary': '',
        'error': None
    }
    
    try:
        # 上傳檔案
        print(f"  > 📤 上傳 {slice_name}...")
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
        
        # 轉錄
        print(f"  > 🎤 轉錄 {slice_name}...")
        def transcribe():
            prompt = 'Generate a transcript of the speech.'
            return audio_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[prompt, myfile]
            )
        
        response = api_call_with_retry(transcribe)
        result['transcript'] = response.text
        
        # 生成摘要
        if result['transcript'].strip():
            print(f"  > 📝 生成摘要 {slice_name}...")
            def summarize():
                summary_prompt = f"""
                請為以下文本生成一個簡潔的摘要，包含：
                1. 主要內容概述
                2. 關鍵要點（3-5個）
                3. 重要決策或結論（如果有的話）

                文本內容：
                ---
                {result['transcript']}
                ---

                摘要：
                """
                
                return audio_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=[summary_prompt]
                )
            
            summary_response = api_call_with_retry(summarize)
            result['summary'] = summary_response.text
        else:
            result['summary'] = ""
        
        print(f"  > ✅ {slice_name} 處理完成")
        
    except Exception as e:
        result['error'] = str(e)
        print(f"  > ❌ 處理 {slice_name} 時發生錯誤: {e}")
    
    return result

def map_reduce_process_slices(state: AllState):
    """MapReduce 主函數：並行處理所有音頻切片"""
    workspace_path = state['workspace_path']
    slice_audio_dir = os.path.join(workspace_path, "slice_audio")
    transcript_dir = os.path.join(workspace_path, "transcript")
    summary_dir = os.path.join(workspace_path, "summaries")
    
    os.makedirs(transcript_dir, exist_ok=True)
    os.makedirs(summary_dir, exist_ok=True)
    
    try:
        slice_files = [f for f in os.listdir(slice_audio_dir) if f.endswith('.mp3')]
        slice_files.sort(key=lambda x: int(x.split('_')[1].split('.')[0]))
    except Exception as e:
        print(f"❌ 讀取切片檔案失敗: {e}")
        return state
    
    if not slice_files:
        print("⚠️ 未找到任何音頻切片")
        return state
    
    print(f"🔄 開始 MapReduce 處理 {len(slice_files)} 個切片...")
    
    slice_paths = [os.path.join(slice_audio_dir, f) for f in slice_files]
    map_args = [(path, workspace_path, api_key) for path in slice_paths]
    
    num_processes = min(2, cpu_count(), len(slice_files))
    print(f"🚀 使用 {num_processes} 個進程並行處理...")
    
    with Pool(processes=num_processes) as pool:
        results = pool.map(process_single_slice, map_args)
    
    all_summaries = []
    success_count = 0
    error_count = 0
    
    for result in results:
        slice_name = result['slice_name']
        base_name = slice_name.replace('.mp3', '')
        
        if result['transcript']:
            transcript_path = os.path.join(transcript_dir, f"{base_name}.txt")
            with open(transcript_path, 'w', encoding='utf-8') as f:
                f.write(result['transcript'])
        
        if result['summary']:
            summary_path = os.path.join(summary_dir, f"{base_name}_summary.txt")
            with open(summary_path, 'w', encoding='utf-8') as f:
                f.write(result['summary'])
            all_summaries.append(result['summary'])
            success_count += 1
        
        if result['error']:
            print(f"  > ❌ {slice_name}: {result['error']}")
            error_count += 1
    
    state['slice_summaries'] = all_summaries
    
    print(f"🎉 MapReduce 處理完成：成功 {success_count} 個，失敗 {error_count} 個")
    return state

def reduce_final_summary(state: AllState):
    """Reduce 函數：將所有切片摘要合併成最終摘要"""
    if 'slice_summaries' not in state or not state['slice_summaries']:
        print("⚠️ 沒有找到切片摘要，跳過最終摘要生成")
        state['final_summary'] = "無法生成摘要：沒有找到任何切片摘要"
        return state
    
    workspace_path = state['workspace_path']
    summary_dir = os.path.join(workspace_path, "summaries")
    
    print("🔄 開始生成最終摘要...")
    
    combined_summaries = "\n\n".join(state['slice_summaries'])
    
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
        audio_client = genai.Client(api_key=api_key)
        
        def generate_final_summary():
            return audio_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[final_summary_prompt]
            )
        
        response = api_call_with_retry(generate_final_summary)
        
        final_summary_path = os.path.join(summary_dir, "final_summary.txt")
        with open(final_summary_path, 'w', encoding='utf-8') as f:
            f.write(response.text)
        
        state['final_summary'] = response.text
        print("✅ 最終摘要生成完成")
        
    except Exception as e:
        error_msg = f"生成最終摘要時發生錯誤: {str(e)}"
        print(f"❌ {error_msg}")
        state['final_summary'] = f"摘要生成失敗：{error_msg}"
    
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

langgraph_app = graph_builder.compile()

def process_audio_file(file_path: str, file_name: str) -> dict:
    """處理音頻檔案的核心邏輯"""
    init_state: AllState = {
        "messages": [], 
        "file_name": file_name,
        "raw_audio_path": file_path,
        "workspace_path": "",
        "slice_summaries": [],
        "final_summary": ""
    }
    
    print(f"🚀 開始執行 LangGraph 流程 for {file_name}...")
    response = langgraph_app.invoke(init_state)
    print("🏁 流程執行完畢。")
    
    final_summary = response.get('final_summary', '')
    slice_count = len(response.get('slice_summaries', []))
    
    if not final_summary:
        final_summary = "處理完成，但未能生成摘要內容"
    
    return {
        "status": "success",
        "message": "音檔處理完成",
        "file_name": file_name,
        "workspace_path": response['workspace_path'],
        "final_summary": final_summary,
        "slice_count": slice_count
    }

@fastapi_app.post("/process_audio/")
async def process_audio(audio_file: UploadFile = File(...)):
    """處理上傳的音頻檔案"""
    try:
        os.makedirs(os.path.join(pwd, "audio"), exist_ok=True)
        
        file_name = audio_file.filename
        file_path = os.path.join(pwd, "audio", file_name)
        
        print(f"📥 接收檔案: {file_name}")
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(audio_file.file, buffer)
        
        result = process_audio_file(file_path, file_name)
        return JSONResponse(content=result)
        
    except Exception as e:
        error_msg = str(e)
        print(f"❌ 處理失敗: {error_msg}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"處理失敗: {error_msg}",
                "final_summary": ""
            }
        )

@fastapi_app.post("/process_youtube/")
async def process_youtube(request: YouTubeRequest):
    """處理 YouTube 影片網址，下載音訊並處理"""
    try:
        youtube_url = request.url
        print(f"📺 接收 YouTube 網址: {youtube_url}")
        
        # 下載 YouTube 音訊
        file_path, file_name = download_youtube_audio(youtube_url)
        
        # 使用相同的處理邏輯
        result = process_audio_file(file_path, file_name)
        result["source"] = "youtube"
        result["youtube_url"] = youtube_url
        
        return JSONResponse(content=result)
        
    except Exception as e:
        error_msg = str(e)
        print(f"❌ YouTube 處理失敗: {error_msg}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"YouTube 處理失敗: {error_msg}",
                "final_summary": ""
            }
        )

@fastapi_app.get("/")
async def root():
    """API 根路徑"""
    return {
        "message": "Audio Processing API",
        "version": "2.0",
        "endpoints": {
            "/process_audio/": "POST - 上傳音頻檔案進行處理",
            "/process_youtube/": "POST - 處理 YouTube 影片網址"
        }
    }

@fastapi_app.get("/health")
async def health_check():
    """健康檢查端點"""
    return {"status": "healthy"}

# 啟動伺服器的指令:
# uvicorn main:fastapi_app --reload