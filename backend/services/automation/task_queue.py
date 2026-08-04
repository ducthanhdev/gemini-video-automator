"""
Quản lý trạng thái hàng đợi nhiệm vụ và cấu hình lưu trữ JSON.
"""

import json
import logging
import uuid
from typing import Any
from backend.config import QUEUE_FILE, SETTINGS_FILE, DEFAULT_SYSTEM_INSTRUCTION, DEFAULT_META_PROMPT_TEMPLATE

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
        self.voice_gender: str = "hoaimy"  # hoaimy (nữ) hoặc namminh (nam)
        self.enable_voiceover: bool = True

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
                self.voice_gender = data.get("voice_gender", "hoaimy")
                self.enable_voiceover = data.get("enable_voiceover", False)
                logger.info("Đã tải cấu hình cài đặt từ file settings.json.")
            else:
                self._save_settings()
        except Exception as e:
            logger.error(f"Lỗi khi tải cấu hình cài đặt từ file: {e}")

    def _save_settings(self):
        """Lưu cấu hình cài đặt vào file settings.json."""
        try:
            data = {
                "api_key": self.api_key,
                "prompt_mode": self.prompt_mode,
                "long_video_mode": self.long_video_mode,
                "system_instruction": self.system_instruction,
                "meta_prompt_template": self.meta_prompt_template,
                "voice_gender": self.voice_gender,
                "enable_voiceover": self.enable_voiceover
            }
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            logger.info("Đã lưu cấu hình cài đặt vào file settings.json.")
        except Exception as e:
            logger.error(f"Lỗi khi lưu cấu hình cài đặt vào file: {e}")

    def _load_queue(self):
        """Tải hàng đợi từ file queue.json nếu có."""
        try:
            if QUEUE_FILE.exists():
                with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                    self.queue = json.load(f)
                # Đưa các tác vụ chưa hoàn thành (đang chạy dở dang hoặc bị kẹt) về pending khi restart server
                for task in self.queue:
                    if task.get("status") not in ["completed", "failed", "pending"]:
                        logger.warning(f"Tự động khôi phục tác vụ {task.get('id')} bị kẹt ở trạng thái '{task.get('status')}' về 'pending'.")
                        task["status"] = "pending"
                        task["progress"] = 0
                        task["error"] = None
                self._save_queue()
                logger.info(f"Đã tải {len(self.queue)} nhiệm vụ từ file lưu trữ.")
            else:
                self.queue = []
        except Exception as e:
            logger.error(f"Lỗi khi tải hàng đợi từ file: {e}")
            self.queue = []

    def _save_queue(self):
        """Lưu hàng đợi vào file queue.json."""
        try:
            with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.queue, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"Lỗi khi lưu hàng đợi vào file: {e}")

    def update_task(self, task: dict[str, Any], **kwargs):
        """Cập nhật thông tin nhiệm vụ và lưu lại vào file queue.json."""
        for key, val in kwargs.items():
            task[key] = val
        self._save_queue()

    def add_task(self, image_filenames: list[str], user_description: str, duration: int, ratio: str = "9:16") -> dict[str, Any]:
        """Thêm một nhiệm vụ tạo video mới vào hàng đợi."""
        task_id = str(uuid.uuid4())
        task = {
            "id": task_id,
            "images": image_filenames,  # Tên file nằm trong storage/uploads
            "user_description": user_description,
            "optimized_prompt": "",
            "duration": duration,
            "ratio": ratio,
            "status": "pending",
            "progress": 0,
            "output_video": None,
            "error": None
        }
        self.queue.append(task)
        self._save_queue()
        logger.info(f"Đã thêm nhiệm vụ {task_id} vào hàng đợi. Tổng nhiệm vụ: {len(self.queue)}")
        return task

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Lấy thông tin của một nhiệm vụ."""
        for t in self.queue:
            if t["id"] == task_id:
                return t
        return None

    def edit_task(self, task_id: str, user_description: str, duration: int, ratio: str, current_task_id: str | None = None) -> bool:
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
        self._save_queue()
        logger.info(f"Đã cập nhật thông tin nhiệm vụ {task_id}.")
        return True
