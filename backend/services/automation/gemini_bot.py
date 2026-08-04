"""
Tương tác DOM Playwright trên giao diện Google Gemini UI (tải ảnh, nhập prompt, chọn tỉ lệ khung hình, chờ render video và retry download).
"""

import asyncio
import base64
import logging
from pathlib import Path
from typing import Any

from backend.services.product_parser import ProductParser
from backend.services.automation.selectors import (
    TEXTBOX_SELECTOR,
    PLUS_BUTTON_SELECTOR,
    PLUS_BUTTON_FALLBACK_SELECTOR,
    MENU_UPLOAD_SELECTOR,
    IMAGE_BUTTON_SELECTORS,
    CREATE_VIDEO_BUTTON_SELECTORS,
    TRY_BUTTON_SELECTORS,
    RATIO_BUTTON_SELECTOR,
    RATIO_9_16_SELECTORS,
    RATIO_16_9_SELECTORS,
    PROMPT_INPUT_SELECTOR,
    SEND_BUTTON_SELECTORS,
    PROGRESS_BAR_SELECTORS,
    IMAGE_PREVIEW_SELECTORS,
    VIDEO_PLAYER_SELECTOR,
    DOWNLOAD_BUTTON_SELECTORS,
)

logger = logging.getLogger(__name__)

