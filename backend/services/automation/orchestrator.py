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
from backend.services.prompt_optimizer import optimize_prompt, parse_prompt_response, ensure_caption_and_hashtags
from backend.services.voiceover import process_video_voiceover
from backend.services.video_qc import validate_clip, validate_final_video

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

    @property
    def auto_retry_failed(self): return getattr(self.queue_mgr, "auto_retry_failed", True)
    @auto_retry_failed.setter
    def auto_retry_failed(self, val): setattr(self.queue_mgr, "auto_retry_failed", val)

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
    def add_task(self, image_filenames: list[str], user_description: str, duration: int, ratio: str = "9:16", voice_gender: str | None = None):
        return self.queue_mgr.add_task(image_filenames, user_description, duration, ratio, voice_gender=voice_gender)
    def get_task(self, task_id: str): return self.queue_mgr.get_task(task_id)
    def edit_task(self, task_id: str, user_description: str, duration: int, ratio: str, voice_gender: str | None = None, current_task_id: str | None = None):
        c_id = current_task_id or self.current_task_id
        return self.queue_mgr.edit_task(task_id, user_description, duration, ratio, voice_gender=voice_gender, current_task_id=c_id)

    # Forwarding Driver Methods
    async def initialize(self):
        await self.driver.initialize()
        has_pending = any(t.get("status") == "pending" for t in self.queue)
        if has_pending:
            logger.info("Đã tải các nhiệm vụ đang chờ trong hàng đợi. Chờ người dùng nhấn Khởi chạy.")

    async def shutdown(self):
        logger.info("Đang tiến hành dọn dẹp và tắt AutomationManager...")
        if self.current_task_id:
            curr_task = self.get_task(self.current_task_id)
            if curr_task:
                self.update_task(curr_task, status="pending", progress=0)
            self.current_task_id = None
        if self.loop_task:
            self.loop_task.cancel()
            try:
                await self.loop_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self.loop_task = None
        self._save_queue()
        await self.driver.shutdown()
        logger.info("Hoàn tất tắt AutomationManager.")
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

    async def _automate_browser_for_clip(self, image_paths: list[Path], prompt: str, output_path: Path, task: dict[str, Any], cycle: int = 0, num_cycles: int = 1, api_error: bool = False):
        settings_dict = {
            "api_key": self.api_key,
            "prompt_mode": self.prompt_mode,
            "meta_prompt_template": self.meta_prompt_template,
            "api_error": api_error
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

        # Nếu trong hàng đợi không còn task pending nào nhưng có task failed, tự động đưa các task failed về pending để chạy lại
        has_pending = any(t.get("status") == "pending" for t in self.queue)
        has_failed = any(t.get("status") == "failed" for t in self.queue)
        if not has_pending and has_failed and self.auto_retry_failed:
            logger.info("Không còn nhiệm vụ pending mới, tự động đưa các nhiệm vụ failed về pending để chạy lại...")
            for t in self.queue:
                if t.get("status") == "failed":
                    self.update_task(t, status="pending", progress=0, error=None)

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
        """Vòng lặp chính xử lý từng nhiệm vụ trong hàng đợi theo các vòng lặp (rounds)."""
        round_index = 1
        logger.info(f"🚀 Bắt đầu chu kỳ xử lý hàng đợi - Vòng {round_index}")

        while self.status == "running":
            # 1. Tìm nhiệm vụ tiếp theo ở trạng thái 'pending'
            task_to_run = None
            for t in self.queue:
                if t.get("status") == "pending":
                    task_to_run = t
                    break

            # 2. Nếu trong vòng hiện tại không còn nhiệm vụ nào 'pending'
            if not task_to_run:
                # Kiểm tra danh sách nhiệm vụ bị lỗi (failed) trong hàng đợi
                failed_tasks = [t for t in self.queue if t.get("status") == "failed"]

                # Nếu không còn nhiệm vụ nào bị lỗi (hoặc tính năng tự động lặp lại bị tắt)
                if not failed_tasks or not self.auto_retry_failed:
                    if not failed_tasks:
                        logger.info("🎉 Tất cả các nhiệm vụ trong hàng đợi đã hoàn thành thành công! Tiến trình tự động hóa chuyển về idle.")
                    else:
                        logger.info(f"Hàng đợi đã hoàn thành lượt hiện tại (còn {len(failed_tasks)} nhiệm vụ lỗi nhưng tính năng tự động lặp lại đang tắt).")
                    self.status = "idle"
                    break

                # Có nhiệm vụ bị lỗi -> Thông báo và tạm nghỉ giải tỏa nghẽn trước khi lặp lại vòng tiếp theo
                logger.warning(
                    f"⚠️ Kết thúc Vòng {round_index}: Có {len(failed_tasks)}/{len(self.queue)} nhiệm vụ bị lỗi "
                    f"(thường do nghẽn máy chủ hoặc mạng từ phía Gemini)."
                )
                logger.info(
                    f"⏳ Đang tạm dừng 20 giây để máy chủ Gemini giải tỏa nghẽn trước khi tự động chạy lại Vòng {round_index + 1}..."
                )

                # Chờ 20 giây có kiểm tra ngắt để phản hồi ngay nếu người dùng nhấn Dừng
                for _ in range(20):
                    if self.status != "running":
                        break
                    await asyncio.sleep(1)

                if self.status != "running":
                    logger.info("Tiến trình xử lý hàng đợi đã bị dừng bởi người dùng.")
                    break

                # Đưa toàn bộ nhiệm vụ failed về pending để chạy lại trong vòng tiếp theo
                round_index += 1
                logger.info(f"🔄 Bắt đầu Vòng {round_index}: Tự động chạy lại {len(failed_tasks)} nhiệm vụ bị lỗi...")
                for t in failed_tasks:
                    retry_cnt = t.get("retry_count", 0) + 1
                    self.update_task(
                        t,
                        status="pending",
                        progress=0,
                        retry_count=retry_cnt,
                        error=None
                    )
                continue

            # 3. Đảm bảo trình duyệt luôn mở và sẵn sàng trước khi thực thi nhiệm vụ
            try:
                await self.driver.initialize()
            except Exception as init_err:
                logger.error(f"Lỗi khi kiểm tra/khởi tạo trình duyệt trước task {task_to_run['id']}: {init_err}")

            self.current_task_id = task_to_run["id"]
            current_retry = task_to_run.get("retry_count", 0)
            retry_info = f" (Lần thử {current_retry + 1} - Vòng {round_index})" if current_retry > 0 else f" (Vòng {round_index})"
            logger.info(f"▶️ Bắt đầu xử lý nhiệm vụ: {task_to_run['id']}{retry_info}")

            try:
                await self._execute_task(task_to_run)
            except asyncio.CancelledError:
                self.update_task(task_to_run, status="pending", progress=0)
                logger.info(f"Nhiệm vụ {task_to_run['id']} bị hủy giữa chừng.")
                raise
            except Exception as e:
                logger.error(f"❌ Lỗi khi thực thi nhiệm vụ {task_to_run['id']}: {e}")
                retry_cnt = task_to_run.get("retry_count", 0) + 1
                self.update_task(
                    task_to_run,
                    status="failed",
                    error=str(e),
                    retry_count=retry_cnt
                )
            finally:
                self.current_task_id = None

            await asyncio.sleep(5)

    async def _execute_task(self, task: dict[str, Any]):
        """Thực thi một nhiệm vụ tạo video chi tiết."""
        logger.info(f"Bắt đầu thực thi nhiệm vụ {task['id']}")
        self.update_task(task, status="optimizing", progress=5)
        
        abs_image_paths = [UPLOAD_DIR / filename for filename in task["images"]]
        
        # Nếu task đã có sẵn prompt tối ưu & caption (ví dụ từ vòng trước), tái sử dụng để tiết kiệm thời gian và tránh nghẽn
        if task.get("optimized_prompt") and task.get("caption") and task.get("hashtags"):
            logger.info(f"Nhiệm vụ {task['id']} đã có sẵn prompt tối ưu & caption. Bỏ qua bước tối ưu lại, tiến hành tạo video ngay...")
            optimized = task["optimized_prompt"]
            voiceover = task.get("voiceover", "")
            overlay_text = task.get("overlay_text", [])
            caption = task.get("caption", "")
            hashtags = task.get("hashtags", "")
            api_error = False
            self.update_task(task, progress=10)
        else:
            api_key_to_use = self.api_key if self.prompt_mode == "api" else None
            from backend.services.prompt_optimizer import optimize_prompt as opt_func
            opt_res = await asyncio.to_thread(
                opt_func,
                abs_image_paths,
                task["user_description"],
                api_key_to_use,
                self.system_instruction,
                self.meta_prompt_template
            )
            api_error = False
            if isinstance(opt_res, dict):
                optimized = opt_res.get("prompt", "")
                voiceover = opt_res.get("voiceover", "")
                overlay_text = opt_res.get("overlay_text", [])
                caption = opt_res.get("caption", "")
                hashtags = opt_res.get("hashtags", "")
                api_error = opt_res.get("api_error", False)
                is_meta = opt_res.get("is_meta", False)
            else:
                optimized = str(opt_res)
                voiceover = ""
                overlay_text = []
                caption = ""
                hashtags = ""
                is_meta = False

            # NẾU LÀ META-PROMPT (chờ gửi vào Chat Gemini để sinh prompt thật), không gán nó làm visual prompt của task
            task_opt_prompt = "" if is_meta else optimized

            self.update_task(
                task,
                optimized_prompt=task_opt_prompt,
                voiceover=voiceover,
                overlay_text=overlay_text,
                caption=caption,
                hashtags=hashtags,
                progress=10
            )

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
                    prompt_to_send = task.get("optimized_prompt") or optimized
                else:
                    prompt_to_send = (
                        f"Please continue the animation of this scene based on this original narrative: '{task['optimized_prompt']}'. "
                        "Keep the motion smooth and natural, continuing the action directly from this image. "
                        "Maintain the style, details, camera movement direction, and lighting from the image."
                    )
                
                await self._automate_browser_for_clip(
                    cycle_images, prompt_to_send, clip_path, task,
                    cycle=cycle, num_cycles=num_cycles, api_error=api_error
                )

                # KIỂM ĐỊNH KỸ THUẬT (Technical QC) CHO CLIP VỪA TẢI VỀ
                clip_valid, clip_reason, clip_info = validate_clip(clip_path)
                if not clip_valid:
                    logger.error(f"❌ Clip {cycle + 1}/{num_cycles} không đạt Technical QC: {clip_reason}")
                    raise Exception(f"Clip {cycle + 1} không đạt Technical QC: {clip_reason}")
                logger.info(f"✅ Clip {cycle + 1}/{num_cycles} đạt Technical QC ({clip_info.get('duration')}s, {clip_info.get('width')}x{clip_info.get('height')})")

                generated_clips.append(clip_path)

            self.update_task(task, status="stitching videos", progress=85)
            
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

            # 1. Đảm bảo toàn vẹn thông tin metadata (caption, hashtags, voiceover, overlay_text, prompt)
            ensured_meta = ensure_caption_and_hashtags({
                "prompt": task.get("optimized_prompt", ""),
                "voiceover": task.get("voiceover", ""),
                "overlay_text": task.get("overlay_text", []),
                "caption": task.get("caption", ""),
                "hashtags": task.get("hashtags", "")
            }, task.get("user_description", ""))

            prompt_val = ensured_meta["prompt"]
            voiceover_val = ensured_meta["voiceover"]
            overlay_text_val = ensured_meta.get("overlay_text", [])
            caption_val = ensured_meta["caption"]
            hashtags_val = ensured_meta["hashtags"]

            task["caption"] = caption_val
            task["hashtags"] = hashtags_val
            task["voiceover"] = voiceover_val
            task["overlay_text"] = overlay_text_val
            task["optimized_prompt"] = prompt_val

            # 2. Tự động vẽ On-Screen Text Overlay (Phụ đề/Hook giật gân chuẩn TikTok)
            if overlay_text_val and len(overlay_text_val) > 0:
                self.update_task(task, status="applying on-screen text overlay", progress=90)
                logger.info(f"Đang tiến hành vẽ {len(overlay_text_val)} câu text overlay lên video...")
                overlay_success = await asyncio.to_thread(
                    video_processor.apply_text_overlay, final_output_path, overlay_text_val, final_output_path
                )
                if overlay_success:
                    logger.info("✨ Tự động vẽ On-Screen Text Overlay thành công!")
                else:
                    logger.warning("Vẽ Text Overlay chưa thành công, giữ nguyên video hiện tại.")

            # 3. Tự động lồng tiếng AI (EdgeTTS) và ghép âm thanh vào file video MP4 (với Duration Control & Ducking)
            if getattr(self, "enable_voiceover", True):
                if voiceover_val and voiceover_val.strip():
                    voice_key = task.get("voice_gender") or getattr(self, "voice_gender", "capcut_cogaighoatngon")
                    logger.info(f"Đang tiến hành tự động lồng tiếng AI cho video (Giọng: {voice_key})... Text: '{voiceover_val[:50]}...'")
                    voice_success = await process_video_voiceover(
                        final_output_path,
                        voiceover_val,
                        voice_key=voice_key,
                        target_duration=float(task.get("duration", 10))
                    )
                    if voice_success:
                        logger.info("⚡ Tự động lồng tiếng AI và ghép âm thanh thành công!")
                    else:
                        logger.warning("Lồng tiếng AI không thành công, giữ nguyên video gốc.")
                else:
                    logger.warning("Không có nội dung Kịch bản lồng tiếng để sinh âm thanh.")

            # 4. Technical QC kiểm tra video hoàn thiện cuối cùng
            final_valid, final_reason, final_qc_info = validate_final_video(
                final_output_path,
                expected_duration=float(task.get("duration", 10)),
                has_audio=getattr(self, "enable_voiceover", False) and bool(voiceover_val)
            )
            if not final_valid:
                logger.warning(f"⚠️ Cảnh báo Technical QC video hoàn thiện: {final_reason}")
            else:
                logger.info(f"🎉 Technical QC PASS cho video hoàn thiện: {final_qc_info.get('width')}x{final_qc_info.get('height')}, {final_qc_info.get('duration')}s, Audio: {final_qc_info.get('has_audio')}")

            meta_json_path = OUTPUT_DIR / f"video_{task['id']}.json"
            meta_txt_path = OUTPUT_DIR / f"video_{task['id']}.txt"

            meta_data = {
                "video_filename": output_filename,
                "prompt": prompt_val,
                "voiceover": voiceover_val,
                "overlay_text": overlay_text_val,
                "caption": caption_val,
                "hashtags": hashtags_val,
                "qc_info": final_qc_info,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            with open(meta_json_path, "w", encoding="utf-8") as f:
                json.dump(meta_data, f, ensure_ascii=False, indent=2)
                
            txt_content = (
                f"--- KỊCH BẢN LỒNG TIẾNG ---\n{voiceover_val}\n\n"
                f"--- PHỤ ĐỀ / TEXT OVERLAY ---\n"
                + "\n".join([f"[{item.get('start', 0)}s - {item.get('end', 0)}s]: {item.get('text', '')}" for item in overlay_text_val])
                + f"\n\n--- BÀI ĐĂNG CAPTION ---\n{caption_val}\n\n"
                f"--- HASHTAGS ---\n{hashtags_val}\n\n"
                f"--- PROMPT VIDEO ---\n{prompt_val}"
            )
            with open(meta_txt_path, "w", encoding="utf-8") as f:
                f.write(txt_content)

            self.update_task(
                task,
                status="completed",
                progress=100,
                output_video=output_filename,
                caption=caption_val,
                hashtags=hashtags_val,
                voiceover=voiceover_val,
                overlay_text=overlay_text_val,
                optimized_prompt=prompt_val
            )
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
