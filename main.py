from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pathlib import Path
import yt_dlp
import json
import os
import logging
from urllib.parse import urlparse
from tenacity import retry, stop_after_attempt, wait_exponential

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# 确保所需目录存在
Path("downloads").mkdir(exist_ok=True)
Path("templates").mkdir(exist_ok=True)

# Setup templates and static files
try:
    templates = Jinja2Templates(directory="templates")
    app.mount("/downloads", StaticFiles(directory="downloads"), name="downloads")
except Exception as e:
    logger.error(f"启动错误: {str(e)}")
    raise

# Store download progress
download_progress = {}

def save_video_info(info):
    try:
        video_info = {
            'id': info['id'],
            'title': info['title'],
            'duration': info['duration'],
            'uploader': info['uploader'],
            'description': info.get('description', ''),
            'filepath': f"downloads/{info['id']}.mp4",
            'filesize': os.path.getsize(f"downloads/{info['id']}.mp4"),
            'thumbnail': info.get('thumbnail', '')
        }
        
        videos = []
        if os.path.exists('videos.json'):
            with open('videos.json', 'r', encoding='utf-8') as f:
                videos = json.load(f)
        
        videos.append(video_info)
        
        with open('videos.json', 'w', encoding='utf-8') as f:
            json.dump(videos, f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"保存视频信息错误: {str(e)}")
        raise

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def download_video(url: str, video_id: str):
    try:
        ydl_opts = {
            'format': 'best',
            'outtmpl': f'downloads/{video_id}.mp4',
            'progress_hooks': [lambda d: update_progress(video_id, d)],
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            save_video_info(info)
        
        download_progress[video_id] = {'status': 'completed'}
    except Exception as e:
        download_progress[video_id] = {
            'status': 'error',
            'message': str(e)
        }
        raise

def update_progress(video_id: str, d: dict):
    if d['status'] == 'downloading':
        download_progress[video_id] = {
            'status': 'downloading',
            'percentage': d['_percent_str'],
            'speed': d['_speed_str'],
            'eta': d['_eta_str']
        }

def is_valid_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.netloc in ['www.youtube.com', 'youtube.com', 'youtu.be']
    except:
        return False

def format_duration(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    
    if hours > 0:
        return f"{hours}小时{minutes}分{seconds}秒"
    elif minutes > 0:
        return f"{minutes}分{seconds}秒"
    else:
        return f"{seconds}秒"

def format_filesize(size: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"

@app.get("/")
async def home(request: Request):
    try:
        videos = []
        if os.path.exists('videos.json'):
            with open('videos.json', 'r', encoding='utf-8') as f:
                videos = json.load(f)
        return templates.TemplateResponse(
            "index.html", 
            {
                "request": request, 
                "videos": videos,
                "format_duration": format_duration,
                "format_filesize": format_filesize
            }
        )
    except Exception as e:
        logger.error(f"首页加载错误: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"message": f"服务器错误: {str(e)}"}
        )

@app.post("/download")
async def download(url: str, background_tasks: BackgroundTasks):
    if not is_valid_youtube_url(url):
        return JSONResponse({
            "status": "error", 
            "message": "请输入有效的YouTube视频链接"
        })
    try:
        with yt_dlp.YoutubeDL() as ydl:
            info = ydl.extract_info(url, download=False)
            video_id = info['id']
            
        download_progress[video_id] = {'status': 'starting'}
        background_tasks.add_task(download_video, url, video_id)
        
        return JSONResponse({
            "status": "success",
            "video_id": video_id
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": str(e)
        })

@app.get("/progress/{video_id}")
async def get_progress(video_id: str):
    return download_progress.get(video_id, {'status': 'not_found'}) 

@app.delete("/video/{video_id}")
async def delete_video(video_id: str):
    try:
        # 删除视频文件
        video_path = f"downloads/{video_id}.mp4"
        if os.path.exists(video_path):
            os.remove(video_path)
            
        # 从videos.json中删除��录
        if os.path.exists('videos.json'):
            with open('videos.json', 'r') as f:
                videos = json.load(f)
            
            videos = [v for v in videos if v['id'] != video_id]
            
            with open('videos.json', 'w') as f:
                json.dump(videos, f)
                
        return {"status": "success"}
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": str(e)
        })