class GeminiBot:
    """Tự động hóa các thao tác DOM trên trang Google Gemini Web App."""

    def __init__(self, driver):
        self.driver = driver

    @property
    def page(self):
        return self.driver.page

    @property
    def context(self):
        return self.driver.context

    async def parse_product_url_with_browser(self, url: str, api_key: str = "") -> dict:
        """Sử dụng trình duyệt Chrome đang chạy để mở link sản phẩm và bóc tách dữ liệu DOM chi tiết dưới phần About this product."""
        if not self.context:
            return ProductParser.parse_product_url(url, api_key=api_key)

        page = self.page
        opened_new_page = False
        if not page or page.is_closed():
            page = await self.context.new_page()
            opened_new_page = True

        try:
            logger.info(f"Đang mở link sản phẩm mới trên Chrome: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            
            logger.info("Tạm dừng 5 giây chờ trang tải hoàn tất và cho phép giải Captcha trên Chrome...")
            await asyncio.sleep(5)

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
                    await page.evaluate("window.scrollTo(0, 800)")
                    await asyncio.sleep(1)

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

        return ProductParser.parse_product_url(url, api_key=api_key)

    async def _upload_images_to_page(self, image_paths: list[Path], timeout_seconds: int = 90) -> bool:
        """Tải hình ảnh lên trình duyệt Gemini một cách linh hoạt."""
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

        plus_button = page.locator(PLUS_BUTTON_SELECTOR).locator("visible=true").first

        try:
            if await plus_button.is_visible(timeout=3000):
                await plus_button.click(force=True)
                await asyncio.sleep(1)
        except Exception as e:
            logger.debug(f"Không thể click nút Plus: {e}")

        upload_option = page.locator(MENU_UPLOAD_SELECTOR).locator("visible=true").first

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

        for sel in IMAGE_BUTTON_SELECTORS:
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
                        logger.debug(f"Click nút {sel} không kích hoạt file chooser ({fc_err}), tiếp tục thử...")
            except Exception:
                pass

        try:
            plus_btn = page.locator(PLUS_BUTTON_SELECTOR).locator("visible=true").first
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

        return await self._upload_images_to_page(image_paths)

    async def _is_image_attached_in_dom(self) -> bool:
        """Kiểm tra xem thẻ preview hoặc thumbnail ảnh đã thực sự xuất hiện trong ô nhập Gemini chưa."""
        if not self.page or self.page.is_closed():
            return False

        for sel in IMAGE_PREVIEW_SELECTORS:
            try:
                elem = self.page.locator(sel).locator("visible=true").first
                if await elem.is_visible(timeout=100):
                    return True
            except Exception:
                pass

        return False

    async def _wait_and_submit_prompt(self, input_element, timeout_seconds: int = 30, image_paths: list[Path] | None = None) -> bool:
        """BẮT BUỘC ĐỦ 3 ĐIỀU KIỆN MỚI CHO PHÉP ENTER/SEND (ảnh xuất hiện, hết upload, nút Send ACTIVE)."""
        if not self.page or self.page.is_closed():
            return False

        require_image = bool(image_paths and len(image_paths) > 0)
        logger.info(f"Đang theo dõi ô nhập & nút Send... (Cần có ảnh đính kèm: {require_image})")

        max_checks = int(timeout_seconds / 0.2)

        for check in range(max_checks):
            has_image = True
            if require_image:
                has_image = await self._is_image_attached_in_dom()

            if require_image and not has_image and check in [12, 25] and image_paths:
                logger.warning(f"Phát hiện chưa có ảnh trong ô preview (Check {check}). Kích hoạt nạp ảnh lại...")
                try:
                    await self._upload_image_in_video_mode(image_paths)
                    await asyncio.sleep(0.5)
                    has_image = await self._is_image_attached_in_dom()
                except Exception as e:
                    logger.error(f"Lỗi nạp lại file: {e}")

            is_uploading = False
            for sel in PROGRESS_BAR_SELECTORS:
                try:
                    if await self.page.locator(sel).locator("visible=true").first.is_visible(timeout=80):
                        is_uploading = True
                        break
                except Exception:
                    pass

            send_btn = self.page.locator(SEND_BUTTON_SELECTORS).locator("visible=true").first
            btn_active = False

            try:
                if await send_btn.is_visible(timeout=100):
                    aria_disabled = await send_btn.get_attribute("aria-disabled")
                    disabled_attr = await send_btn.get_attribute("disabled")
                    if aria_disabled != "true" and disabled_attr is None and await send_btn.is_enabled():
                        btn_active = True
            except Exception:
                pass

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

    async def _automate_browser_for_clip(
        self,
        image_paths: list[Path],
        prompt: str,
        output_path: Path,
        task: dict[str, Any],
        update_task_fn,
        settings: dict[str, Any],
        cycle: int = 0,
        num_cycles: int = 1
    ):
        """Điều khiển Playwright nạp ảnh, chọn khung dọc 9:16, gửi prompt và tải video."""
        if not self.page or self.page.is_closed():
            raise Exception("Trình duyệt chưa được khởi tạo hoặc đã bị đóng.")

        base_prog = 10 + int((cycle / num_cycles) * 75)
        cycle_span = max(10, int(75 / num_cycles))

        logger.info("Điều hướng đến Gemini...")
        await self.page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
        await asyncio.sleep(2)

        api_key = settings.get("api_key", "")
        prompt_mode = settings.get("prompt_mode", "api")
        meta_prompt_template = settings.get("meta_prompt_template", "")

        is_meta_prompt = (not api_key or prompt_mode == "meta") and "Please continue" not in prompt
        if is_meta_prompt:
            logger.info("Chế độ Web UI: Đang tối ưu hóa prompt qua Chat Gemini trước...")
            update_task_fn(task, status="generating optimized prompt via chat")
            
            await self._upload_images_to_page(image_paths)
            
            from backend.services.prompt_optimizer import _generate_meta_prompt, parse_prompt_response
            meta_prompt_to_send = _generate_meta_prompt(task["user_description"], len(image_paths) > 1, meta_prompt_template)

            chat_input = self.page.locator(TEXTBOX_SELECTOR).first
            await chat_input.focus()
            await chat_input.fill(meta_prompt_to_send)
            await asyncio.sleep(1)
            
            await self._wait_and_submit_prompt(chat_input, timeout_seconds=90, image_paths=image_paths)
            
            logger.info("Đã gửi Meta-Prompt. Đang chờ Gemini sinh prompt tối ưu (chờ ít nhất 20 giây)...")
            await asyncio.sleep(20)
            
            last_text = ""
            for _ in range(15):
                try:
                    text = await self.page.locator("message-content").last.inner_text()
                    if len(text.strip()) > 0 and text == last_text:
                        break
                    last_text = text
                except Exception:
                    pass
                await asyncio.sleep(1)
            
            parsed_dict = parse_prompt_response(last_text)
            optimized_prompt = parsed_dict.get("prompt", "").strip()
            
            if not optimized_prompt or "Engineer & Social Media Marketing" in optimized_prompt:
                logger.warning("Không thể lấy prompt tối ưu sạch từ Chat. Dùng prompt fallback.")
                optimized_prompt = f"A high-quality 4k promotional video of pet cat food product based on: {task['user_description']}"
                
            logger.info(f"Đã nhận prompt tối ưu từ Chat: {optimized_prompt}")
            prompt = optimized_prompt
            update_task_fn(
                task,
                optimized_prompt=optimized_prompt,
                voiceover=parsed_dict.get("voiceover", ""),
                caption=parsed_dict.get("caption", ""),
                hashtags=parsed_dict.get("hashtags", "")
            )
            
            logger.info("Làm sạch khung chat và bắt đầu bước tạo video...")
            await self.page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
            await asyncio.sleep(2)

        ratio_button = self.page.locator(RATIO_BUTTON_SELECTOR).locator("visible=true").first

        is_already_video_mode = await ratio_button.is_visible(timeout=1500)

        if not is_already_video_mode:
            logger.info("Đang mở Menu tải lên và chọn chế độ 'Tạo video'...")
            video_menu_found = False

            for attempt in range(1, 4):
                plus_button = self.page.locator(PLUS_BUTTON_SELECTOR).locator("visible=true").first

                if not await plus_button.is_visible():
                    plus_button = self.page.locator(PLUS_BUTTON_FALLBACK_SELECTOR).locator("visible=true").first

                try:
                    if await plus_button.is_visible(timeout=2000):
                        await plus_button.click(force=True)
                        await asyncio.sleep(1.5)
                except Exception as e:
                    logger.debug(f"Click nút Plus (Lần {attempt}): {e}")

                for sel in CREATE_VIDEO_BUTTON_SELECTORS:
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

        try:
            try_button = self.page.locator(TRY_BUTTON_SELECTORS).first
            if await try_button.is_visible(timeout=2000):
                logger.info("Phát hiện modal giới thiệu 'Dùng thử'. Đang click để bỏ qua...")
                await try_button.click(force=True)
                await asyncio.sleep(1.5)
        except Exception as e:
            logger.info(f"Không xuất hiện modal giới thiệu hoặc có lỗi khi bỏ qua: {e}")

        target_ratio = task.get("ratio", "9:16")
        logger.info(f"Đang thiết lập tỷ lệ khung hình: {target_ratio}...")
        
        ratio_button = self.page.locator(RATIO_BUTTON_SELECTOR).locator("visible=true").first
        
        if await ratio_button.is_visible():
            current_text = await ratio_button.inner_text()
            current_text_lower = current_text.lower()
            
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
                
                found_option = False
                selectors = RATIO_9_16_SELECTORS if target_ratio == "9:16" else RATIO_16_9_SELECTORS
                text_vals = ["Dọc (9:16)", "Portrait (9:16)", "9:16", "Dọc", "Portrait"] if target_ratio == "9:16" else ["Ngang (16:9)", "Landscape (16:9)", "16:9", "Ngang", "Landscape"]
                
                for sel in selectors:
                    opt = self.page.locator(sel).locator("visible=true").first
                    if await opt.is_visible():
                        logger.info(f"Tìm thấy tùy chọn tỷ lệ bằng selector: {sel}")
                        await opt.click(force=True)
                        found_option = True
                        break
                        
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

        logger.info(f"Đang tải {len(image_paths)} hình ảnh lên giao diện Tạo Video...")
        p_upload = base_prog + int(cycle_span * 0.15)
        update_task_fn(task, status=f"uploading images (cycle {cycle + 1}/{num_cycles})", progress=p_upload)
        
        await self._upload_image_in_video_mode(image_paths)
        await asyncio.sleep(1.5)

        logger.info("Đang điền prompt tạo video...")
        p_submit = base_prog + int(cycle_span * 0.25)
        update_task_fn(task, status=f"submitting prompt (cycle {cycle + 1}/{num_cycles})", progress=p_submit)
        
        prompt_input = self.page.locator(PROMPT_INPUT_SELECTOR).first
        
        if not await prompt_input.is_visible():
            raise Exception("Không tìm thấy ô nhập mô tả video trên giao diện.")
            
        await prompt_input.focus()
        await prompt_input.fill(prompt)
        await asyncio.sleep(1)
        
        await self._wait_and_submit_prompt(prompt_input, timeout_seconds=90, image_paths=image_paths)
        logger.info("Đã gửi prompt lên Gemini. Đang chờ render video...")
        
        initial_video_count = await self.page.locator(VIDEO_PLAYER_SELECTOR).count()
        
        video_found = False
        for sec in range(180):
            current_video_count = await self.page.locator(VIDEO_PLAYER_SELECTOR).count()
            if current_video_count > initial_video_count:
                video_found = True
                break
            await asyncio.sleep(1.5)
            
        if not video_found:
            raise Exception("Quá thời gian chờ (3 phút) nhưng Gemini vẫn chưa tạo ra video.")

        logger.info("Đã phát hiện video mới. Đang chuẩn bị tải về...")
        update_task_fn(task, status="downloading generated video")
        
        video_element = self.page.locator(VIDEO_PLAYER_SELECTOR).last
        video_src = ""
        
        for _ in range(30):
            video_src = await video_element.get_attribute("src") or ""
            if video_src.startswith("http") or video_src.startswith("blob"):
                break
            await asyncio.sleep(1)
            
        if not video_src:
            raise Exception("Thẻ video không chứa đường dẫn src hợp lệ.")

        logger.info(f"Đường dẫn video phát hiện: {video_src[:60]}...")
        
        download_success = False

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

        if not download_success:
            try:
                logger.info("Chuyển sang thử phương án click nút Tải xuống trên giao diện Gemini...")
                download_btn = self.page.locator(DOWNLOAD_BUTTON_SELECTORS).last
                if await download_btn.is_visible(timeout=3000):
                    async with self.page.expect_download(timeout=15000) as download_info:
                        await download_btn.click(force=True)
                    download = await download_info.value
                    await download.save_as(output_path)
                    await asyncio.sleep(1)
                    if output_path.exists() and output_path.stat().st_size >= 10000:
                        logger.info("Đã tải video thành công bằng nút Tải xuống trên giao diện!")
                        download_success = True
            except Exception as e:
                logger.warning(f"Click nút Tải xuống trên giao diện chưa thành công: {e}")

        if not download_success or not output_path.exists() or output_path.stat().st_size < 10000:
            raise Exception("Không thể tải video từ trình duyệt (Google CDN trả về 503 hoặc quá trình tải về bị ngắt).")

        logger.info(f"Đã lưu video thành công vào: {output_path} (Kích thước: {output_path.stat().st_size} bytes)")
        p_done = base_prog + cycle_span
        update_task_fn(task, status=f"completed clip {cycle + 1}/{num_cycles}", progress=p_done)
        await asyncio.sleep(2)
