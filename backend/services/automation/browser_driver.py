"""
Quản lý vòng đời trình duyệt Playwright, Chrome persistent profile, cờ chống bot và screenshot loop.
"""

import asyncio
import base64
import logging

from playwright.async_api import async_playwright, Playwright, BrowserContext, Page
from backend.config import PROFILE_DIR
from backend.services.automation.selectors import TEXTBOX_SELECTOR

logger = logging.getLogger(__name__)

class BrowserDriver:
    """Quản lý kết nối trình duyệt Playwright Chrome persistent context."""

    def __init__(self):
        self.playwright: Playwright | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        
        self.status: str = "idle"  # idle, waiting_login, running, paused
        self.screenshot: str | None = None
        self.error_message: str | None = None
        self.screenshot_task: asyncio.Task | None = None

    async def initialize(self):
        """Khởi tạo Playwright và mở trình duyệt Chrome với profile cố định."""
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

    async def _screenshot_loop(self):
        """Luồng chụp ảnh màn hình trình duyệt định kỳ gửi lên UI."""
        while True:
            try:
                if self.page:
                    screenshot_bytes = await self.page.screenshot(type="jpeg", quality=40)
                    self.screenshot = base64.b64encode(screenshot_bytes).decode('utf-8')
                    
                    # Tự động phát hiện nếu người dùng đã hoàn thành đăng nhập
                    if self.status == "waiting_login":
                        url = self.page.url
                        if "gemini.google.com" in url:
                            textbox = self.page.locator(TEXTBOX_SELECTOR).first
                            if await textbox.is_visible(timeout=500):
                                logger.info("Tự động phát hiện người dùng đã đăng nhập thành công.")
                                self.status = "idle"
            except Exception:
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
            if self.page.url and "gemini.google.com" in self.page.url:
                textbox = self.page.locator(TEXTBOX_SELECTOR).first
                if await textbox.is_visible(timeout=1000):
                    logger.info("Đã đăng nhập thành công (xác nhận nhanh).")
                    self.status = "idle"
                    return True
                    
            await self.page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
            await asyncio.sleep(2)
            
            textbox = self.page.locator(TEXTBOX_SELECTOR).first
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
        
        try:
            if PROFILE_DIR.exists():
                import shutil
                shutil.rmtree(PROFILE_DIR, ignore_errors=True)
                PROFILE_DIR.mkdir(parents=True, exist_ok=True)
                logger.info("Đã xóa sạch cache & session tài khoản cũ.")
        except Exception as e:
            logger.warning(f"Không thể xóa thư mục profile: {e}")

        await self.initialize()
        self.status = "waiting_login"
        
        if self.page:
            try:
                logger.info("Đã mở trang Đăng nhập Google cho tài khoản mới.")
                await self.page.goto("https://accounts.google.com/ServiceLogin?continue=https://gemini.google.com/app", wait_until="domcontentloaded")
            except Exception as e:
                logger.error(f"Lỗi khi điều hướng sang trang đăng nhập: {e}")
