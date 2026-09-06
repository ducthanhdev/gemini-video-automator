"""
Quản lý trạng thái hàng đợi nhiệm vụ và cấu hình lưu trữ JSON.
"""

import json
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any
from backend.config import (
    QUEUE_FILE,
    QUEUE_BACKUP_FILE,
    SETTINGS_FILE,
    OUTPUT_DIR,
    DEFAULT_SYSTEM_INSTRUCTION,
    DEFAULT_META_PROMPT_TEMPLATE,
)

logger = logging.getLogger(__name__)

class TaskQueueManager:
    """Quản lý trạng thái và tệp lưu trữ dữ liệu của hàng đợi nhiệm vụ và cấu hình cài đặt."""

    def __init__(self):
        self.queue: list[dict[str, Any]] = []
        
        # Cấu hình cài đặt mặc định
        self.api_key: str = ""
        self.prompt_mode: str = "api"  # api hoặc meta
        self.long_video_mode: str = "last_frame"  # last_frame hoặc crossfade
        self.system_instruction: str = DEFAULT_SYSTEM_INSTRUCTION
        self.meta_prompt_template: str = DEFAULT_META_PROMPT_TEMPLATE
        self.voice_gender: str = "capcut_cogaighoatngon"  # capcut_cogaighoatngon, capcut_nhongotngao, capcut_thanhnientutin, hoaimy, namminh
        self.enable_voiceover: bool = True
        self.auto_retry_failed: bool = True  # Tự động lặp lại theo vòng cho đến khi tất cả task hoàn thành

        # Tải cấu hình và hàng đợi từ tệp lưu trữ
        self._load_settings()
        self._load_queue()

    def _load_settings(self):
        """Tải cấu hình cài đặt từ file settings.json nếu có."""
        try:
            if SETTINGS_FILE.exists():
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.api_key = data.get("api_key", "")
                self.prompt_mode = data.get("prompt_mode", "api")
                self.long_video_mode = data.get("long_video_mode", "last_frame")
                self.system_instruction = data.get("system_instruction") or DEFAULT_SYSTEM_INSTRUCTION
                self.meta_prompt_template = data.get("meta_prompt_template") or DEFAULT_META_PROMPT_TEMPLATE
                self.voice_gender = data.get("voice_gender", "capcut_cogaighoatngon")
                self.enable_voiceover = data.get("enable_voiceover", False)
                self.auto_retry_failed = data.get("auto_retry_failed", True)
                logger.info("Đã tải cấu hình cài đặt từ file settings.json.")
            else:
                self._save_settings()
        except Exception as e:
            logger.error(f"Lỗi khi tải cấu hình cài đặt từ file: {e}")

    def _save_settings(self):
        """Lưu cấu hình cài đặt vào file settings.json bằng atomic write."""
        try:
            data = {
                "api_key": self.api_key,
                "prompt_mode": self.prompt_mode,
                "long_video_mode": self.long_video_mode,
                "system_instruction": self.system_instruction,
                "meta_prompt_template": self.meta_prompt_template,
                "voice_gender": self.voice_gender,
                "enable_voiceover": self.enable_voiceover,
                "auto_retry_failed": self.auto_retry_failed
            }
            temp_file = SETTINGS_FILE.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file, SETTINGS_FILE)
            logger.info("Đã lưu cấu hình cài đặt an toàn vào file settings.json.")
        except Exception as e:
            logger.error(f"Lỗi khi lưu cấu hình cài đặt vào file: {e}")

    def _recover_completed_tasks_from_outputs(self):
        """Tự phục hồi các nhiệm vụ đã hoàn thành từ thư mục storage/outputs nếu bị thiếu trong hàng đợi."""
        existing_ids = {t["id"] for t in self.queue}
        recovered_count = 0
        try:
            if not OUTPUT_DIR.exists():
                return
            for meta_file in sorted(OUTPUT_DIR.glob("video_*.json")):
                try:
                    task_id = meta_file.stem.replace("video_", "")
                    if task_id in existing_ids:
                        continue
                    video_file = OUTPUT_DIR / f"{meta_file.stem}.mp4"
                    with open(meta_file, "r", encoding="utf-8") as f:
                        meta_data = json.load(f)

                    user_desc = meta_data.get("caption") or meta_data.get("prompt") or "Video đã tạo thành công"
                    # Rút ngắn tiêu đề nếu quá dài
                    user_desc_short = user_desc.split("\n")[0][:100]

                    recovered_task = {
                        "id": task_id,
                        "images": [],
                        "user_description": user_desc_short,
                        "optimized_prompt": meta_data.get("prompt", ""),
                        "voiceover": meta_data.get("voiceover", ""),
                        "overlay_text": meta_data.get("overlay_text", []),
                        "caption": meta_data.get("caption", ""),
                        "hashtags": meta_data.get("hashtags", ""),
                        "duration": 10,
                        "ratio": "9:16",
                        "status": "completed",
                        "progress": 100,
                        "retry_count": 0,
                        "output_video": video_file.name if video_file.exists() else meta_data.get("video_filename"),
                        "error": None
                    }
                    self.queue.append(recovered_task)
                    existing_ids.add(task_id)
                    recovered_count += 1
                except Exception as item_err:
                    logger.warning(f"Lỗi khi đọc metadata phục hồi từ {meta_file}: {item_err}")

            if recovered_count > 0:
                logger.info(f"🎉 Đã tự động phục hồi {recovered_count} nhiệm vụ hoàn thành từ thư mục outputs.")
                self._save_queue()
        except Exception as e:
            logger.error(f"Lỗi trong quá trình tự phục hồi nhiệm vụ từ outputs: {e}")

    def _load_queue(self):
        """Tải hàng đợi từ file queue.json, tự động phục hồi từ backup hoặc outputs nếu gặp sự cố."""
        loaded_tasks: list[dict[str, Any]] | None = None

        # 1. Thử nạp từ file queue.json chính
        if QUEUE_FILE.exists() and QUEUE_FILE.stat().st_size > 2:
            try:
                with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                    loaded_tasks = json.load(f)
            except Exception as e:
                logger.error(f"Lỗi khi đọc file queue.json ({e}). Chuẩn bị thử nạp từ file backup...")
                loaded_tasks = None

        # 2. Nếu file chính không tồn tại hoặc bị lỗi/trống, thử phục hồi từ queue.json.bak
        if not loaded_tasks and QUEUE_BACKUP_FILE.exists() and QUEUE_BACKUP_FILE.stat().st_size > 2:
            try:
                logger.info("Đang phục hồi hàng đợi từ file sao lưu queue.json.bak...")
                with open(QUEUE_BACKUP_FILE, "r", encoding="utf-8") as f:
                    bak_tasks = json.load(f)
                if isinstance(bak_tasks, list):
                    loaded_tasks = bak_tasks
                    logger.info(f"Phục hồi thành công {len(loaded_tasks)} nhiệm vụ từ file backup.")
            except Exception as bak_err:
                logger.error(f"Lỗi khi đọc file backup queue.json.bak: {bak_err}")

        self.queue = loaded_tasks if isinstance(loaded_tasks, list) else []

        # 3. Phục hồi các task đã hoàn thành từ thư mục outputs nếu chưa có trong queue
        self._recover_completed_tasks_from_outputs()

        # 4. Bảo toàn trạng thái các task:
        # - Task 'completed': giữ nguyên
        # - Task 'failed': giữ nguyên
        # - Task 'pending': giữ nguyên
        # - Task bị ngắt ngang khi đang chạy dở dang (optimizing, uploading, etc.):
        #   Khôi phục an toàn về 'pending', giữ nguyên optimized_prompt/voiceover/caption đã tạo xong
        status_changed = False
        for task in self.queue:
            status = task.get("status")
            if status not in ["completed", "failed", "pending"]:
                logger.warning(
                    f"Tự động khôi phục nhiệm vụ {task.get('id')} bị ngắt ngang ở trạng thái '{status}' về 'pending'."
                )
                task["status"] = "pending"
                task["progress"] = 0
                task["error"] = None
                status_changed = True

        if status_changed or not QUEUE_FILE.exists():
            self._save_queue()

        logger.info(f"Đã tải thành công {len(self.queue)} nhiệm vụ trong hàng đợi.")

    def _save_queue(self):
        """Lưu hàng đợi vào file queue.json bằng cơ chế atomic write và tạo bản sao lưu an toàn."""
        try:
            temp_file = QUEUE_FILE.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.queue, f, ensure_ascii=False, indent=4)
                f.flush()
                os.fsync(f.fileno())

            # Nếu lưu thành công danh sách hợp lệ và queue không rỗng, cập nhật bản sao lưu .bak
            if self.queue and QUEUE_FILE.exists() and QUEUE_FILE.stat().st_size > 2:
                try:
                    shutil.copy2(QUEUE_FILE, QUEUE_BACKUP_FILE)
                except Exception as bak_err:
                    logger.warning(f"Không thể sao lưu queue.json.bak: {bak_err}")

            os.replace(temp_file, QUEUE_FILE)
        except Exception as e:
            logger.error(f"Lỗi khi lưu hàng đợi an toàn: {e}")

    def update_task(self, task: dict[str, Any], **kwargs):
        """Cập nhật thông tin nhiệm vụ và lưu lại vào file queue.json."""
        for key, val in kwargs.items():
            task[key] = val
        self._save_queue()

    def add_task(self, image_filenames: list[str], user_description: str, duration: int, ratio: str = "9:16", voice_gender: str | None = None) -> dict[str, Any]:
        """Thêm một nhiệm vụ tạo video mới vào hàng đợi."""
        task_id = str(uuid.uuid4())
        task = {
            "id": task_id,
            "images": image_filenames,  # Tên file nằm trong storage/uploads
            "user_description": user_description,
            "optimized_prompt": "",
            "voiceover": "",
            "overlay_text": [],
            "caption": "",
            "hashtags": "",
            "duration": duration,
            "ratio": ratio,
            "voice_gender": voice_gender or self.voice_gender,
            "status": "pending",
            "progress": 0,
            "retry_count": 0,
            "output_video": None,
            "error": None
        }
        self.queue.append(task)
        self._save_queue()
        logger.info(f"Đã thêm nhiệm vụ {task_id} vào hàng đợi (Giọng: {task['voice_gender']}). Tổng nhiệm vụ: {len(self.queue)}")
        return task

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Lấy thông tin của một nhiệm vụ."""
        for t in self.queue:
            if t["id"] == task_id:
                return t
        return None

    def edit_task(self, task_id: str, user_description: str, duration: int, ratio: str, voice_gender: str | None = None, current_task_id: str | None = None) -> bool:
        """Chỉnh sửa thông tin nhiệm vụ khi còn ở trạng thái pending hoặc failed."""
        task = self.get_task(task_id)
        if not task:
            return False
            
        if current_task_id == task_id:
            logger.warning(f"Không thể sửa nhiệm vụ đang thực sự hoạt động: {task_id}")
            return False
            
        task["user_description"] = user_description
        task["duration"] = duration
        task["ratio"] = ratio
        if voice_gender:
            task["voice_gender"] = voice_gender
        self._save_queue()
        logger.info(f"Đã cập nhật thông tin nhiệm vụ {task_id}.")
        return True
