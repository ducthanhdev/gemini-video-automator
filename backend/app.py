import socket
import logging
import json
import uuid
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import asyncio
from contextlib import asynccontextmanager

from backend.config import UPLOAD_DIR, OUTPUT_DIR, PORT, STATIC_DIR, TEMPLATES_DIR, STORAGE_DIR
from backend.services.automation import AutomationManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

manager = AutomationManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(manager.initialize())
    logger.info("FastAPI Backend started. Browser initialization scheduled.")
    yield
    await manager.shutdown()
    logger.info("FastAPI Backend shutdown completed.")

app = FastAPI(title="VeoFlow AI - Batch Video Generator", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
(STORAGE_DIR / "previews").mkdir(parents=True, exist_ok=True)
app.mount("/storage/previews", StaticFiles(directory=str(STORAGE_DIR / "previews")), name="previews")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

def get_local_ip() -> str:
    """Quét và lấy IP cục bộ của máy tính trong mạng nội bộ Wi-Fi."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

class SettingsUpdate(BaseModel):
    api_key: str
    prompt_mode: str
    long_video_mode: str
    system_instruction: str = ""
    meta_prompt_template: str = ""
    voice_gender: str = "capcut_cogaighoatngon"
    enable_voiceover: bool = True
    auto_retry_failed: bool = True

class TaskCreate(BaseModel):
    images: List[str]
    user_description: str
    duration: int
    ratio: str = "9:16"
    voice_gender: Optional[str] = "capcut_cogaighoatngon"

class TaskUpdate(BaseModel):
    user_description: str
    duration: int
    ratio: str
    voice_gender: Optional[str] = None

class ParseUrlRequest(BaseModel):
    url: str

# REST Endpoints
@app.get("/", response_class=HTMLResponse)
async def read_index(request: Request):
    local_ip = get_local_ip()
    local_url = f"http://{local_ip}:{PORT}"
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "local_url": local_url}
    )

@app.post("/api/settings")
async def update_settings(settings: SettingsUpdate):
    manager.api_key = settings.api_key
    manager.prompt_mode = settings.prompt_mode
    manager.long_video_mode = settings.long_video_mode
    manager.system_instruction = settings.system_instruction
    manager.meta_prompt_template = settings.meta_prompt_template
    manager.voice_gender = settings.voice_gender
    manager.enable_voiceover = settings.enable_voiceover
    manager.auto_retry_failed = settings.auto_retry_failed
    manager._save_settings()
    logger.info("Cập nhật và lưu cấu hình cố định thành công.")
    return {"status": "success", "settings": {
        "api_key": manager.api_key,
        "prompt_mode": manager.prompt_mode,
        "long_video_mode": manager.long_video_mode,
        "system_instruction": manager.system_instruction,
        "meta_prompt_template": manager.meta_prompt_template,
        "voice_gender": manager.voice_gender,
        "enable_voiceover": manager.enable_voiceover,
        "auto_retry_failed": manager.auto_retry_failed
    }}

@app.get("/api/settings")
async def get_settings():
    return {
        "api_key": manager.api_key,
        "prompt_mode": manager.prompt_mode,
        "long_video_mode": manager.long_video_mode,
        "system_instruction": manager.system_instruction,
        "meta_prompt_template": manager.meta_prompt_template,
        "voice_gender": manager.voice_gender,
        "enable_voiceover": manager.enable_voiceover,
        "auto_retry_failed": manager.auto_retry_failed
    }

@app.get("/api/voices")
async def get_available_voices():
    return [
        {"id": "capcut_cogaighoatngon", "name": "Cô Gái Hoạt Ngôn (TikTok Bán Hàng Viral - Khuyên dùng)", "provider": "capcut", "gender": "female", "preview_url": "/static/previews/capcut_cogaighoatngon.mp3"},
        {"id": "capcut_nhongotngao", "name": "Nhỏ Ngọt Ngào (Mỹ phẩm, Decor, Thời trang)", "provider": "capcut", "gender": "female", "preview_url": "/static/previews/capcut_nhongotngao.mp3"},
        {"id": "capcut_thanhnientutin", "name": "Thanh Niên Tự Tin (Công nghệ, Đồ gia dụng)", "provider": "capcut", "gender": "male", "preview_url": "/static/previews/capcut_thanhnientutin.mp3"},
        {"id": "capcut_nuphothong", "name": "Giọng Nữ Phổ Thông (Chị Google CapCut)", "provider": "capcut", "gender": "female", "preview_url": "/static/previews/capcut_nuphothong.mp3"},
        {"id": "capcut_namtram", "name": "Giọng Nam Trầm (Điện ảnh, Uy tín)", "provider": "capcut", "gender": "male", "preview_url": "/static/previews/capcut_namtram.mp3"},
        {"id": "capcut_reviewphim", "name": "Review Phim New (Lôi cuốn, Nhấn nhá)", "provider": "capcut", "gender": "female", "preview_url": "/static/previews/capcut_reviewphim.mp3"},
        {"id": "capcut_banmai", "name": "Ban Mai (Tươi tắn, Năng lượng)", "provider": "capcut", "gender": "female", "preview_url": "/static/previews/capcut_banmai.mp3"},
        {"id": "capcut_mai", "name": "Mai (Trầm lắng, Nhẹ nhàng)", "provider": "capcut", "gender": "female", "preview_url": "/static/previews/capcut_mai.mp3"},
        {"id": "capcut_giongge", "name": "Giọng Bé (Đáng yêu, Hoạt hình)", "provider": "capcut", "gender": "female", "preview_url": "/static/previews/capcut_giongge.mp3"},
        {"id": "capcut_vietmeo", "name": "Việt Méo (Hài hước, Meme)", "provider": "capcut", "gender": "male", "preview_url": "/static/previews/capcut_vietmeo.mp3"},
        {"id": "capcut_bantin1", "name": "Bản Tin 1 (Thời sự, Trang trọng)", "provider": "capcut", "gender": "female", "preview_url": "/static/previews/capcut_bantin1.mp3"},
        {"id": "capcut_sunnyidol", "name": "Sunny Idol (Thần tượng, Trẻ trung)", "provider": "capcut", "gender": "female", "preview_url": "/static/previews/capcut_sunnyidol.mp3"},
        {"id": "capcut_gaimoilon", "name": "Gái Mới Lớn (Ngây thơ, Trong trẻo)", "provider": "capcut", "gender": "female", "preview_url": "/static/previews/capcut_gaimoilon.mp3"},
        {"id": "capcut_robot", "name": "Robot VN (Công nghệ, Sci-Fi)", "provider": "capcut", "gender": "male", "preview_url": "/static/previews/capcut_robot.mp3"},
        {"id": "hoaimy", "name": "Hoài Mỹ (Microsoft Edge Neural Nữ, Phóng sự)", "provider": "edge_tts", "gender": "female", "preview_url": "/static/previews/hoaimy.mp3"},
        {"id": "namminh", "name": "Nam Minh (Microsoft Edge Neural Nam, Trầm ấm)", "provider": "edge_tts", "gender": "male", "preview_url": "/static/previews/namminh.mp3"}
    ]

@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    saved_filenames = []
    for file in files:
        if not file.filename:
            continue
        # Tạo tên file an toàn tránh trùng lặp
        ext = Path(file.filename).suffix
        filename = f"{uuid.uuid4()}{ext}"
        file_path = UPLOAD_DIR / filename
        
        try:
            content = await file.read()
            with open(file_path, "wb") as f:
                f.write(content)
            saved_filenames.append(filename)
            logger.info(f"Đã lưu tệp tải lên: {filename}")
        except Exception as e:
            logger.error(f"Lỗi khi lưu tệp {file.filename}: {e}")
            raise HTTPException(status_code=500, detail=f"Không thể lưu file {file.filename}")
            
    return {"filenames": saved_filenames}

@app.post("/api/parse-url")
async def parse_product_url(payload: ParseUrlRequest):
    if not payload.url or not payload.url.strip():
        raise HTTPException(status_code=400, detail="Vui lòng nhập đường dẫn sản phẩm hợp lệ.")
    try:
        result = await manager.parse_product_url_with_browser(payload.url)
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Lỗi trích xuất URL {payload.url}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/tasks")
async def create_task(task_data: TaskCreate):
    if not task_data.images:
        raise HTTPException(status_code=400, detail="Không có hình ảnh nào được gửi.")
    
    # Kiểm tra xem các file có tồn tại thật trong uploads không
    for filename in task_data.images:
        if not (UPLOAD_DIR / filename).exists():
            raise HTTPException(status_code=404, detail=f"Không tìm thấy ảnh: {filename}")
            
    created_tasks = []
    for filename in task_data.images:
        # Mỗi bức ảnh sẽ trở thành 1 nhiệm vụ riêng biệt trong hàng đợi
        task = manager.add_task(
            [filename],
            task_data.user_description,
            task_data.duration,
            task_data.ratio,
            voice_gender=task_data.voice_gender
        )
        created_tasks.append(task)
        
    return {"status": "success", "tasks": created_tasks, "task": created_tasks[0]}

@app.delete("/api/tasks")
async def clear_all_tasks():
    deleted_count = await manager.clear_queue()
    return {"status": "success", "deleted_count": deleted_count}

@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    success = await manager.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhiệm vụ hoặc không thể xóa.")
    return {"status": "success"}

@app.post("/api/tasks/{task_id}/retry")
async def retry_task(task_id: str):
    success = await manager.retry_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Không thể chạy lại nhiệm vụ này (có thể do đang xử lý).")
    return {"status": "success"}

@app.put("/api/tasks/{task_id}")
async def edit_task(task_id: str, task_update: TaskUpdate):
    success = manager.edit_task(
        task_id,
        task_update.user_description,
        task_update.duration,
        task_update.ratio,
        voice_gender=task_update.voice_gender,
        current_task_id=manager.current_task_id
    )
    if not success:
        raise HTTPException(status_code=400, detail="Không thể chỉnh sửa nhiệm vụ này (có thể do đang hoạt động).")
    return {"status": "success"}

@app.get("/api/status")
async def get_status():
    return {
        "status": manager.status,
        "current_task_id": manager.current_task_id,
        "screenshot": manager.screenshot,
        "error_message": manager.error_message,
        "queue": manager.queue
    }

@app.post("/api/start")
async def start_queue():
    await manager.start_queue_processing()
    return {"status": "success", "manager_status": manager.status}

@app.post("/api/stop")
async def stop_queue():
    await manager.stop_queue_processing()
    return {"status": "success", "manager_status": manager.status}

@app.post("/api/open-login")
async def open_login():
    await manager.start_login_session()
    return {"status": "success", "manager_status": manager.status}

@app.post("/api/switch-account")
async def switch_account():
    await manager.switch_account()
    return {"status": "success", "manager_status": manager.status}

@app.get("/api/videos")
async def list_videos():
    """Liệt kê danh sách các video kết quả đã hoàn thành đính kèm thông tin Caption/Hashtags."""
    from backend.services.prompt_optimizer import ensure_caption_and_hashtags, parse_prompt_response, generate_smart_caption_and_hashtags
    videos = []
    try:
        for p in OUTPUT_DIR.glob("*.mp4"):
            stat = p.stat()
            json_path = OUTPUT_DIR / f"{p.stem}.json"
            txt_path = OUTPUT_DIR / f"{p.stem}.txt"
            
            caption = ""
            hashtags = ""
            prompt = ""
            voiceover = ""
            meta_data = {}
            
            if json_path.exists():
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        meta_data = json.load(f)
                        caption = meta_data.get("caption", "")
                        hashtags = meta_data.get("hashtags", "")
                        prompt = meta_data.get("prompt", "")
                        voiceover = meta_data.get("voiceover", "")
                except Exception:
                    pass

            # Nếu chưa có caption trong file json, thử trích xuất từ file txt đi kèm
            if (not caption or not hashtags) and txt_path.exists():
                try:
                    txt_content = txt_path.read_text(encoding="utf-8")
                    parsed_txt = parse_prompt_response(txt_content)
                    if not caption and parsed_txt.get("caption"):
                        caption = parsed_txt["caption"]
                    if not hashtags and parsed_txt.get("hashtags"):
                        hashtags = parsed_txt["hashtags"]
                    if not prompt and parsed_txt.get("prompt"):
                        prompt = parsed_txt["prompt"]
                except Exception:
                    pass

            # Nếu vẫn còn thiếu Caption hoặc Hashtags, tự động tạo smart fallback
            if not caption or not hashtags:
                smart_fb = generate_smart_caption_and_hashtags(prompt or p.stem, prompt)
                caption = caption or smart_fb["caption"]
                hashtags = hashtags or smart_fb["hashtags"]
                
                # Lưu cập nhật lại file json để lần sau tải nhanh
                try:
                    meta_data["video_filename"] = p.name
                    meta_data["caption"] = caption
                    meta_data["hashtags"] = hashtags
                    meta_data["prompt"] = prompt
                    meta_data["voiceover"] = voiceover
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(meta_data, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass

            overlay_text = meta_data.get("overlay_text", [])
            qc_info = meta_data.get("qc_info", {})

            videos.append({
                "filename": p.name,
                "size": stat.st_size,
                "created_at": stat.st_mtime,
                "url": f"/outputs/{p.name}",
                "caption": caption,
                "hashtags": hashtags,
                "prompt": prompt,
                "voiceover": voiceover,
                "overlay_text": overlay_text,
                "qc_info": qc_info
            })
        videos.sort(key=lambda x: x["created_at"], reverse=True)
    except Exception as e:
        logger.error(f"Lỗi quét thư mục video: {e}")
    return JSONResponse(
        content=videos,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

@app.delete("/api/videos/{filename}")
async def delete_video(filename: str):
    """Xóa file video và các file metadata (.json, .txt) đi kèm trong thư mục outputs."""
    safe_filename = Path(filename).name
    if not safe_filename or safe_filename != filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Tên tệp không hợp lệ.")
    
    mp4_path = OUTPUT_DIR / safe_filename
    if not mp4_path.exists():
        raise HTTPException(status_code=404, detail="Không tìm thấy tệp video.")
    
    try:
        mp4_path.unlink(missing_ok=True)
        
        stem = mp4_path.stem
        json_path = OUTPUT_DIR / f"{stem}.json"
        txt_path = OUTPUT_DIR / f"{stem}.txt"
        
        json_path.unlink(missing_ok=True)
        txt_path.unlink(missing_ok=True)
        
        logger.info(f"Đã xóa thành công video và các tệp đi kèm: {filename}")
        return {"status": "success", "message": f"Đã xóa video {filename}"}
    except Exception as e:
        logger.error(f"Lỗi khi xóa video {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Không thể xóa video: {str(e)}")

class BatchDeleteVideosRequest(BaseModel):
    filenames: List[str]

@app.post("/api/videos/batch-delete")
async def batch_delete_videos(req: BatchDeleteVideosRequest):
    """Xóa hàng loạt các file video được chọn trong thư mục outputs."""
    deleted_count = 0
    for filename in req.filenames:
        safe_filename = Path(filename).name
        if not safe_filename or safe_filename != filename or ".." in filename:
            continue
        mp4_path = OUTPUT_DIR / safe_filename
        if mp4_path.exists():
            try:
                mp4_path.unlink(missing_ok=True)
                stem = mp4_path.stem
                (OUTPUT_DIR / f"{stem}.json").unlink(missing_ok=True)
                (OUTPUT_DIR / f"{stem}.txt").unlink(missing_ok=True)
                deleted_count += 1
            except Exception as e:
                logger.error(f"Lỗi khi xóa file {filename}: {e}")
    logger.info(f"Đã xóa hàng loạt {deleted_count} video khỏi thư viện.")
    return {"status": "success", "deleted_count": deleted_count}

