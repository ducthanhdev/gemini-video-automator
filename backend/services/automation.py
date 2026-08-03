import asyncio
import base64
import logging
import uuid
from pathlib import Path
from typing import Any
from playwright.async_api import async_playwright
from backend.config import PROFILE_DIR, UPLOAD_DIR, OUTPUT_DIR, DEFAULT_SYSTEM_INSTRUCTION, DEFAULT_META_PROMPT_TEMPLATE, CLIP_DURATION, QUEUE_FILE, SETTINGS_FILE
from backend.services.prompt_optimizer import optimize_prompt
from backend.services import video_processor
from backend.services.product_parser import ProductParser

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
        self.voice_gender = "hoaimy"  # hoaimy (nữ) hoặc namminh (nam)
        self.enable_voiceover = True

        # Tải cấu hình và hàng đợi đã lưu từ trước
        self._load_settings()
        self._load_queue()

    def _load_settings(self):
        """Tải cấu hình cài đặt từ file settings.json nếu có."""
        import json
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
                self.enable_voiceover = data.get("enable_voiceover", True)
                logger.info("Đã tải cấu hình cài đặt từ file settings.json.")
            else:
                self._save_settings()
        except Exception as e:
            logger.error(f"Lỗi khi tải cấu hình cài đặt từ file: {e}")

    def _save_settings(self):
        """Lưu cấu hình cài đặt vào file settings.json."""
        import json
        try:
            data = {
                "api_key": self.api_key,
                "prompt_mode": self.prompt_mode,
                "long_video_mode": self.long_video_mode,
                "system_instruction": self.system_instruction,
                "meta_prompt_template": self.meta_prompt_template,
                "voice_gender": getattr(self, "voice_gender", "hoaimy"),
                "enable_voiceover": getattr(self, "enable_voiceover", True)
            }
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            logger.info("Đã lưu cấu hình cài đặt vào file settings.json.")
        except Exception as e:
            logger.error(f"Lỗi khi lưu cấu hình cài đặt vào file: {e}")

    def _load_queue(self):
        """Tải hàng đợi từ file queue.json nếu có."""
        import json
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
            
            # Khởi chạy Persistent Context sử dụng Chrome của hệ thống kèm cờ mở rộng tối đa màn hình
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                channel="chrome",
                headless=False,  # Bắt buộc headless=False để người dùng đăng nhập
                viewport=None,
                no_viewport=True,
                ignore_default_args=["--enable-automation"],
                args=[
                    "--start-maximized",
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
            
            # Đã nạp danh sách hàng đợi, không tự động chạy cho đến khi người dùng yêu cầu (bấm nút Khởi chạy)
            has_pending = any(t.get("status") == "pending" for t in self.queue)
            if has_pending:
                logger.info("Đã tải các nhiệm vụ đang chờ trong hàng đợi. Chờ người dùng nhấn Khởi chạy.")
            
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
            logger.error(f"Lỗi khi đóng trình duyệt: {e}")
        finally:
            self.context = None
            self.playwright = None
            self.page = None
            self.status = "idle"

    async def parse_product_url_with_browser(self, url: str) -> dict:
        """Sử dụng trình duyệt Chrome đang chạy để mở link sản phẩm và bóc tách dữ liệu DOM chi tiết dưới phần About this product."""
        if not self.context:
            return ProductParser.parse_product_url(url, api_key=self.api_key)

        page = self.page
        opened_new_page = False
        if not page or page.is_closed():
            page = await self.context.new_page()
            opened_new_page = True

        try:
            logger.info(f"Đang mở link sản phẩm mới trên Chrome: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            
            # Tạm dừng 5 giây theo yêu cầu để người dùng có thời gian giải Captcha trên Chrome nếu bị Security Check
            logger.info("Tạm dừng 5 giây chờ trang tải hoàn tất và cho phép giải Captcha trên Chrome...")
            await asyncio.sleep(5)

            # Nếu đang ở màn hình Security Check, tiếp tục chờ thêm tối đa 20s cho người dùng giải Captcha trên Chrome
            start_wait_time = asyncio.get_running_loop().time()
            title = await page.title()
            while title and ("Security Check" in title or "Verify to continue" in title) and (asyncio.get_running_loop().time() - start_wait_time) < 20:
                logger.info("Phát hiện màn hình Security Check. Đang chờ người dùng kéo mảnh ghép Captcha trên Chrome...")
                await asyncio.sleep(2)
                try:
                    title = await page.title()
                except Exception:
                    pass

            extracted_desc = ""
            image_urls = []

            for retry in range(3):
                try:
                    # Cuộn trang xuống để kích hoạt lazy loading phần Mô tả sản phẩm (About this product)
                    await page.evaluate("window.scrollTo(0, 800)")
                    await asyncio.sleep(1)

                    # Trích xuất phần mô tả chính xác giữa marker BẮT ĐẦU và KẾT THÚC
                    extracted_desc = await page.evaluate('''() => {
                        const fullBody = document.body ? document.body.innerText : '';
                        const startMarkers = [
                            'Thông tin về sản phẩm này',
                            'About this product',
                            'Mô tả sản phẩm',
                            'Product description',
                            'Product Details'
                        ];
                        const endMarkers = [
                            'Khám phá thêm sản phẩm từ',
                            'Bạn cũng có thể thích',
                            'Đánh giá của khách hàng',
                            'Recommended',
                            'Customers also liked',
                            'Khám phá thêm',
                            'Reviews',
                            'TikTok Shop',
                            'Cửa hàng',
                            'Tận hưởng trải nghiệm',
                            'Hỗ trợ khách hàng'
                        ];

                        let startPos = -1;
                        for (const sm of startMarkers) {
                            const p = fullBody.indexOf(sm);
                            if (p !== -1) {
                                startPos = p;
                                break;
                            }
                        }

                        if (startPos !== -1) {
                            const sub = fullBody.substring(startPos);
                            let endPos = sub.length;
                            for (const em of endMarkers) {
                                const p = sub.indexOf(em);
                                if (p !== -1 && p > 50) {
                                    if (p < endPos) endPos = p;
                                }
                            }
                            const sliced = sub.substring(0, endPos).trim();
                            if (sliced.length > 30) return sliced;
                        }

                        return '';
                    }''')

                    # Trích xuất URL hình ảnh từ DOM
                    image_urls = await page.evaluate('''() => {
                        const imgs = Array.from(document.querySelectorAll('img'));
                        const srcList = [];
                        for (const img of imgs) {
                            const src = img.src || img.getAttribute('data-src');
                            if (src && (src.includes('ibyteimg') || src.includes('tiktok') || src.includes('product')) && !src.includes('avatar') && !src.includes('logo')) {
                                if (!srcList.includes(src)) srcList.push(src);
                            }
                        }
                        return srcList;
                    }''')

                    if extracted_desc and len(extracted_desc) > 30:
                        logger.info(f"Đã trích xuất thành công {len(extracted_desc)} ký tự ở lần thử {retry+1}!")
                        break

                except Exception as eval_err:
                    logger.warning(f"Lần thử {retry+1} bị gián đoạn (trang đang chuyển hướng): {eval_err}")
                    await asyncio.sleep(2)

            if opened_new_page and page and not page.is_closed():
                await page.close()

            logger.info(f"Kết quả trích xuất DOM: {len(extracted_desc)} ký tự. Tiêu đề: {title}")

            if extracted_desc and len(extracted_desc) > 30 and "Security Check" not in extracted_desc:
                saved_images = []
                for img_url in image_urls[:3]:
                    fn = ProductParser._download_image(img_url)
                    if fn:
                        saved_images.append(fn)

                clean_title = title.replace(" - TikTok Shop", "").replace("TikTok Shop", "").strip()
                full_text = f"{clean_title}\n\n{extracted_desc}"

                return {
                    "title": clean_title,
                    "description": extracted_desc,
                    "full_text": full_text,
                    "images": saved_images,
                    "raw_image_urls": image_urls
                }

        except Exception as e:
            logger.warning(f"Lỗi khi dùng Chrome bóc tách DOM: {e}")
            if page and not page.is_closed():
                try:
                    await page.close()
                except Exception:
                    pass

        return ProductParser.parse_product_url(url, api_key=self.api_key)

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
            logger.info("Đang điều hướng đến trang Đăng nhập Google...")
            await self.page.goto("https://accounts.google.com/ServiceLogin?continue=https://gemini.google.com/app", wait_until="domcontentloaded")
        except Exception as e:
            logger.error(f"Không thể mở trang đăng nhập Google: {e}")

    async def switch_account(self):
        """Đăng xuất tài khoản Google hiện tại và xóa sạch session để đăng nhập tài khoản Gemini mới."""
        logger.info("Đang đăng xuất và xóa sạch session tài khoản Google hiện tại...")
        await self.shutdown()
        
        # Xóa sạch toàn bộ thư mục profile để đảm bảo Google không tự động đăng nhập lại tài khoản cũ
        try:
            if PROFILE_DIR.exists():
                import shutil
                shutil.rmtree(PROFILE_DIR, ignore_errors=True)
                PROFILE_DIR.mkdir(parents=True, exist_ok=True)
                logger.info("Đã xóa sạch cache & session tài khoản cũ.")
        except Exception as e:
            logger.warning(f"Không thể xóa thư mục profile: {e}")

        # Khởi tạo lại trình duyệt Chrome mới tinh
        await self.initialize()
        self.status = "waiting_login"
        
        if self.page:
            try:
                logger.info("Đã mở trang Đăng nhập Google cho tài khoản mới.")
                await self.page.goto("https://accounts.google.com/ServiceLogin?continue=https://gemini.google.com/app", wait_until="domcontentloaded")
            except Exception as e:
                logger.error(f"Lỗi khi điều hướng sang trang đăng nhập: {e}")

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

    async def clear_queue(self) -> int:
        """Xóa tất cả các nhiệm vụ khỏi hàng đợi. Nếu có nhiệm vụ đang chạy, dừng tiến trình."""
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

        self.queue = []
        self._save_queue()
        self.status = "idle"
        logger.info(f"Đã xóa toàn bộ {count} nhiệm vụ khỏi hàng đợi.")
        return count

    async def retry_task(self, task_id: str) -> bool:
        """Chạy lại một nhiệm vụ (đổi trạng thái về pending)."""
        task = self.get_task(task_id)
        if not task:
            return False
            
        # Chỉ không cho chạy lại nếu nhiệm vụ đang thực sự chạy trong luồng hiện tại
        if self.current_task_id == task_id:
            logger.warning(f"Không thể chạy lại nhiệm vụ đang thực sự hoạt động: {task_id}")
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
            
        # Không cho sửa nhiệm vụ đang thực sự chạy trong luồng hiện tại
        if self.current_task_id == task_id:
            logger.warning(f"Không thể sửa nhiệm vụ đang thực sự hoạt động: {task_id}")
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
                
            # Chờ 5s để hệ thống lưu trữ tệp hoàn chỉnh xuống ổ đĩa và cập nhật giao diện trước khi sang task tiếp theo
            await asyncio.sleep(5)

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
            voiceover = opt_res.get("voiceover", "")
            caption = opt_res.get("caption", "")
            hashtags = opt_res.get("hashtags", "")
        else:
            optimized = str(opt_res)
            voiceover = ""
            caption = ""
            hashtags = ""

        self.update_task(task, optimized_prompt=optimized, voiceover=voiceover, caption=caption, hashtags=hashtags, progress=10)

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

            # 4.5. Tự động lồng tiếng AI cho video (Nếu được bật và có kịch bản voiceover)
            if getattr(self, "enable_voiceover", True):
                voiceover_text = task.get("voiceover", "")
                if voiceover_text and voiceover_text.strip():
                    self.update_task(task, status="generating AI voiceover audio")
                    logger.info(f"Đang tiến hành tự động lồng tiếng AI cho video (Giọng: {getattr(self, 'voice_gender', 'hoaimy')})...")
                    from backend.services.voiceover import process_video_voiceover
                    voice_key = getattr(self, "voice_gender", "hoaimy")
                    voice_success = await process_video_voiceover(final_output_path, voiceover_text, voice_key=voice_key)
                    if voice_success:
                        logger.info("⚡ Tự động lồng tiếng AI và ghép âm thanh thành công!")
                    else:
                        logger.warning("Lồng tiếng AI không thành công, giữ nguyên video gốc.")

            # 5. Lưu trữ tệp thông tin JSON và TXT đính kèm theo video
            meta_json_path = OUTPUT_DIR / f"video_{task['id']}.json"
            meta_txt_path = OUTPUT_DIR / f"video_{task['id']}.txt"
            
            from datetime import datetime
            import json
            from backend.services.prompt_optimizer import parse_prompt_response
            
            caption_val = task.get("caption", "")
            hashtags_val = task.get("hashtags", "")
            prompt_val = task.get("optimized_prompt", "")
            voiceover_val = task.get("voiceover", "")
            
            # Nếu vì lý do nào đó caption/hashtags chưa được trích xuất, thử phân tách dự phòng
            if not caption_val or not hashtags_val or not voiceover_val:
                fallback_parsed = parse_prompt_response(prompt_val)
                if fallback_parsed.get("caption"):
                    caption_val = fallback_parsed["caption"]
                    task["caption"] = caption_val
                if fallback_parsed.get("hashtags"):
                    hashtags_val = fallback_parsed["hashtags"]
                    task["hashtags"] = hashtags_val
                if fallback_parsed.get("voiceover"):
                    voiceover_val = fallback_parsed["voiceover"]
                    task["voiceover"] = voiceover_val
                if fallback_parsed.get("prompt"):
                    prompt_val = fallback_parsed["prompt"]
                    task["optimized_prompt"] = prompt_val
            
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

    async def _upload_images_to_page(self, image_paths: list[Path], timeout_seconds: int = 90) -> bool:
        """Tải hình ảnh lên trình duyệt Gemini một cách linh hoạt, tránh dính timeout 30s."""
        if not self.page or self.page.is_closed():
            logger.error("Trình duyệt hoặc trang không tồn tại/đã bị đóng trong _upload_images_to_page.")
            return False

        page = self.page

        str_paths = [str(p.resolve()) for p in image_paths if p.exists()]
        if not str_paths:
            logger.warning("Không có tệp ảnh hợp lệ để tải lên.")
            return False

        logger.info(f"Đang tiến hành tải {len(str_paths)} hình ảnh lên...")
        upload_success = False

        # 1. Thử click nút Plus trước để mở menu hoặc kích hoạt file chooser
        plus_button = page.locator(
            "button[aria-label*='upload' i], button[aria-label*='tải' i], button[aria-label*='thêm' i], button[aria-label*='add' i], button[mattooltip*='Upload' i], button[mattooltip*='Tải' i]"
        ).locator("visible=true").first

        try:
            if await plus_button.is_visible(timeout=3000):
                await plus_button.click(force=True)
                await asyncio.sleep(1)
        except Exception as e:
            logger.debug(f"Không thể click nút Plus: {e}")

        # 2. Kiểm tra xem có menu thả xuống hiện ra hay không (timeout ngắn 2.5 giây)
        upload_option = page.locator(
            "button[role*='menuitem']:has-text('Tải lên từ máy tính'), button[role*='menuitem']:has-text('Upload from computer'), button[role*='menuitem']:has-text('Upload from this device'), button[role*='menuitem']:has-text('Tải tệp lên'), button[role*='menuitem']:has-text('Upload file'), "
            "button[role*='menuitem']:has-text('Tải lên'), button[role*='menuitem']:has-text('Upload'), "
            ".gem-menu-item-label:has-text('Tải lên từ máy tính'), .gem-menu-item-label:has-text('Upload from computer'), .gem-menu-item-label:has-text('Upload from this device'), .gem-menu-item-label:has-text('Tải tệp lên'), .gem-menu-item-label:has-text('Upload file'), "
            "button:has-text('Tải lên từ máy tính'), button:has-text('Upload from computer'), button:has-text('Upload from this device'), button:has-text('Tải tệp lên'), button:has-text('Upload file'), "
            "button:has-text('Tải lên'), button:has-text('Upload'), "
            "[role*='menu'] button:has-text('Tải lên từ máy tính'), [role*='menu'] button:has-text('Upload from computer'), [role*='menu'] button:has-text('Upload from this device'), [role*='menu'] button:has-text('Tải tệp lên'), [role*='menu'] button:has-text('Upload file'), "
            "[role*='menu'] span:has-text('Tải lên từ máy tính'), [role*='menu'] span:has-text('Upload from computer'), [role*='menu'] span:has-text('Upload from this device'), [role*='menu'] span:has-text('Tải tệp lên'), [role*='menu'] span:has-text('Upload file')"
        ).locator("visible=true").first

        try:
            if await upload_option.is_visible(timeout=2500):
                logger.info("Phát hiện menu thả xuống. Đang chọn mục tải file lên...")
                async with page.expect_file_chooser(timeout=5000) as fc_info:
                    await upload_option.click(force=True)
                file_chooser = await fc_info.value
                await file_chooser.set_files(str_paths)
                upload_success = True
        except Exception as e:
            logger.info(f"Không nhấp được menu thả xuống ({e}). Chuyển sang phương án nạp file trực tiếp...")

        if not upload_success:
            # 3. Click nút Plus kết hợp expect_file_chooser
            try:
                if await plus_button.is_visible(timeout=2000):
                    async with page.expect_file_chooser(timeout=5000) as fc_info:
                        await plus_button.click(force=True)
                    file_chooser = await fc_info.value
                    await file_chooser.set_files(str_paths)
                    upload_success = True
            except Exception as e:
                logger.debug(f"File chooser trực tiếp từ Plus button thất bại ({e})...")

        if not upload_success:
            # 4. Fallback cuối cùng: nạp trực tiếp vào thẻ input file của DOM
            try:
                await page.set_input_files("input[type='file']", str_paths)
                logger.info("Đã nạp file thành công qua thẻ input[type='file'].")
                upload_success = True
            except Exception as e:
                logger.error(f"Lỗi nạp file trực tiếp qua input[type='file']: {e}")

        if upload_success:
            logger.info("Đã gửi tệp ảnh vào trình duyệt thành công.")
            return True

        return False

    async def _upload_image_in_video_mode(self, image_paths: list[Path]) -> bool:
        """Tải tệp ảnh lên chuyên biệt cho giao diện 'Tạo video' của Gemini."""
        if not self.page or self.page.is_closed():
            return False

        str_paths = [str(p.resolve()) for p in image_paths if p.exists()]
        if not str_paths:
            logger.warning("Không có đường dẫn tệp ảnh hợp lệ để tải lên.")
            return False

        logger.info(f"Đang tiến hành tải {len(str_paths)} ảnh lên giao diện Tạo Video...")
        page = self.page

        # 1. Danh sách selector nút biểu tượng ảnh 🖼️ trong giao diện Tạo video
        image_button_selectors = [
            "button:has(mat-icon:has-text('image'))",
            "button:has(mat-icon:has-text('add_photo_alternate'))",
            "button:has(mat-icon:has-text('photo'))",
            "button:has(mat-icon:has-text('insert_photo'))",
            "button:has(mat-icon[data-mat-icon-name*='image'])",
            "button:has(mat-icon[data-mat-icon-name*='photo'])",
            "button[aria-label*='ảnh' i]",
            "button[aria-label*='image' i]",
            "button[aria-label*='photo' i]",
            "button[aria-label*='tải' i]",
            "button[aria-label*='upload' i]",
            "button[mattooltip*='ảnh' i]",
            "button[mattooltip*='image' i]",
            "button[mattooltip*='photo' i]",
            "button[mattooltip*='tải' i]",
            "button[mattooltip*='upload' i]",
            "button:has-text('Thêm ảnh')",
            "button:has-text('Add image')",
            "button:has-text('Tải ảnh')",
            "button:has-text('Upload image')",
            "button:has-text('Chọn ảnh')"
        ]

        # Phương án 1: Click nút biểu tượng ảnh 🖼️ trên thanh công cụ Tạo video và dùng file_chooser
        for sel in image_button_selectors:
            try:
                btn = page.locator(sel).locator("visible=true").first
                if await btn.is_visible(timeout=800):
                    logger.info(f"Phát hiện nút ảnh 🖼️ bằng selector: {sel}")
                    try:
                        async with page.expect_file_chooser(timeout=3500) as fc_info:
                            await btn.click(force=True)
                        file_chooser = await fc_info.value
                        await file_chooser.set_files(str_paths)
                        logger.info("⚡ Đã chọn tệp ảnh thành công qua file_chooser!")
                        await asyncio.sleep(1)
                        return True
                    except Exception as fc_err:
                        logger.debug(f"Click nút {sel} không kích hoạt file chooser ({fc_err}), tiếp tục thử phương án khác...")
            except Exception:
                pass

        # Phương án 2: Click nút Plus (+) rồi chọn Tải ảnh lên
        try:
            plus_btn = page.locator(
                "button[aria-label*='upload' i], button[aria-label*='tải' i], button[aria-label*='thêm' i], button[aria-label*='add' i], button[mattooltip*='Upload' i], button[mattooltip*='Tải' i]"
            ).locator("visible=true").first
            if await plus_btn.is_visible(timeout=1000):
                async with page.expect_file_chooser(timeout=3500) as fc_info:
                    await plus_btn.click(force=True)
                file_chooser = await fc_info.value
                await file_chooser.set_files(str_paths)
                logger.info("⚡ Đã nạp tệp ảnh qua nút Plus (+).")
                await asyncio.sleep(1)
                return True
        except Exception as e:
            logger.debug(f"Nạp qua Plus button không kích hoạt file chooser: {e}")

        # Phương án 3: Kích hoạt file input trực tiếp bằng Playwright set_input_files
        try:
            file_inputs = page.locator("input[type='file']")
            count = await file_inputs.count()
            if count > 0:
                await file_inputs.first.set_input_files(str_paths)
                logger.info(f"⚡ Đã nạp tệp ảnh qua thẻ input[type='file'] (Tìm thấy {count} thẻ input).")
                await asyncio.sleep(1)
                return True
        except Exception as e:
            logger.warning(f"Lỗi nạp file trực tiếp qua input[type='file']: {e}")

        # Phương án 4: Dùng JS kích hoạt click() trên thẻ input[type='file'] đồng thời với expect_file_chooser
        try:
            async with page.expect_file_chooser(timeout=3000) as fc_info:
                await page.evaluate("() => { const inp = document.querySelector(\"input[type='file']\"); if (inp) inp.click(); }")
            file_chooser = await fc_info.value
            await file_chooser.set_files(str_paths)
            logger.info("⚡ Đã nạp tệp ảnh bằng JS trigger input.click().")
            await asyncio.sleep(1)
            return True
        except Exception as js_err:
            logger.debug(f"JS trigger input.click() thất bại: {js_err}")

        # Fallback cuối cùng
        return await self._upload_images_to_page(image_paths)

    async def _is_image_attached_in_dom(self) -> bool:
        """Kiểm tra xem thẻ preview hoặc thumbnail ảnh đã thực sự xuất hiện trong ô nhập Gemini chưa."""
        if not self.page or self.page.is_closed():
            return False

        image_preview_selectors = [
            "uploader-file",
            "file-preview",
            ".image-preview",
            ".preview-image",
            "[data-test-id*='file']",
            "img[src*='blob:']",
            "img[src*='googleusercontent']",
            "img[src*='data:image']",
            "button[aria-label*='Remove' i]",
            "button[aria-label*='Xóa' i]",
            "button[aria-label*='Gỡ' i]",
            "button[aria-label*='Delete' i]",
            "mat-chip",
            "[class*='attachment']",
            "[class*='thumbnail']",
            "[class*='preview'] img",
            "figure img",
            "div[class*='image'] img"
        ]

        for sel in image_preview_selectors:
            try:
                elem = self.page.locator(sel).locator("visible=true").first
                if await elem.is_visible(timeout=100):
                    return True
            except Exception:
                pass

        return False

    async def _wait_and_submit_prompt(self, input_element, timeout_seconds: int = 30, image_paths: list[Path] | None = None) -> bool:
        """
        BẮT BUỘC ĐỦ 3 ĐIỀU KIỆN MỚI CHO PHÉP ENTER/SEND:
        1. Ảnh ĐÃ THỰC SỰ XUẤT HIỆN trong ô preview.
        2. Thanh tiến trình nạp tệp ĐÃ HOÀN TẤT.
        3. Nút Send / Enter ĐÃ ACTIVE (enabled).
        """
        if not self.page or self.page.is_closed():
            return False

        require_image = bool(image_paths and len(image_paths) > 0)
        logger.info(f"Đang theo dõi ô nhập & nút Send... (Cần có ảnh đính kèm: {require_image})")

        send_button_selectors = (
            "button[aria-label*='Send' i], "
            "button[aria-label*='Gửi' i], "
            "button[aria-label*='submit' i], "
            "button[aria-label*='tạo' i], "
            "button[aria-label*='create' i], "
            "button[aria-label*='generate' i], "
            "button[mattooltip*='Send' i], "
            "button[mattooltip*='Gửi' i], "
            "button.send-button, "
            ".send-button-container button, "
            "button:has(mat-icon[data-mat-icon-name='send']), "
            "button:has(mat-icon:has-text('send')), "
            "button:has-text('Gửi'), "
            "button:has-text('Send'), "
            "button:has-text('Tạo video'), "
            "button:has-text('Create video'), "
            "button:has-text('Tạo'), "
            "button:has-text('Create')"
        )

        progress_selectors = [
            "mat-progress-bar",
            "uploader-file mat-spinner",
            "file-preview mat-spinner",
            "[role='progressbar']"
        ]

        max_checks = int(timeout_seconds / 0.2)  # Poll 200ms

        for check in range(max_checks):
            # 1. Kiểm tra ảnh đã đính kèm trong DOM chưa
            has_image = True
            if require_image:
                has_image = await self._is_image_attached_in_dom()

            # 2. Tự động kích hoạt nạp lại ảnh nếu sau 2.5s hoặc 5s vẫn chưa thấy thẻ ảnh trong DOM
            if require_image and not has_image and check in [12, 25] and image_paths:
                logger.warning(f"Phát hiện chưa có ảnh trong ô preview (Check {check}). Kích hoạt nạp ảnh lại...")
                try:
                    await self._upload_image_in_video_mode(image_paths)
                    await asyncio.sleep(0.5)
                    has_image = await self._is_image_attached_in_dom()
                except Exception as e:
                    logger.error(f"Lỗi nạp lại file: {e}")

            # 3. Kiểm tra thanh progress tải ảnh có đang chạy không
            is_uploading = False
            for sel in progress_selectors:
                try:
                    if await self.page.locator(sel).locator("visible=true").first.is_visible(timeout=80):
                        is_uploading = True
                        break
                except Exception:
                    pass

            # 4. Kiểm tra nút Send/Enter đã ACTIVE chưa
            send_btn = self.page.locator(send_button_selectors).locator("visible=true").first
            btn_active = False

            try:
                if await send_btn.is_visible(timeout=100):
                    aria_disabled = await send_btn.get_attribute("aria-disabled")
                    disabled_attr = await send_btn.get_attribute("disabled")

                    if aria_disabled != "true" and disabled_attr is None and await send_btn.is_enabled():
                        btn_active = True
            except Exception:
                pass

            # 5. CHỈ ENTER/GỬI KHI ĐỦ 3 ĐIỀU KIỆN THỎA MÃN (Có ảnh + Hết Upload + Nút Send ACTIVE)
            if has_image and not is_uploading and btn_active:
                logger.info(f"🚀 THỎA MÃN ĐỦ 3 ĐIỀU KIỆN (Đã có ảnh + Hết upload + Nút Enter ACTIVE sau {check * 0.2:.1f}s)! Kích hoạt Enter/Gửi tạo video...")
                try:
                    await send_btn.click(force=True)
                    await asyncio.sleep(0.5)
                    return True
                except Exception as e:
                    logger.warning(f"Click nút Send bị gián đoạn ({e}), thử bấm phím Enter...")
                    await input_element.focus()
                    await input_element.press("Enter")
                    await asyncio.sleep(0.5)
                    return True

            if check > 0 and check % 15 == 0:
                logger.info(f"Vẫn đang chờ nạp ảnh & nút Send... (has_image={has_image}, is_uploading={is_uploading}, btn_active={btn_active}) [{check * 0.2:.1f}s/{timeout_seconds}s]")

            await asyncio.sleep(0.2)

        if require_image and not (await self._is_image_attached_in_dom()):
            logger.error(f"❌ Không thể gửi prompt vì ẢNH CHƯA ĐƯỢC NẠP VÀO TRÌNH DUYỆT sau {timeout_seconds}s!")
            return False

        logger.warning(f"Hết thời gian chờ ({timeout_seconds}s). Nhấn Enter cưỡng chế...")
        try:
            await input_element.focus()
            await input_element.press("Enter")
            await asyncio.sleep(0.5)
            return True
        except Exception as e:
            logger.error(f"Lỗi khi nhấn Enter: {e}")
            return False

    async def _automate_browser_for_clip(self, image_paths: list[Path], prompt: str, output_path: Path, task: dict[str, Any]):
        """Điều khiển Playwright nạp ảnh, chọn khung dọc 9:16, gửi prompt và tải video."""
        if not self.page or self.page.is_closed():
            raise Exception("Trình duyệt chưa được khởi tạo hoặc đã bị đóng.")

        # 1. Điều hướng và reset khung chat
        logger.info("Điều hướng đến Gemini...")
        await self.page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # 1.5 Nếu prompt là Meta-Prompt (dùng Web UI để tối ưu prompt), thực hiện tối ưu qua Chat trước
        is_meta_prompt = (not self.api_key or self.prompt_mode == "meta") and "Please continue" not in prompt
        if is_meta_prompt:
            logger.info("Chế độ Web UI: Đang tối ưu hóa prompt qua Chat Gemini trước...")
            self.update_task(task, status="generating optimized prompt via chat")
            
            # Tải tệp ảnh lên Chat tự động bằng hàm hỗ trợ nhiều phương án
            await self._upload_images_to_page(image_paths)
            
            # Điền Meta-Prompt đầy đủ vào Chat thường
            from backend.services.prompt_optimizer import _generate_meta_prompt, parse_prompt_response
            meta_prompt_to_send = _generate_meta_prompt(task["user_description"], len(image_paths) > 1, self.meta_prompt_template)

            chat_input = self.page.locator("div[role='textbox'], [contenteditable='true']").first
            await chat_input.focus()
            await chat_input.fill(meta_prompt_to_send)
            await asyncio.sleep(1)
            
            # Chờ ảnh tải xong và nút Send/Enter sáng lên trước khi gửi Meta-Prompt
            await self._wait_and_submit_prompt(chat_input, timeout_seconds=90, image_paths=image_paths)
            
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
            parsed_dict = parse_prompt_response(last_text)
            optimized_prompt = parsed_dict.get("prompt", "").strip()
            
            if not optimized_prompt or "Engineer & Social Media Marketing" in optimized_prompt:
                logger.warning("Không thể lấy prompt tối ưu sạch từ Chat. Dùng prompt fallback.")
                optimized_prompt = f"A high-quality 4k promotional video of pet cat food product based on: {task['user_description']}"
                
            logger.info(f"Đã nhận prompt tối ưu từ Chat: {optimized_prompt}")
            prompt = optimized_prompt
            self.update_task(
                task,
                optimized_prompt=optimized_prompt,
                caption=parsed_dict.get("caption", ""),
                hashtags=parsed_dict.get("hashtags", "")
            )
            
            # Điều hướng lại trang chính để làm sạch khung chat trước khi vào Tạo video
            logger.info("Làm sạch khung chat và bắt đầu bước tạo video...")
            await self.page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
            await asyncio.sleep(2)

        # 2 & 3. Kiểm tra xem trình duyệt đã ở sẵn chế độ Tạo Video hay chưa trước khi click Menu
        ratio_button = self.page.locator(
            "button:has-text('16:9'), button:has-text('9:16'), "
            "button:has-text('ngang'), button:has-text('dọc'), "
            "[role='button']:has-text('16:9'), [role='button']:has-text('9:16')"
        ).locator("visible=true").first

        is_already_video_mode = await ratio_button.is_visible(timeout=1500)

        if not is_already_video_mode:
            logger.info("Đang mở Menu tải lên và chọn chế độ 'Tạo video'...")
            video_menu_found = False

            for attempt in range(1, 4):
                # Click nút Plus (+)
                plus_button = self.page.locator(
                    "button[aria-label*='upload' i], button[aria-label*='tải' i], button[aria-label*='thêm' i], button[aria-label*='add' i], button[mattooltip*='Upload' i], button[mattooltip*='Tải' i]"
                ).locator("visible=true").first

                if not await plus_button.is_visible():
                    plus_button = self.page.locator(
                        ".simplified-input-menu-container button, .leading-actions-wrapper button, [class*='input-menu'] button, button.plus-button"
                    ).locator("visible=true").first

                try:
                    if await plus_button.is_visible(timeout=2000):
                        await plus_button.click(force=True)
                        await asyncio.sleep(1.5)
                except Exception as e:
                    logger.debug(f"Click nút Plus (Lần {attempt}): {e}")

                # Tìm mục 'Tạo video' / 'Create video' / 'Veo' trong menu popup
                video_selectors = [
                    "toolbox-drawer-item:has-text('Tạo video')",
                    "toolbox-drawer-item:has-text('Create video')",
                    "toolbox-drawer-item:has-text('Veo')",
                    ".gem-menu-item-label:has-text('Tạo video')",
                    ".gem-menu-item-label:has-text('Create video')",
                    ".gem-menu-item-label:has-text('Veo')",
                    "[role*='menuitem']:has-text('Tạo video')",
                    "[role*='menuitem']:has-text('Create video')",
                    "[role*='menuitem']:has-text('Veo')",
                    "button[role='menuitemcheckbox']:has-text('Tạo video')",
                    "button[role='menuitemcheckbox']:has-text('Create video')",
                    "button:has-text('Tạo video')",
                    "button:has-text('Create video')",
                    "span:has-text('Tạo video')",
                    "span:has-text('Create video')",
                    "div:has-text('Tạo video')",
                    "div:has-text('Create video')",
                    "button[aria-label*='video' i]",
                    "*[role*='menuitem']:has-text('video' i)"
                ]

                for sel in video_selectors:
                    try:
                        item = self.page.locator(sel).locator("visible=true").first
                        if await item.is_visible(timeout=600):
                            logger.info(f"Tìm thấy mục 'Tạo video' bằng selector: {sel}")
                            await item.click(force=True)
                            await asyncio.sleep(2.5)
                            video_menu_found = True
                            break
                    except Exception:
                        pass

                if video_menu_found:
                    break

                logger.warning(f"Lần thử {attempt}/3 chưa chọn được mục 'Tạo video'. Thử lại...")
                await asyncio.sleep(1)

            if not video_menu_found:
                logger.warning("Không phát hiện menu 'Tạo video' trong popup. Tiếp tục thử tạo video trên giao diện hiện tại...")

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

        # 5. Tải ảnh lên chuyên biệt cho giao diện Tạo video
        logger.info(f"Đang tải {len(image_paths)} hình ảnh lên giao diện Tạo Video...")
        self.update_task(task, status="uploading images to Gemini")
        
        await self._upload_image_in_video_mode(image_paths)
        await asyncio.sleep(1.5)  # Chờ tệp được đính kèm vào DOM

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
        
        # Chờ ảnh tải hoàn tất và nút Send/Enter sáng lên trước khi gửi
        await self._wait_and_submit_prompt(prompt_input, timeout_seconds=90, image_paths=image_paths)
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
        
        # Thực hiện tải video linh hoạt 3 lớp (JS fetch có retry -> APIRequestContext có retry -> UI Download button)
        download_success = False

        # Lớp 1: Thử tải qua JS fetch trong trình duyệt (sử dụng session cookies & hỗ trợ retry 5 lần nếu gặp 503 Service Unavailable)
        for attempt in range(1, 6):
            try:
                logger.info(f"Đang thử tải video qua JS fetch trong trình duyệt (Lần thử {attempt}/5)...")
                res_data = await self.page.evaluate("""async (url) => {
                    for (let i = 0; i < 3; i++) {
                        try {
                            const res = await fetch(url, { credentials: 'include' });
                            if (res.ok) {
                                const blob = await res.blob();
                                return new Promise((resolve, reject) => {
                                    const reader = new FileReader();
                                    reader.onloadend = () => resolve({ ok: true, data: reader.result.split(',')[1] });
                                    reader.onerror = () => resolve({ ok: false, error: 'FileReader error' });
                                    reader.readAsDataURL(blob);
                                });
                            }
                            if (res.status === 503 || res.status === 500) {
                                await new Promise(r => setTimeout(r, 2500));
                                continue;
                            }
                            return { ok: false, status: res.status, statusText: res.statusText };
                        } catch (e) {
                            await new Promise(r => setTimeout(r, 2500));
                        }
                    }
                    return { ok: false, error: 'Failed after internal JS retries' };
                }""", video_src)

                if res_data and res_data.get("ok"):
                    video_bytes = base64.b64decode(res_data["data"])
                    with open(output_path, "wb") as f:
                        f.write(video_bytes)
                    await asyncio.sleep(1)
                    if output_path.exists() and output_path.stat().st_size >= 10000:
                        logger.info(f"Đã tải thành công video qua JS fetch (Kích thước: {output_path.stat().st_size} bytes)")
                        download_success = True
                        break
                else:
                    logger.warning(f"Lần thử {attempt} qua JS fetch thất bại: {res_data}")
            except Exception as e:
                logger.debug(f"Lỗi thử JS fetch (Lần {attempt}): {e}")
            await asyncio.sleep(2.5)

        # Lớp 2: Thử tải qua Playwright request context (có retry) nếu lớp 1 chưa thành công
        if not download_success and not video_src.startswith("blob:"):
            for attempt in range(1, 4):
                try:
                    logger.info(f"Đang thử tải video qua Playwright request context (Lần thử {attempt}/3)...")
                    response = await self.page.request.get(video_src)
                    if response.ok:
                        video_bytes = await response.body()
                        with open(output_path, "wb") as f:
                            f.write(video_bytes)
                        await asyncio.sleep(1)
                        if output_path.exists() and output_path.stat().st_size >= 10000:
                            logger.info(f"Đã tải thành công video qua request context (Kích thước: {output_path.stat().st_size} bytes)")
                            download_success = True
                            break
                    else:
                        logger.warning(f"Lần thử {attempt} qua request context thất bại: Status {response.status} {response.status_text}")
                except Exception as e:
                    logger.debug(f"Lỗi request context (Lần {attempt}): {e}")
                await asyncio.sleep(3)

        # Lớp 3: Thử click nút Tải xuống trên giao diện Gemini nếu 2 lớp trên thất bại
        if not download_success:
            try:
                logger.info("Chuyển sang thử phương án click nút Tải xuống trên giao diện Gemini...")
                download_btn = self.page.locator(
                    "button[aria-label*='Download' i], button[aria-label*='Tải' i], button[mattooltip*='Download' i], button[mattooltip*='Tải' i], a[download]"
                ).last
                if await download_btn.is_visible(timeout=3000):
                    async with self.page.expect_download(timeout=15000) as download_info:
                        await download_btn.click(force=True)
                    download = await download_info.value
                    await download.save_as(output_path)
                    await asyncio.sleep(1)
                    if output_path.exists() and output_path.stat().st_size >= 10000:
                        logger.info(f"Đã tải video thành công bằng nút Tải xuống trên giao diện!")
                        download_success = True
            except Exception as e:
                logger.warning(f"Click nút Tải xuống trên giao diện chưa thành công: {e}")

        # Kiểm tra cuối cùng
        if not download_success or not output_path.exists() or output_path.stat().st_size < 10000:
            raise Exception("Không thể tải video từ trình duyệt (Google CDN trả về 503 hoặc quá trình tải về bị ngắt).")

        logger.info(f"Đã lưu video thành công vào: {output_path} (Kích thước: {output_path.stat().st_size} bytes)")
        await asyncio.sleep(2)  # Đợi 2s để đảm bảo phiên làm việc ổn định trước khi chuyển nhiệm vụ mới
