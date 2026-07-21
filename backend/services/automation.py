import asyncio
import base64
import logging
import uuid
from pathlib import Path
from typing import Any
from playwright.async_api import async_playwright
from backend.config import PROFILE_DIR, UPLOAD_DIR, OUTPUT_DIR, DEFAULT_SYSTEM_INSTRUCTION, DEFAULT_META_PROMPT_TEMPLATE, CLIP_DURATION, QUEUE_FILE
from backend.services.prompt_optimizer import optimize_prompt
from backend.services import video_processor

logger = logging.getLogger(__name__)

class AutomationManager:
    def __init__(self):
        self.queue = []
        self.status = "idle"  # idle, waiting_login, running, paused
        self.current_task_id = None
        self.screenshot = None
        self.error_message = None
        
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        
        self.loop_task = None
        self.screenshot_task = None
        
        # Cấu hình cài đặt
        self.api_key = ""
        self.prompt_mode = "api"  # api hoặc meta
        self.long_video_mode = "last_frame"  # last_frame hoặc crossfade
        self.system_instruction = DEFAULT_SYSTEM_INSTRUCTION
        self.meta_prompt_template = DEFAULT_META_PROMPT_TEMPLATE

        # Tải hàng đợi đã lưu từ trước
        self._load_queue()

    def _load_queue(self):
        """Tải hàng đợi từ file queue.json nếu có."""
        import json
        try:
            if QUEUE_FILE.exists():
                with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                    self.queue = json.load(f)
                # Đưa các tác vụ đang chạy dở dang hoặc bị kẹt về pending
                for task in self.queue:
                    if task.get("status") in ["processing", "generating", "uploading", "running", "optimizing", "stitching videos", "submitting prompt", "generating video (waiting 1-3 mins)", "downloading generated video"]:
                        task["status"] = "pending"
                        task["progress"] = 0
                logger.info(f"Đã tải {len(self.queue)} nhiệm vụ từ file lưu trữ.")
            else:
                self.queue = []
        except Exception as e:
            logger.error(f"Lỗi khi tải hàng đợi từ file: {e}")
            self.queue = []

    def _save_queue(self):
        """Lưu hàng đợi vào file queue.json."""
        import json
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

    async def initialize(self):
        """Khởi tạo Playwright và mở trình duyệt."""
        if self.playwright:
            if self.page and not self.page.is_closed():
                return
            else:
                logger.info("Phát hiện trình duyệt hoặc trang đã bị đóng. Đang dọn dẹp để khởi tạo lại...")
                await self.shutdown()
            
        try:
            logger.info("Đang khởi tạo Playwright...")
            self.playwright = await async_playwright().start()
            
            # Khởi chạy Persistent Context sử dụng Chrome của hệ thống kèm cờ ẩn chế độ tự động hóa
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                channel="chrome",
                headless=False,  # Bắt buộc headless=False để người dùng đăng nhập
                viewport={"width": 1280, "height": 800},
                no_viewport=False,
                ignore_default_args=["--enable-automation"],
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars"
                ]
            )
            
            # Khử thuộc tính navigator.webdriver để Google không phát hiện trình duyệt ảo
            await self.context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            # Thiết lập timeout mặc định
            self.context.set_default_timeout(30000)
            
            # Lấy hoặc tạo page mới
            if self.context.pages:
                self.page = self.context.pages[0]
            else:
                self.page = await self.context.new_page()
                
            logger.info("Đã khởi chạy trình duyệt Chrome thành công.")
            
            # Chạy task chụp ảnh màn hình ngầm
            self.screenshot_task = asyncio.create_task(self._screenshot_loop())
            
            # Tự động kích hoạt hàng đợi nếu có nhiệm vụ pending/đang chờ
            has_pending = any(t.get("status") == "pending" for t in self.queue)
            if has_pending:
                logger.info("Phát hiện có nhiệm vụ đang chờ trong hàng đợi. Đang tự động chạy...")
                asyncio.create_task(self.start_queue_processing())
            
        except Exception as e:
            logger.error(f"Lỗi khi khởi tạo trình duyệt Chrome: {e}")
            self.error_message = f"Không thể mở Chrome: {str(e)}. Hãy chắc chắn rằng bạn đã cài đặt Google Chrome trên máy tính."
            await self.shutdown()

    async def shutdown(self):
        """Đóng trình duyệt và giải phóng tài nguyên."""
        logger.info("Đang đóng trình duyệt...")
        if self.screenshot_task:
            self.screenshot_task.cancel()
            self.screenshot_task = None
            
        try:
            if self.context:
                await self.context.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            logger.error(f"Lỗi khi đóng Playwright: {e}")
        finally:
            self.playwright = None
            self.browser = None
            self.context = None
            self.page = None
            self.status = "idle"

    async def _screenshot_loop(self):
        """Luồng chụp ảnh màn hình trình duyệt định kỳ gửi lên UI."""
        while True:
            try:
                if self.page:
                    # Chụp ảnh chất lượng thấp để giảm băng thông truyền tải
                    screenshot_bytes = await self.page.screenshot(type="jpeg", quality=40)
                    self.screenshot = base64.b64encode(screenshot_bytes).decode('utf-8')
                    
                    # Tự động phát hiện nếu người dùng đã hoàn thành đăng nhập
                    if self.status == "waiting_login":
                        url = self.page.url
                        if "gemini.google.com" in url:
                            textbox = self.page.locator("div[role='textbox'], [contenteditable='true']").first
                            if await textbox.is_visible(timeout=500):
                                logger.info("Tự động phát hiện người dùng đã đăng nhập thành công.")
                                self.status = "idle"
            except Exception:
                # Bỏ qua lỗi khi page đang tải hoặc đóng
                pass
            await asyncio.sleep(1.5)

    async def check_login_status(self) -> bool:
        """Kiểm tra xem người dùng đã đăng nhập Gemini chưa."""
        if not self.page:
            await self.initialize()
            if not self.page:
                logger.error("Không thể khởi tạo trang trình duyệt.")
                self.status = "waiting_login"
                return False
            
        try:
            logger.info("Đang kiểm tra trạng thái đăng nhập trên Gemini...")
            # Kiểm tra nhanh nếu đang ở trang gemini và ô nhập chat đã hiển thị
            if self.page.url and "gemini.google.com" in self.page.url:
                textbox = self.page.locator("div[role='textbox'], [contenteditable='true']").first
                if await textbox.is_visible(timeout=1000):
                    logger.info("Đã đăng nhập thành công (xác nhận nhanh).")
                    self.status = "idle"
                    return True
                    
            await self.page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
            await asyncio.sleep(2)
            
            # Kiểm tra xem có ô nhập chat (textbox) hay không
            textbox = self.page.locator("div[role='textbox'], [contenteditable='true']").first
            is_logged_in = await textbox.is_visible()
            
            if is_logged_in:
                logger.info("Đã đăng nhập thành công.")
                self.status = "idle"
                return True
            else:
                logger.warning("Chưa đăng nhập Google.")
                self.status = "waiting_login"
                return False
        except Exception as e:
            logger.error(f"Lỗi kiểm tra đăng nhập: {e}")
            self.status = "waiting_login"
            return False
    async def start_login_session(self):
        """Mở cửa sổ Chrome để người dùng đăng nhập thủ công."""
        await self.initialize()
        self.status = "waiting_login"
        if not self.page:
            logger.error("Không thể khởi tạo trang trình duyệt để bắt đầu đăng nhập.")
            return
        try:
            await self.page.goto("https://gemini.google.com/app")
        except Exception as e:
            logger.error(f"Không thể mở trang Gemini: {e}")

    async def switch_account(self):
        """Đăng xuất tài khoản Google hiện tại và chuyển sang màn hình đăng nhập tài khoản Gemini mới."""
        await self.initialize()
        self.status = "waiting_login"
        if self.page:
            try:
                logger.info("Đang tiến hành đăng xuất tài khoản Google hiện tại...")
                await self.page.goto("https://accounts.google.com/Logout")
                await asyncio.sleep(2)
                await self.page.goto("https://accounts.google.com/ServiceLogin?continue=https://gemini.google.com/app")
                logger.info("Đã mở trang đăng nhập tài khoản Google/Gemini mới.")
            except Exception as e:
                logger.error(f"Lỗi khi thực hiện đăng xuất/chuyển tài khoản: {e}")

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

    async def delete_task(self, task_id: str) -> bool:
        """Xóa một nhiệm vụ khỏi hàng đợi. Nếu đang chạy, hủy bỏ nó."""
        task = self.get_task(task_id)
        if not task:
            return False
            
        # Nếu nhiệm vụ đang chạy, hủy tiến trình
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
            
        # Xóa khỏi hàng đợi
        self.queue = [t for t in self.queue if t["id"] != task_id]
        self._save_queue()
        logger.info(f"Đã xóa nhiệm vụ {task_id} khỏi hàng đợi.")
        
        # Nếu trạng thái là running nhưng bị ngắt, khởi động lại vòng lặp cho các nhiệm vụ tiếp theo
        if self.status == "running" and not self.loop_task:
            self.status = "idle"  # reset để start_queue_processing có thể chạy lại
            await self.start_queue_processing()
            
        return True

    async def retry_task(self, task_id: str) -> bool:
        """Chạy lại một nhiệm vụ (đổi trạng thái về pending)."""
        task = self.get_task(task_id)
        if not task:
            return False
            
        # Chỉ chạy lại nếu không phải đang chạy
        if self.current_task_id == task_id or task["status"] in ["processing", "generating", "uploading"]:
            logger.warning(f"Không thể chạy lại nhiệm vụ đang hoạt động: {task_id}")
            return False
            
        task["status"] = "pending"
        task["progress"] = 0
        task["error"] = None
        task["output_video"] = None
        self._save_queue()
        logger.info(f"Đã đưa nhiệm vụ {task_id} về trạng thái chờ xử lý.")
        
        # Nếu vòng lặp đang nghỉ (idle/paused), kích hoạt chạy lại
        if self.status in ["idle", "paused"]:
            if self.status == "paused":
                self.status = "idle"
            await self.start_queue_processing()
            
        return True

    def edit_task(self, task_id: str, user_description: str, duration: int, ratio: str) -> bool:
        """Chỉnh sửa thông tin nhiệm vụ khi còn ở trạng thái pending hoặc failed."""
        task = self.get_task(task_id)
        if not task:
            return False
            
        # Không cho sửa nhiệm vụ đang chạy
        if self.current_task_id == task_id or task["status"] in ["processing", "generating", "uploading"]:
            logger.warning(f"Không thể sửa nhiệm vụ đang hoạt động: {task_id}")
            return False
            
        task["user_description"] = user_description
        task["duration"] = duration
        task["ratio"] = ratio
        self._save_queue()
        logger.info(f"Đã cập nhật thông tin nhiệm vụ {task_id}.")
        return True

    async def start_queue_processing(self):
        """Bắt đầu chạy vòng lặp xử lý hàng đợi nhiệm vụ."""
        if self.status == "running":
            return
            
        # Kiểm tra đăng nhập trước khi chạy
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
            # Tìm nhiệm vụ đầu tiên có trạng thái pending
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
                
            await asyncio.sleep(2)

    async def _execute_task(self, task: dict[str, Any]):
        """Thực thi một nhiệm vụ tạo video chi tiết."""
        logger.info(f"Bắt đầu thực thi nhiệm vụ {task['id']}")
        self.update_task(task, status="optimizing", progress=5)
        
        # 1. Chuẩn bị đường dẫn hình ảnh tuyệt đối
        abs_image_paths = [UPLOAD_DIR / filename for filename in task["images"]]
        
        # 2. Chạy Smart Prompt Optimizer
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
            caption = opt_res.get("caption", "")
            hashtags = opt_res.get("hashtags", "")
        else:
            optimized = str(opt_res)
            caption = ""
            hashtags = ""

        self.update_task(task, optimized_prompt=optimized, caption=caption, hashtags=hashtags, progress=10)

        # 3. Tính toán số lượng clip cần sinh dựa trên thời lượng
        # Mỗi clip mặc định dài CLIP_DURATION giây, đảm bảo tối thiểu là 1 clip
        num_cycles = max(1, task["duration"] // CLIP_DURATION)
        logger.info(f"Nhiệm vụ {task['id']} yêu cầu thời lượng {task['duration']}s. CLIP_DURATION = {CLIP_DURATION}s. Số lượng clip cần sinh: {num_cycles}")
        generated_clips: list[Path] = []
        
        # Thư mục tạm chứa các clip đơn lẻ
        temp_dir = UPLOAD_DIR / f"temp_{task['id']}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            for cycle in range(num_cycles):
                # Phân bổ progress từ 10% đến 85%
                progress_step = 10 + int((cycle / num_cycles) * 75)
                self.update_task(task, status=f"uploading (cycle {cycle + 1}/{num_cycles})", progress=progress_step)
                
                # Xác định ảnh cần tải lên cho chu kỳ này
                if cycle == 0:
                    # Chu kỳ đầu: tải lên tất cả các ảnh gốc của task
                    cycle_images = abs_image_paths
                else:
                    # Các chu kỳ sau: trích xuất last frame từ clip trước đó
                    last_clip = generated_clips[-1]
                    last_frame_path = temp_dir / f"last_frame_cycle_{cycle}.jpg"
                    
                    self.update_task(task, status=f"extracting last frame (cycle {cycle + 1}/{num_cycles})")
                    success = await asyncio.to_thread(
                        video_processor.extract_last_frame, last_clip, last_frame_path
                    )
                    if not success or not last_frame_path.exists():
                        raise Exception("Không thể trích xuất khung hình cuối từ clip trước.")
                    
                    cycle_images = [last_frame_path]
                
                # Bắt đầu tự động hóa browser cho clip hiện tại
                clip_path = temp_dir / f"clip_{cycle}.mp4"
                
                # Sử dụng prompt tối ưu ở vòng 1. Ở các vòng sau, sử dụng prompt bổ trợ chuyển động mượt mà kết hợp ngữ cảnh câu chuyện gốc
                if cycle == 0:
                    prompt_to_send = task["optimized_prompt"]
                else:
                    prompt_to_send = (
                        f"Please continue the animation of this scene based on this original narrative: '{task['optimized_prompt']}'. "
                        "Keep the motion smooth and natural, continuing the action directly from this image. "
                        "Maintain the style, details, camera movement direction, and lighting from the image."
                    )
                
                await self._automate_browser_for_clip(cycle_images, prompt_to_send, clip_path, task)
                generated_clips.append(clip_path)

            # 4. Ghép nối các clip đã sinh bằng FFmpeg
            self.update_task(task, status="stitching videos", progress=90)
            
            output_filename = f"video_{task['id']}.mp4"
            final_output_path = OUTPUT_DIR / output_filename
            
            if len(generated_clips) == 1:
                # 1 clip duy nhất: chỉ cần copy sang thư mục output
                import shutil
                await asyncio.to_thread(shutil.copy2, generated_clips[0], final_output_path)
            else:
                # Nhiều clips: ghép nối dựa theo cài đặt long_video_mode
                if self.long_video_mode == "last_frame":
                    # Nối trực tiếp không hiệu ứng vì các clip đã khớp khung hình cuối - đầu
                    success = await asyncio.to_thread(
                        video_processor.concatenate_videos_direct, generated_clips, final_output_path
                    )
                else:
                    # Nối có hiệu ứng xfade mờ chồng
                    success = await asyncio.to_thread(
                        video_processor.concatenate_videos_xfade, generated_clips, final_output_path, 0.5
                    )
                
                if not success or not final_output_path.exists():
                    raise Exception("Lỗi khi ghép nối các đoạn video ngắn thành video tổng hợp.")

            # 5. Lưu trữ tệp thông tin JSON và TXT đính kèm theo video
            meta_json_path = OUTPUT_DIR / f"video_{task['id']}.json"
            meta_txt_path = OUTPUT_DIR / f"video_{task['id']}.txt"
            
            from datetime import datetime
            import json
            from backend.services.prompt_optimizer import parse_prompt_response
            
            caption_val = task.get("caption", "")
            hashtags_val = task.get("hashtags", "")
            prompt_val = task.get("optimized_prompt", "")
            
            # Nếu vì lý do nào đó caption/hashtags chưa được trích xuất, thử phân tách dự phòng
            if not caption_val or not hashtags_val:
                fallback_parsed = parse_prompt_response(prompt_val)
                if fallback_parsed.get("caption"):
                    caption_val = fallback_parsed["caption"]
                    task["caption"] = caption_val
                if fallback_parsed.get("hashtags"):
                    hashtags_val = fallback_parsed["hashtags"]
                    task["hashtags"] = hashtags_val
                if fallback_parsed.get("prompt"):
                    prompt_val = fallback_parsed["prompt"]
                    task["optimized_prompt"] = prompt_val
            
            meta_data = {
                "video_filename": output_filename,
                "prompt": prompt_val,
                "caption": caption_val,
                "hashtags": hashtags_val,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            with open(meta_json_path, "w", encoding="utf-8") as f:
                json.dump(meta_data, f, ensure_ascii=False, indent=2)
                
            txt_content = f"--- BÀI ĐĂNG CAPTION ---\n{caption_val}\n\n--- HASHTAGS ---\n{hashtags_val}\n\n--- PROMPT VIDEO ---\n{prompt_val}"
            with open(meta_txt_path, "w", encoding="utf-8") as f:
                f.write(txt_content)

            # Hoàn tất nhiệm vụ
            self.update_task(task, status="completed", progress=100, output_video=output_filename)
            logger.info(f"Đã hoàn thành nhiệm vụ {task['id']}. Video kết quả: {final_output_path}")

        except Exception as e:
            logger.error(f"Lỗi trong quá trình tạo video cho task {task['id']}: {e}")
            self.update_task(task, status="failed", error=str(e))
            raise e
        finally:
            # Xóa thư mục tạm thời chứa các clip đơn lẻ
            try:
                import shutil
                if temp_dir.exists():
                    await asyncio.to_thread(shutil.rmtree, temp_dir)
            except Exception as e:
                logger.error(f"Không thể xóa thư mục tạm {temp_dir}: {e}")

    async def _automate_browser_for_clip(self, image_paths: list[Path], prompt: str, output_path: Path, task: dict[str, Any]):
        """Điều khiển Playwright nạp ảnh, chọn khung dọc 9:16, gửi prompt và tải video."""
        if not self.page:
            raise Exception("Trình duyệt chưa được khởi tạo.")

        # 1. Điều hướng và reset khung chat
        logger.info("Điều hướng đến Gemini...")
        await self.page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # 1.5 Nếu prompt là Meta-Prompt (dùng Web UI để tối ưu prompt), thực hiện tối ưu qua Chat trước
        is_meta_prompt = (not self.api_key or self.prompt_mode == "meta") and "Please continue" not in prompt
        if is_meta_prompt:
            logger.info("Chế độ Web UI: Đang tối ưu hóa prompt qua Chat Gemini trước...")
            self.update_task(task, status="generating optimized prompt via chat")
            
            # Click nút Plus để mở menu trong Chat
            plus_button = self.page.locator(
                "button[aria-label*='upload' i], button[aria-label*='tải' i], button[aria-label*='thêm' i], button[aria-label*='add' i]"
            ).locator("visible=true").first
            await plus_button.click(force=True)
            await asyncio.sleep(1.5)
            
            # Chọn 'Tải tệp lên' và nạp ảnh tự động (hỗ trợ cả giao diện mới và cũ)
            upload_option = self.page.locator(
                "button[role*='menuitem']:has-text('Tải lên từ máy tính'), button[role*='menuitem']:has-text('Upload from computer'), button[role*='menuitem']:has-text('Upload from this device'), button[role*='menuitem']:has-text('Tải tệp lên'), button[role*='menuitem']:has-text('Upload file'), "
                "button[role*='menuitem']:has-text('Tải lên'), button[role*='menuitem']:has-text('Upload'), "
                ".gem-menu-item-label:has-text('Tải lên từ máy tính'), .gem-menu-item-label:has-text('Upload from computer'), .gem-menu-item-label:has-text('Upload from this device'), .gem-menu-item-label:has-text('Tải tệp lên'), .gem-menu-item-label:has-text('Upload file'), "
                "button:has-text('Tải lên từ máy tính'), button:has-text('Upload from computer'), button:has-text('Upload from this device'), button:has-text('Tải tệp lên'), button:has-text('Upload file'), "
                "button:has-text('Tải lên'), button:has-text('Upload'), "
                "[role*='menu'] button:has-text('Tải lên từ máy tính'), [role*='menu'] button:has-text('Upload from computer'), [role*='menu'] button:has-text('Upload from this device'), [role*='menu'] button:has-text('Tải tệp lên'), [role*='menu'] button:has-text('Upload file'), "
                "[role*='menu'] span:has-text('Tải lên từ máy tính'), [role*='menu'] span:has-text('Upload from computer'), [role*='menu'] span:has-text('Upload from this device'), [role*='menu'] span:has-text('Tải tệp lên'), [role*='menu'] span:has-text('Upload file')"
            ).locator("visible=true").first
            
            str_paths = [str(p.resolve()) for p in image_paths]
            async with self.page.expect_file_chooser() as fc_info:
                await upload_option.click(force=True)
            file_chooser = await fc_info.value
            await file_chooser.set_files(str_paths)
            await asyncio.sleep(3)  # Chờ ảnh load lên
            
            # Điền Meta-Prompt vào Chat thường
            chat_input = self.page.locator("div[role='textbox'], [contenteditable='true']").first
            await chat_input.focus()
            await chat_input.fill(prompt)
            await asyncio.sleep(1)
            await chat_input.press("Enter")
            
            logger.info("Đã gửi Meta-Prompt. Đang chờ Gemini sinh prompt tối ưu (chờ ít nhất 20 giây)...")
            await asyncio.sleep(20)  # Chờ ít nhất 20 giây để AI hoàn tất sinh prompt
            
            # Chờ tiếp thêm một chút nếu văn bản vẫn đang thay đổi
            last_text = ""
            for _ in range(15):  # Kiểm tra thêm tối đa 15 giây
                try:
                    text = await self.page.locator("message-content").last.inner_text()
                    if len(text.strip()) > 0 and text == last_text:
                        break
                    last_text = text
                except Exception:
                    pass
                await asyncio.sleep(1)
            
            # Trích xuất prompt tối ưu từ câu trả lời của Gemini
            from backend.services.prompt_optimizer import parse_prompt_response
            parsed_dict = parse_prompt_response(last_text)
            optimized_prompt = parsed_dict.get("prompt", "").strip()
            
            if not optimized_prompt:
                logger.warning("Không thể lấy prompt tối ưu từ Chat. Dùng prompt mặc định.")
                optimized_prompt = f"A video of a product based on: {task['user_description']}"
                
            logger.info(f"Đã nhận prompt tối ưu từ Chat: {optimized_prompt}")
            prompt = optimized_prompt
            task["optimized_prompt"] = optimized_prompt
            if parsed_dict.get("caption"):
                task["caption"] = parsed_dict["caption"]
            if parsed_dict.get("hashtags"):
                task["hashtags"] = parsed_dict["hashtags"]
            
            # Điều hướng lại trang chính để làm sạch khung chat trước khi vào Tạo video
            logger.info("Làm sạch khung chat và bắt đầu bước tạo video...")
            await self.page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
            await asyncio.sleep(2)

        # 2. Click nút Plus (+) Menu tải lên
        logger.info("Đang click vào Menu tải lên...")
        # Tìm nút plus hoặc paperclip (chỉ chọn các nút có nhãn tải lên/thêm/add/upload và đang hiển thị)
        plus_button = self.page.locator(
            "button[aria-label*='upload' i], button[aria-label*='tải' i], button[aria-label*='thêm' i], button[aria-label*='add' i]"
        ).locator("visible=true").first
        
        if not await plus_button.is_visible():
            # Fallback nếu không tìm thấy qua label
            plus_button = self.page.locator(
                ".simplified-input-menu-container button, .leading-actions-wrapper button, [class*='input-menu'] button"
            ).locator("visible=true").first
            
        await plus_button.click(force=True)
        await asyncio.sleep(1.5)

        # 3. Chọn "Tạo video" (hoặc "Create video")
        logger.info("Đang chọn chế độ 'Tạo video'...")
        selector = (
            "toolbox-drawer-item:has-text('Tạo video'), "
            "toolbox-drawer-item:has-text('Create video'), "
            ".gem-menu-item-label:has-text('Tạo video'), "
            ".gem-menu-item-label:has-text('Create video'), "
            "button[role='menuitemcheckbox']:has-text('Tạo video'), "
            "button[role='menuitemcheckbox']:has-text('Create video')"
        )
        video_menu_item = self.page.locator(selector).first
        if not await video_menu_item.is_visible():
            raise Exception("Không tìm thấy mục 'Tạo video' trong menu tải lên của Gemini.")
        await video_menu_item.click(force=True)
        await asyncio.sleep(2.5)

        # 3.5 Bỏ qua modal giới thiệu "Dùng thử" nếu có
        try:
            try_button = self.page.locator(
                "button:has-text('Dùng thử'), button:has-text('Try'), button:has-text('Get started'), button:has-text('Dùng thử ngay')"
            ).first
            if await try_button.is_visible(timeout=2000):
                logger.info("Phát hiện modal giới thiệu 'Dùng thử'. Đang click để bỏ qua...")
                await try_button.click(force=True)
                await asyncio.sleep(1.5)
        except Exception as e:
            logger.info(f"Không xuất hiện modal giới thiệu hoặc có lỗi khi bỏ qua: {e}")

        # 4. Thiết lập tỷ lệ khung hình (Aspect Ratio)
        target_ratio = task.get("ratio", "9:16")
        logger.info(f"Đang thiết lập tỷ lệ khung hình: {target_ratio}...")
        
        # Tìm dropdown chọn tỷ lệ
        ratio_button = self.page.locator(
            "button:has-text('16:9'), button:has-text('9:16'), "
            "button:has-text('ngang'), button:has-text('dọc'), "
            "[role='button']:has-text('16:9'), [role='button']:has-text('9:16'), "
            "[role='combobox']:has-text('16:9'), [role='combobox']:has-text('9:16'), "
            "*[role='button']:has-text('ngang'), *[role='button']:has-text('dọc')"
        ).locator("visible=true").first
        
        if await ratio_button.is_visible():
            current_text = await ratio_button.inner_text()
            current_text_lower = current_text.lower()
            
            # Kiểm tra xem tỷ lệ hiện tại đã khớp chưa để tránh click thừa
            already_correct = False
            if target_ratio == "16:9" and ("16:9" in current_text_lower or "ngang" in current_text_lower or "landscape" in current_text_lower):
                already_correct = True
            elif target_ratio == "9:16" and ("9:16" in current_text_lower or "dọc" in current_text_lower or "portrait" in current_text_lower):
                already_correct = True
                
            if already_correct:
                logger.info(f"Tỷ lệ khung hình đã sẵn sàng ở chế độ {target_ratio}. Không cần chỉnh sửa.")
            else:
                logger.info(f"Thay đổi tỷ lệ từ '{current_text}' sang '{target_ratio}'...")
                await ratio_button.click(force=True)
                await asyncio.sleep(1.5)
                
                # Chọn tùy chọn tương ứng trong menu popup bằng danh sách các selector ưu tiên từ cụ thể tới bao quát
                found_option = False
                if target_ratio == "9:16":
                    selectors = [
                        "span:has-text('Dọc (9:16)')",
                        "span:has-text('Portrait (9:16)')",
                        "[role*='menuitem'] span:has-text('9:16')",
                        "[role*='menuitem']:has-text('9:16')",
                        "[role*='option'] span:has-text('9:16')",
                        "[role*='option']:has-text('9:16')",
                        "span:has-text('Dọc')",
                        "span:has-text('Portrait')",
                        "button:has-text('9:16')",
                    ]
                    text_vals = ["Dọc (9:16)", "Portrait (9:16)", "9:16", "Dọc", "Portrait"]
                else:
                    selectors = [
                        "span:has-text('Ngang (16:9)')",
                        "span:has-text('Landscape (16:9)')",
                        "[role*='menuitem'] span:has-text('16:9')",
                        "[role*='menuitem']:has-text('16:9')",
                        "[role*='option'] span:has-text('16:9')",
                        "[role*='option']:has-text('16:9')",
                        "span:has-text('Ngang')",
                        "span:has-text('Landscape')",
                        "button:has-text('16:9')",
                    ]
                    text_vals = ["Ngang (16:9)", "Landscape (16:9)", "16:9", "Ngang", "Landscape"]
                
                # Thử tìm bằng các selector cụ thể trước
                for sel in selectors:
                    opt = self.page.locator(sel).locator("visible=true").first
                    if await opt.is_visible():
                        logger.info(f"Tìm thấy tùy chọn tỷ lệ bằng selector: {sel}")
                        await opt.click(force=True)
                        found_option = True
                        break
                        
                # Nếu không tìm thấy, thử bằng get_by_text (xác định chuẩn text node, tránh click nhầm thẻ div bọc ngoài của popup)
                if not found_option:
                    for text_val in text_vals:
                        opt = self.page.get_by_text(text_val).locator("visible=true").first
                        if await opt.is_visible():
                            logger.info(f"Tìm thấy tùy chọn tỷ lệ bằng get_by_text: {text_val}")
                            await opt.click(force=True)
                            found_option = True
                            break
                            
                if found_option:
                    await asyncio.sleep(1.5)
                    logger.info(f"Đã chuyển tỷ lệ sang: {target_ratio}")
                else:
                    logger.warning(f"Không tìm thấy tùy chọn '{target_ratio}' trong dropdown menu.")
        else:
            logger.warning("Không tìm thấy nút chỉnh tỷ lệ khung hình video trên giao diện Gemini.")

        # 5. Tải ảnh lên
        logger.info(f"Đang tải {len(image_paths)} hình ảnh lên...")
        self.update_task(task, status="uploading images to Gemini")
        
        str_paths = [str(p.resolve()) for p in image_paths]
        
        try:
            # Click nút Plus ở ô nhập liệu của chế độ tạo video để xem menu hiện ra hay mở thẳng hộp thoại chọn file
            plus_input_area = self.page.locator(
                "button[aria-label*='upload' i], button[aria-label*='tải' i], button[aria-label*='thêm' i], button[aria-label*='add' i]"
            ).locator("visible=true").first
            
            await plus_input_area.click(force=True)
            await asyncio.sleep(1.5)
            
            # Tìm xem có menu tải lên phụ hay không
            upload_option = self.page.locator(
                "button[role*='menuitem']:has-text('Tải lên từ máy tính'), button[role*='menuitem']:has-text('Upload from computer'), button[role*='menuitem']:has-text('Upload from this device'), button[role*='menuitem']:has-text('Tải tệp lên'), button[role*='menuitem']:has-text('Upload file'), "
                "button[role*='menuitem']:has-text('Tải lên'), button[role*='menuitem']:has-text('Upload'), "
                ".gem-menu-item-label:has-text('Tải lên từ máy tính'), .gem-menu-item-label:has-text('Upload from computer'), .gem-menu-item-label:has-text('Upload from this device'), .gem-menu-item-label:has-text('Tải tệp lên'), .gem-menu-item-label:has-text('Upload file'), "
                "button:has-text('Tải lên từ máy tính'), button:has-text('Upload from computer'), button:has-text('Upload from this device'), button:has-text('Tải tệp lên'), button:has-text('Upload file'), "
                "button:has-text('Tải lên'), button:has-text('Upload'), "
                "[role*='menu'] button:has-text('Tải lên từ máy tính'), [role*='menu'] button:has-text('Upload from computer'), [role*='menu'] button:has-text('Upload from this device'), [role*='menu'] button:has-text('Tải tệp lên'), [role*='menu'] button:has-text('Upload file'), "
                "[role*='menu'] span:has-text('Tải lên từ máy tính'), [role*='menu'] span:has-text('Upload from computer'), [role*='menu'] span:has-text('Upload from this device'), [role*='menu'] span:has-text('Tải tệp lên'), [role*='menu'] span:has-text('Upload file')"
            ).locator("visible=true").first
            
            if await upload_option.is_visible(timeout=3000):
                logger.info("Phát hiện menu thả xuống. Đang chọn mục tải file lên...")
                async with self.page.expect_file_chooser() as fc_info:
                    await upload_option.click(force=True)
                file_chooser = await fc_info.value
                await file_chooser.set_files(str_paths)
            else:
                raise Exception("Không tìm thấy menu phụ.")
                
        except Exception as e:
            logger.info(f"Không xuất hiện menu phụ hoặc lỗi ({e}). Tiến hành click trực tiếp nút Plus để nạp file...")
            plus_input_area = self.page.locator(
                "button[aria-label*='upload' i], button[aria-label*='tải' i], button[aria-label*='thêm' i], button[aria-label*='add' i]"
            ).locator("visible=true").first
            
            async with self.page.expect_file_chooser() as fc_info:
                await plus_input_area.click(force=True)
            file_chooser = await fc_info.value
            await file_chooser.set_files(str_paths)
            
        await asyncio.sleep(4)  # Chờ ảnh tải lên trình duyệt

        # 6. Nhập prompt và gửi
        logger.info("Đang điền prompt tạo video...")
        self.update_task(task, status="submitting prompt")
        
        # Tìm ô nhập liệu của tính năng Tạo video (có placeholder Mô tả video)
        prompt_input = self.page.locator(
            "div[role='textbox'][data-placeholder*='video' i], .ql-editor[data-placeholder*='video' i], div[role='textbox'][aria-label*='Gemini' i]"
        ).first
        
        if not await prompt_input.is_visible():
            raise Exception("Không tìm thấy ô nhập mô tả video trên giao diện.")
            
        await prompt_input.focus()
        await prompt_input.fill(prompt)
        await asyncio.sleep(1)
        
        # Nhấn Enter để gửi đi
        await prompt_input.press("Enter")
        logger.info("Đã gửi prompt lên Gemini. Đang chờ render video...")
        
        # 7. Chờ video được sinh ra
        self.update_task(task, status="generating video (waiting 1-3 mins)")
        
        # Đếm số video ban đầu trên trang để phân biệt video mới
        initial_video_count = await self.page.locator("video").count()
        
        # Đợi thẻ video xuất hiện
        # Chờ tối đa 180 giây (3 phút)
        video_found = False
        for sec in range(180):
            current_video_count = await self.page.locator("video").count()
            if current_video_count > initial_video_count:
                video_found = True
                break
            await asyncio.sleep(1.5)
            
        if not video_found:
            raise Exception("Quá thời gian chờ (3 phút) nhưng Gemini vẫn chưa tạo ra video.")

        # 8. Trích xuất link video src và Tải về bằng JS fetch
        logger.info("Đã phát hiện video mới. Đang chuẩn bị tải về...")
        self.update_task(task, status="downloading generated video")
        
        video_element = self.page.locator("video").last
        video_src = ""
        
        # Chờ src attribute của video load đầy đủ
        for _ in range(30):
            video_src = await video_element.get_attribute("src") or ""
            if video_src.startswith("http") or video_src.startswith("blob"):
                break
            await asyncio.sleep(1)
            
        if not video_src:
            raise Exception("Thẻ video không chứa đường dẫn src hợp lệ.")

        logger.info(f"Đường dẫn video phát hiện: {video_src[:60]}...")
        
        # Thực hiện tải video qua JS fetch (nếu là blob) hoặc qua APIRequestContext (nếu là http/https)
        try:
            if video_src.startswith("blob:"):
                logger.info("Phát hiện video dạng blob. Đang tải qua JS evaluate...")
                base64_data = await self.page.evaluate("""async (url) => {
                    const res = await fetch(url);
                    const blob = await res.blob();
                    return new Promise((resolve, reject) => {
                        const reader = new FileReader();
                        reader.onloadend = () => resolve(reader.result.split(',')[1]);
                        reader.onerror = reject;
                        reader.readAsDataURL(blob);
                    });
                }""", video_src)
                video_bytes = base64.b64decode(base64_data)
            else:
                logger.info("Phát hiện video dạng HTTP/HTTPS. Đang tải qua Playwright request context...")
                response = await self.page.request.get(video_src)
                if not response.ok:
                    raise Exception(f"Tải video thất bại với status code: {response.status} {response.status_text}")
                video_bytes = await response.body()
                
            with open(output_path, "wb") as f:
                f.write(video_bytes)
                
            logger.info(f"Đã lưu video thành công vào: {output_path}")
            
        except Exception as e:
            logger.error(f"Lỗi khi thực thi tải video: {e}")
            raise Exception(f"Không thể tải video từ trình duyệt: {str(e)}")
