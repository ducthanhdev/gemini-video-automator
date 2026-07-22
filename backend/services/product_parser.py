import re
import uuid
import json
import logging
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Dict, Any, List
from backend.config import UPLOAD_DIR

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
}

class ProductParser:
    """Service trích xuất thông tin sản phẩm và tự động tải ảnh từ URL."""

    @staticmethod
    def parse_product_url(url: str, api_key: str = "", **kwargs) -> Dict[str, Any]:
        """
        Tải nội dung HTML từ URL, trích xuất tiêu đề, mô tả và tải về các ảnh sản phẩm chính.
        Tự động phân tích và tạo bài mô tả sản phẩm chi tiết đầy đủ cho mọi ngành hàng.
        """
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        final_url = url
        html = ""
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=12) as response:
                html_bytes = response.read()
                final_url = response.geturl()
                html = html_bytes.decode("utf-8", errors="ignore")
        except Exception as e:
            logger.error(f"Lỗi khi tải trang từ URL {url}: {e}")

        # 1. Trích xuất og_info từ URL (rất hữu ích với TikTok Shop share link)
        og_title = ""
        og_image = ""
        if "og_info=" in final_url or "og_info=" in url:
            try:
                target_u = final_url if "og_info=" in final_url else url
                parsed_q = urllib.parse.parse_qs(urllib.parse.urlparse(target_u).query)
                if "og_info" in parsed_q:
                    og_json_str = parsed_q["og_info"][0]
                    og_dict = json.loads(og_json_str)
                    og_title = og_dict.get("title", "")
                    og_image = og_dict.get("image", "")
            except Exception as ex:
                logger.warning(f"Không thể parse og_info từ URL: {ex}")

        # Trích xuất thông tin từ HTML
        title = ProductParser._extract_title(html)
        description = ProductParser._extract_description(html)
        image_urls = ProductParser._extract_image_urls(html, final_url)

        # Nếu HTML dính Security Check hoặc empty title, ưu tiên dùng og_info vừa parse
        if (not title or title == "Security Check" or title == "Live Content") and og_title:
            title = og_title

        if og_image and og_image not in image_urls:
            image_urls.insert(0, og_image)

        # Tải các hình ảnh chính về UPLOAD_DIR
        saved_images: List[str] = []
        for img_url in image_urls[:3]:  # Lấy tối đa 3 ảnh sản phẩm đại diện
            filename = ProductParser._download_image(img_url)
            if filename:
                saved_images.append(filename)

        # Tự động tạo bài mô tả sản phẩm chi tiết đầy đủ từ dữ liệu thu thập
        full_description = ProductParser._build_structured_description(title, description, api_key=api_key)

        return {
            "title": title,
            "description": description,
            "full_text": full_description,
            "images": saved_images,
            "raw_image_urls": image_urls
        }

    @staticmethod
    def _build_structured_description(title: str, description: str, api_key: str = "") -> str:
        """
        Tạo bài mô tả sản phẩm chi tiết đầy đủ.
        - Nếu có Gemini API Key: Gọi Gemini 2.5 Flash phân tích tên & hình ảnh để tự động sinh ra bài mô tả chi tiết đầy đủ 100-150 từ.
        - Nếu không có API Key hoặc chỉ trích xuất được tiêu đề: Trả về tiêu đề sản phẩm kèm hướng dẫn.
        """
        title_clean = title.strip()
        desc_clean = description.strip() if description and "Security Check" not in description and "Live Content" not in description else ""

        # 1. Nếu có Gemini API Key, tự động gọi AI sinh ra bài mô tả chi tiết sản phẩm hoàn chỉnh
        if api_key:
            try:
                from google import genai
                client = genai.Client(api_key=api_key)
                prompt = (
                    f"Dựa trên thông tin tên sản phẩm sau:\n"
                    f"\"{title_clean}\"\n\n"
                    f"Hãy viết một bài MÔ TẢ SẢN PHẨM HOÀN CHỈNH, ĐẦY ĐỦ CHI TIẾT VÀ TỰ NHIÊN (khoảng 100-150 từ) "
                    f"dành cho sản phẩm này gồm:\n"
                    f"1. Tên & Tổng quan sản phẩm\n"
                    f"2. Chất liệu / Thành phần / Thông số thiết kế\n"
                    f"3. Công dụng nổi bật & Đối tượng phù hợp\n"
                    f"4. Lợi ích khi sử dụng sản phẩm\n"
                    f"Viết bằng tiếng Việt hấp dẫn, thực tế, đúng bản chất ngành hàng của sản phẩm."
                )
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt
                )
                if response and response.text:
                    return response.text.strip()
            except Exception as e:
                logger.warning(f"Không thể dùng Gemini AI để mở rộng mô tả: {e}")

        # 2. Nếu đã trích xuất được mô tả thực tế từ web (và không trùng tiêu đề)
        if desc_clean and desc_clean != title_clean:
            return f"{title_clean}\n\n{desc_clean}"

        # 3. Trả về tiêu đề sản phẩm
        return title_clean

    @staticmethod
    def _extract_title(html: str) -> str:
        # og:title
        match = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # twitter:title
        match = re.search(r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # Thẻ <title>
        match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        return "Sản phẩm mới"

    @staticmethod
    def _extract_description(html: str) -> str:
        # JSON-LD Product description
        json_ld_matches = re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
        for jtext in json_ld_matches:
            try:
                data = json.loads(jtext.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict) and item.get("@type") in ("Product", "ProductGroup"):
                        desc = item.get("description")
                        if isinstance(desc, str) and len(desc) > 15:
                            return desc.strip()
            except Exception:
                pass

        # og:description
        match = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if match:
            desc = match.group(1).strip()
            if len(desc) > 10:
                return desc

        # meta description
        match = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if match:
            desc = match.group(1).strip()
            if len(desc) > 10:
                return desc

        # twitter:description
        match = re.search(r'<meta[^>]+name=["\']twitter:description["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        return ""

    @staticmethod
    def _extract_image_urls(html: str, base_url: str) -> List[str]:
        image_urls = []

        # Find og:image
        matches = re.findall(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        for m in matches:
            if m and m not in image_urls:
                image_urls.append(m)

        # Find twitter:image
        matches = re.findall(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        for m in matches:
            if m and m not in image_urls:
                image_urls.append(m)

        # Parse JSON-LD Product images
        json_ld_matches = re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
        for jtext in json_ld_matches:
            try:
                data = json.loads(jtext.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict) and item.get("@type") in ("Product", "ProductGroup"):
                        img = item.get("image")
                        if isinstance(img, str) and img not in image_urls:
                            image_urls.append(img)
                        elif isinstance(img, list):
                            for iurl in img:
                                if isinstance(iurl, str) and iurl not in image_urls:
                                    image_urls.append(iurl)
            except Exception:
                pass

        # Normalize relative URLs
        final_urls = []
        for img in image_urls:
            img = img.replace("&amp;", "&")
            full_img_url = urllib.parse.urljoin(base_url, img)
            if full_img_url not in final_urls:
                final_urls.append(full_img_url)

        return final_urls

    @staticmethod
    def _download_image(img_url: str) -> str:
        """Tải ảnh từ img_url và lưu vào UPLOAD_DIR với tên UUID. Trả về tên file."""
        try:
            req = urllib.request.Request(img_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
                if not data or len(data) < 500:
                    return ""
                
                content_type = resp.headers.get("Content-Type", "").lower()
                ext = ".jpg"
                if "png" in content_type or ".png" in img_url.lower():
                    ext = ".png"
                elif "webp" in content_type or ".webp" in img_url.lower():
                    ext = ".webp"
                elif "jpeg" in content_type or ".jpg" in img_url.lower():
                    ext = ".jpg"

                filename = f"{uuid.uuid4()}{ext}"
                target_path = UPLOAD_DIR / filename
                with open(target_path, "wb") as f:
                    f.write(data)

                logger.info(f"Đã tải tự động ảnh sản phẩm: {filename} từ {img_url[:60]}...")
                return filename
        except Exception as e:
            logger.warning(f"Không thể tải ảnh sản phẩm từ {img_url[:60]}: {e}")
            return ""
