import socket
import logging
from pathlib import Path
from typing import List
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import asyncio
from contextlib import asynccontextmanager

from backend.config import BASE_DIR, UPLOAD_DIR, OUTPUT_DIR, PORT
from backend.services.automation import AutomationManager
from backend.services.product_parser import ProductParser

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

app = FastAPI(title="Gemini Video Batch Generator", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "frontend" / "static")), name="static")
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

templates = Jinja2Templates(directory=str(BASE_DIR / "frontend" / "templates"))

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

class TaskCreate(BaseModel):
    images: List[str]
    user_description: str
    duration: int
    ratio: str = "9:16"

class TaskUpdate(BaseModel):
    user_description: str
    duration: int
    ratio: str

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
    logger.info("Cập nhật cấu hình thành công.")
    return {"status": "success", "settings": {
        "api_key": manager.api_key,
        "prompt_mode": manager.prompt_mode,
        "long_video_mode": manager.long_video_mode,
        "system_instruction": manager.system_instruction,
        "meta_prompt_template": manager.meta_prompt_template
    }}

@app.get("/api/settings")
async def get_settings():
    return {
        "api_key": manager.api_key,
        "prompt_mode": manager.prompt_mode,
        "long_video_mode": manager.long_video_mode,
        "system_instruction": manager.system_instruction,
        "meta_prompt_template": manager.meta_prompt_template
    }

@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    saved_filenames = []
    for file in files:
        if not file.filename:
            continue
        # Tạo tên file an toàn tránh trùng lặp
        import uuid
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
        task = manager.add_task([filename], task_data.user_description, task_data.duration, task_data.ratio)
        created_tasks.append(task)
        
    return {"status": "success", "tasks": created_tasks, "task": created_tasks[0]}

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
        task_update.ratio
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
    videos = []
    try:
        import json
        for p in OUTPUT_DIR.glob("*.mp4"):
            stat = p.stat()
            json_path = OUTPUT_DIR / f"{p.stem}.json"
            caption = ""
            hashtags = ""
            prompt = ""
            if json_path.exists():
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        caption = meta.get("caption", "")
                        hashtags = meta.get("hashtags", "")
                        prompt = meta.get("prompt", "")
                except Exception:
                    pass

            videos.append({
                "filename": p.name,
                "size": stat.st_size,
                "created_at": stat.st_mtime,
                "url": f"/outputs/{p.name}",
                "caption": caption,
                "hashtags": hashtags,
                "prompt": prompt
            })
        videos.sort(key=lambda x: x["created_at"], reverse=True)
    except Exception as e:
        logger.error(f"Lỗi quét thư mục video: {e}")
    return videos

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

