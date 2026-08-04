"""
Điều phối luồng xử lý chính của task, gọi prompt optimizer, điều khiển chu kỳ clip, ghép nối FFmpeg, voiceover & xuất metadata.
"""

import asyncio
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.config import UPLOAD_DIR, OUTPUT_DIR, CLIP_DURATION
from backend.services import video_processor
from backend.services.prompt_optimizer import optimize_prompt, parse_prompt_response
from backend.services.voiceover import process_video_voiceover

from backend.services.automation.task_queue import TaskQueueManager
from backend.services.automation.browser_driver import BrowserDriver
from backend.services.automation.gemini_bot import GeminiBot

logger = logging.getLogger(__name__)

class AutomationManager:
    """Class điều phối chính, kết hợp TaskQueueManager, BrowserDriver và GeminiBot."""

    def __init__(self):
        self.queue_mgr = TaskQueueManager()
        self.driver = BrowserDriver()
        self.bot = GeminiBot(self.driver)
        
        self.current_task_id: str | None = None
        self.loop_task: asyncio.Task | None = None

    # Forwarding properties cho TaskQueueManager
    @property
    def queue(self): return self.queue_mgr.queue
    @queue.setter
    def queue(self, val): self.queue_mgr.queue = val

    @property
    def api_key(self): return self.queue_mgr.api_key
    @api_key.setter
    def api_key(self, val): self.queue_mgr.api_key = val

    @property
    def prompt_mode(self): return self.queue_mgr.prompt_mode
    @prompt_mode.setter
    def prompt_mode(self, val): self.queue_mgr.prompt_mode = val

    @property
    def long_video_mode(self): return self.queue_mgr.long_video_mode
    @long_video_mode.setter
    def long_video_mode(self, val): self.queue_mgr.long_video_mode = val

    @property
    def system_instruction(self): return self.queue_mgr.system_instruction
    @system_instruction.setter
    def system_instruction(self, val): self.queue_mgr.system_instruction = val

    @property
    def meta_prompt_template(self): return self.queue_mgr.meta_prompt_template
    @meta_prompt_template.setter
    def meta_prompt_template(self, val): self.queue_mgr.meta_prompt_template = val

    @property
    def voice_gender(self): return getattr(self.queue_mgr, "voice_gender", "hoaimy")
    @voice_gender.setter
    def voice_gender(self, val): setattr(self.queue_mgr, "voice_gender", val)

    @property
    def enable_voiceover(self): return getattr(self.queue_mgr, "enable_voiceover", True)
    @enable_voiceover.setter
    def enable_voiceover(self, val): setattr(self.queue_mgr, "enable_voiceover", val)

    # Forwarding properties cho BrowserDriver
    @property
    def status(self): return self.driver.status
    @status.setter
    def status(self, val): self.driver.status = val

    @property
    def screenshot(self): return self.driver.screenshot
    @property
    def error_message(self): return self.driver.error_message
    @property
    def playwright(self): return self.driver.playwright
    @property
    def browser(self): return None
    @property
    def context(self): return self.driver.context
    @property
    def page(self): return self.driver.page

    # Forwarding Queue Methods
    def _load_settings(self): self.queue_mgr._load_settings()
    def _save_settings(self): self.queue_mgr._save_settings()
    def _load_queue(self): self.queue_mgr._load_queue()
    def _save_queue(self): self.queue_mgr._save_queue()
    def update_task(self, task: dict[str, Any], **kwargs): self.queue_mgr.update_task(task, **kwargs)
    def add_task(self, image_filenames: list[str], user_description: str, duration: int, ratio: str = "9:16"):
        return self.queue_mgr.add_task(image_filenames, user_description, duration, ratio)
    def get_task(self, task_id: str): return self.queue_mgr.get_task(task_id)
    def edit_task(self, task_id: str, user_description: str, duration: int, ratio: str):
        return self.queue_mgr.edit_task(task_id, user_description, duration, ratio, current_task_id=self.current_task_id)

    # Forwarding Driver Methods
    async def initialize(self):
        await self.driver.initialize()
        has_pending = any(t.get("status") == "pending" for t in self.queue)
        if has_pending:
            logger.info("Đã tải các nhiệm vụ đang chờ trong hàng đợi. Chờ người dùng nhấn Khởi chạy.")

    async def shutdown(self): await self.driver.shutdown()
    async def check_login_status(self): return await self.driver.check_login_status()
    async def start_login_session(self): await self.driver.start_login_session()
    async def switch_account(self): await self.driver.switch_account()

    # Forwarding Bot Methods
    async def parse_product_url_with_browser(self, url: str):
        return await self.bot.parse_product_url_with_browser(url, api_key=self.api_key)

    async def _upload_images_to_page(self, image_paths: list[Path], timeout_seconds: int = 90):
        return await self.bot._upload_images_to_page(image_paths, timeout_seconds)

    async def _upload_image_in_video_mode(self, image_paths: list[Path]):
        return await self.bot._upload_image_in_video_mode(image_paths)

    async def _automate_browser_for_clip(self, image_paths: list[Path], prompt: str, output_path: Path, task: dict[str, Any], cycle: int = 0, num_cycles: int = 1):
        settings_dict = {
            "api_key": self.api_key,
            "prompt_mode": self.prompt_mode,
            "meta_prompt_template": self.meta_prompt_template
        }
        return await self.bot._automate_browser_for_clip(
            image_paths, prompt, output_path, task,
            update_task_fn=self.update_task,
            settings=settings_dict,
            cycle=cycle,
            num_cycles=num_cycles
        )

    # Orchestrator Task Management & Execution
    async def delete_task(self, task_id: str) -> bool:
        """Xóa một nhiệm vụ khỏi hàng đợi. Nếu đang chạy, hủy bỏ tiến trình."""
        task = self.get_task(task_id)
        if not task:
            return False
            
        if self.current_task_id == task_id:
            logger.info(f"Hủy bỏ nhiệm vụ đang chạy: {task_id}")
            if self.loop_task:
                self.loop_task.cancel()
                try:
                    await self.loop_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"Lỗi khi hủy loop_task: {e}")
                self.loop_task = None
            self.current_task_id = None
            
        self.queue_mgr.queue = [t for t in self.queue_mgr.queue if t["id"] != task_id]
        self._save_queue()
        logger.info(f"Đã xóa nhiệm vụ {task_id} khỏi hàng đợi.")
        
        if self.status == "running" and not self.loop_task:
            self.status = "idle"
            await self.start_queue_processing()
            
        return True

    async def clear_queue(self) -> int:
        """Xóa tất cả các nhiệm vụ khỏi hàng đợi."""
        count = len(self.queue)
        if count == 0:
            return 0

        if self.current_task_id:
            logger.info(f"Hủy bỏ nhiệm vụ đang chạy {self.current_task_id} do xóa toàn bộ hàng đợi.")
            if self.loop_task:
                self.loop_task.cancel()
                try:
                    await self.loop_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"Lỗi khi hủy loop_task trong clear_queue: {e}")
                self.loop_task = None
            self.current_task_id = None

        self.queue_mgr.queue = []
        self._save_queue()
        self.status = "idle"
        logger.info(f"Đã xóa toàn bộ {count} nhiệm vụ khỏi hàng đợi.")
        return count

    async def retry_task(self, task_id: str) -> bool:
        """Chạy lại một nhiệm vụ (đổi trạng thái về pending)."""
        task = self.get_task(task_id)
        if not task:
            return False
            
        if self.current_task_id == task_id:
            logger.warning(f"Không thể chạy lại nhiệm vụ đang thực sự hoạt động: {task_id}")
            return False
            
        task["status"] = "pending"
        task["progress"] = 0
        task["error"] = None
        task["output_video"] = None
        self._save_queue()
        logger.info(f"Đã đưa nhiệm vụ {task_id} về trạng thái chờ xử lý.")
        
        if self.status in ["idle", "paused"]:
            if self.status == "paused":
                self.status = "idle"
            await self.start_queue_processing()
            
        return True

    async def start_queue_processing(self):
        """Bắt đầu chạy vòng lặp xử lý hàng đợi nhiệm vụ."""
        if self.status == "running":
            return
            
        is_logged_in = await self.check_login_status()
        if not is_logged_in:
            logger.warning("Dừng xử lý hàng đợi vì chưa đăng nhập.")
            return

        self.status = "running"
        self.loop_task = asyncio.create_task(self._queue_loop())
        logger.info("Đã bắt đầu tiến trình xử lý hàng đợi.")

    async def stop_queue_processing(self):
        """Tạm dừng xử lý hàng đợi."""
        self.status = "paused"
        if self.loop_task:
            self.loop_task.cancel()
            self.loop_task = None
        self.current_task_id = None
        logger.info("Đã tạm dừng tiến trình xử lý hàng đợi.")

    async def _queue_loop(self):
        """Vòng lặp chính xử lý từng nhiệm vụ trong hàng đợi."""
        while self.status == "running":
            task_to_run = None
            for t in self.queue:
                if t["status"] == "pending":
                    task_to_run = t
                    break
                    
            if not task_to_run:
                logger.info("Hàng đợi trống. Tiến trình tự động hóa chuyển về idle.")
                self.status = "idle"
                break
                
            self.current_task_id = task_to_run["id"]
            try:
                await self._execute_task(task_to_run)
            except asyncio.CancelledError:
                self.update_task(task_to_run, status="pending", progress=0)
                logger.info(f"Nhiệm vụ {task_to_run['id']} bị hủy giữa chừng.")
                raise
            except Exception as e:
                logger.error(f"Lỗi khi thực thi nhiệm vụ {task_to_run['id']}: {e}")
                self.update_task(task_to_run, status="failed", error=str(e))
            finally:
                self.current_task_id = None
                
            await asyncio.sleep(5)

    async def _execute_task(self, task: dict[str, Any]):
        """Thực thi một nhiệm vụ tạo video chi tiết."""
        logger.info(f"Bắt đầu thực thi nhiệm vụ {task['id']}")
        self.update_task(task, status="optimizing", progress=5)
        
        abs_image_paths = [UPLOAD_DIR / filename for filename in task["images"]]
        
        api_key_to_use = self.api_key if self.prompt_mode == "api" else None
        opt_res = await asyncio.to_thread(
            optimize_prompt,
            abs_image_paths,
            task["user_description"],
            api_key_to_use,
            self.system_instruction,
            self.meta_prompt_template
        )
        if isinstance(opt_res, dict):
            optimized = opt_res.get("prompt", "")
            voiceover = opt_res.get("voiceover", "")
            caption = opt_res.get("caption", "")
            hashtags = opt_res.get("hashtags", "")
        else:
            optimized = str(opt_res)
            voiceover = ""
            caption = ""
            hashtags = ""

        self.update_task(task, optimized_prompt=optimized, voiceover=voiceover, caption=caption, hashtags=hashtags, progress=10)

        num_cycles = max(1, task["duration"] // CLIP_DURATION)
        logger.info(f"Nhiệm vụ {task['id']} yêu cầu thời lượng {task['duration']}s. CLIP_DURATION = {CLIP_DURATION}s. Số lượng clip cần sinh: {num_cycles}")
        generated_clips: list[Path] = []
        
        temp_dir = UPLOAD_DIR / f"temp_{task['id']}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            for cycle in range(num_cycles):
                progress_step = 10 + int((cycle / num_cycles) * 75)
                self.update_task(task, status=f"uploading (cycle {cycle + 1}/{num_cycles})", progress=progress_step)
                
                if cycle == 0:
                    cycle_images = abs_image_paths
                else:
                    last_clip = generated_clips[-1]
                    last_frame_path = temp_dir / f"last_frame_cycle_{cycle}.jpg"
                    
                    self.update_task(task, status=f"extracting last frame (cycle {cycle + 1}/{num_cycles})")
                    success = await asyncio.to_thread(
                        video_processor.extract_last_frame, last_clip, last_frame_path
                    )
                    if not success or not last_frame_path.exists():
                        raise Exception("Không thể trích xuất khung hình cuối từ clip trước.")
                    
                    cycle_images = [last_frame_path]
                
                clip_path = temp_dir / f"clip_{cycle}.mp4"
                
                if cycle == 0:
                    prompt_to_send = task["optimized_prompt"]
                else:
                    prompt_to_send = (
                        f"Please continue the animation of this scene based on this original narrative: '{task['optimized_prompt']}'. "
                        "Keep the motion smooth and natural, continuing the action directly from this image. "
                        "Maintain the style, details, camera movement direction, and lighting from the image."
                    )
                
                await self._automate_browser_for_clip(cycle_images, prompt_to_send, clip_path, task, cycle=cycle, num_cycles=num_cycles)
                generated_clips.append(clip_path)

            self.update_task(task, status="stitching videos", progress=88)
            
            output_filename = f"video_{task['id']}.mp4"
            final_output_path = OUTPUT_DIR / output_filename
            
            if len(generated_clips) == 1:
                await asyncio.to_thread(shutil.copy2, generated_clips[0], final_output_path)
            else:
                if self.long_video_mode == "last_frame":
                    success = await asyncio.to_thread(
                        video_processor.concatenate_videos_direct, generated_clips, final_output_path
                    )
                else:
                    success = await asyncio.to_thread(
                        video_processor.concatenate_videos_xfade, generated_clips, final_output_path, 0.5
                    )
                
                if not success or not final_output_path.exists():
                    raise Exception("Lỗi khi ghép nối các đoạn video ngắn thành video tổng hợp.")

            # 1. Giải mã và chuẩn hóa các thông tin metadata (caption, hashtags, voiceover, prompt)
            caption_val = task.get("caption", "")
            hashtags_val = task.get("hashtags", "")
            prompt_val = task.get("optimized_prompt", "")
            voiceover_val = task.get("voiceover", "")
            
            if not caption_val or not hashtags_val or not voiceover_val:
                fallback_parsed = parse_prompt_response(prompt_val)
                if not caption_val and fallback_parsed.get("caption"):
                    caption_val = fallback_parsed["caption"]
                    task["caption"] = caption_val
                if not hashtags_val and fallback_parsed.get("hashtags"):
                    hashtags_val = fallback_parsed["hashtags"]
                    task["hashtags"] = hashtags_val
                if not voiceover_val and fallback_parsed.get("voiceover"):
                    voiceover_val = fallback_parsed["voiceover"]
                    task["voiceover"] = voiceover_val
                if not prompt_val and fallback_parsed.get("prompt"):
                    prompt_val = fallback_parsed["prompt"]
                    task["optimized_prompt"] = prompt_val

            # Nếu voiceover_val vẫn trống, tự động tạo kịch bản từ caption hoặc mô tả sản phẩm của người dùng
            if not voiceover_val or not voiceover_val.strip():
                src_text = caption_val if caption_val else task.get("user_description", "")
                clean_src = re.sub(r'#\w+', '', src_text).strip()
                clean_src = re.sub(r'PROMPT:|CAPTION:|HASHTAGS:|VOICEOVER:', '', clean_src, flags=re.IGNORECASE).strip()
                words = clean_src.split()
                if words:
                    voiceover_val = ' '.join(words[:30])
                    task["voiceover"] = voiceover_val

            # 2. Tự động lồng tiếng AI (EdgeTTS) và ghép âm thanh vào file video MP4
            if getattr(self, "enable_voiceover", True):
                if voiceover_val and voiceover_val.strip():
                    self.update_task(task, status="generating AI voiceover audio", progress=93)
                    logger.info(f"Đang tiến hành tự động lồng tiếng AI cho video (Giọng: {getattr(self, 'voice_gender', 'hoaimy')})... Text: '{voiceover_val[:50]}...'")
                    voice_key = getattr(self, "voice_gender", "hoaimy")
                    voice_success = await process_video_voiceover(final_output_path, voiceover_val, voice_key=voice_key)
                    if voice_success:
                        logger.info("⚡ Tự động lồng tiếng AI và ghép âm thanh thành công!")
                    else:
                        logger.warning("Lồng tiếng AI không thành công, giữ nguyên video gốc.")
                else:
                    logger.warning("Không có nội dung Kịch bản lồng tiếng để sinh âm thanh.")

            meta_json_path = OUTPUT_DIR / f"video_{task['id']}.json"
            meta_txt_path = OUTPUT_DIR / f"video_{task['id']}.txt"

            meta_data = {
                "video_filename": output_filename,
                "prompt": prompt_val,
                "voiceover": voiceover_val,
                "caption": caption_val,
                "hashtags": hashtags_val,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            with open(meta_json_path, "w", encoding="utf-8") as f:
                json.dump(meta_data, f, ensure_ascii=False, indent=2)
                
            txt_content = f"--- KỊCH BẢN LỒNG TIẾNG ---\n{voiceover_val}\n\n--- BÀI ĐĂNG CAPTION ---\n{caption_val}\n\n--- HASHTAGS ---\n{hashtags_val}\n\n--- PROMPT VIDEO ---\n{prompt_val}"
            with open(meta_txt_path, "w", encoding="utf-8") as f:
                f.write(txt_content)

            self.update_task(task, status="completed", progress=100, output_video=output_filename)
            logger.info(f"Đã hoàn thành nhiệm vụ {task['id']}. Video kết quả: {final_output_path}")

        except Exception as e:
            logger.error(f"Lỗi trong quá trình tạo video cho task {task['id']}: {e}")
            self.update_task(task, status="failed", error=str(e))
            raise e
        finally:
            try:
                if temp_dir.exists():
                    await asyncio.to_thread(shutil.rmtree, temp_dir)
            except Exception as e:
                logger.error(f"Không thể xóa thư mục tạm {temp_dir}: {e}")
