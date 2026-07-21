import logging
from typing import Any
from pathlib import Path
from PIL import Image
from google import genai
from google.genai import types
from backend.config import DEFAULT_SYSTEM_INSTRUCTION, DEFAULT_META_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

def optimize_prompt(
    image_paths: list[Path],
    user_description: str,
    api_key: str | None = None,
    system_instruction: str | None = None,
    meta_prompt_template: str | None = None
) -> str:
    """
    Tối ưu hóa prompt tạo video từ hình ảnh và mô tả ngắn.
    - Lựa chọn 1: Nếu có api_key, gọi API gemini-2.5-flash của Google GenAI.
    - Lựa chọn 2: Nếu không có api_key, tạo Meta-Prompt tiếng Việt/Anh để Playwright gửi lên Web UI.
    """
    sys_instruction = system_instruction if system_instruction and system_instruction.strip() else DEFAULT_SYSTEM_INSTRUCTION
    meta_template = meta_prompt_template if meta_prompt_template and meta_prompt_template.strip() else DEFAULT_META_PROMPT_TEMPLATE

    if api_key and api_key.strip():
        try:
            logger.info("Đang gọi API Gemini để tối ưu hóa prompt...")
            client = genai.Client(api_key=api_key.strip())
            
            # Load tất cả các ảnh bằng PIL
            pil_images = []
            for path in image_paths:
                if path.exists():
                    pil_images.append(Image.open(path))
            
            if not pil_images:
                logger.warning("Không tìm thấy tệp ảnh nào hợp lệ để gửi cho API. Chuyển sang Meta-Prompt.")
                return _generate_meta_prompt(user_description, len(image_paths) > 1, meta_template)

            # Chuẩn bị nội dung gửi lên Gemini
            contents: list[Any] = []
            contents.extend(pil_images)
            contents.append(f"Mô tả của người dùng: '{user_description}'")

            # Gọi mô hình gemini-2.5-flash để sinh prompt tiếng Anh tối ưu
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=sys_instruction,
                    max_output_tokens=400,
                    temperature=0.7
                )
            )
            
            text = response.text
            if not text:
                raise Exception("Không nhận được phản hồi từ Gemini.")
            optimized = text.strip()
            # Loại bỏ các dấu nháy kép bọc xung quanh nếu có
            if (optimized.startswith('"') and optimized.endswith('"')) or (optimized.startswith("'") and optimized.endswith("'")):
                optimized = optimized[1:-1].strip()
                
            logger.info(f"Đã tối ưu hóa prompt thành công: {optimized}")
            return optimized
            
        except Exception as e:
            logger.error(f"Lỗi khi gọi API Gemini Developer: {e}. Tự động fallback sang Meta-Prompt.")
            return _generate_meta_prompt(user_description, len(image_paths) > 1, meta_template)
    else:
        logger.info("Không có API Key. Sử dụng Meta-Prompt trực tiếp cho Web UI.")
        return _generate_meta_prompt(user_description, len(image_paths) > 1, meta_template)

def _generate_meta_prompt(user_description: str, has_multiple_images: bool, meta_template: str) -> str:
    """Tạo Meta-Prompt tối ưu gửi thẳng cho Gemini Web."""
    try:
        formatted_prompt = meta_template.format(description=user_description)
    except Exception as e:
        logger.error(f"Lỗi định dạng meta_template: {e}. Fallback về mặc định.")
        from backend.config import DEFAULT_META_PROMPT_TEMPLATE
        formatted_prompt = DEFAULT_META_PROMPT_TEMPLATE.format(description=user_description)

    if has_multiple_images:
        # Nếu có nhiều ảnh và chưa có chỉ thị chuyển tiếp, tự động thêm vào để đảm bảo mượt mà
        if "transition" not in formatted_prompt.lower():
            formatted_prompt = "I want to create a video transitioning smoothly through these photos. " + formatted_prompt
        return formatted_prompt
    else:
        return formatted_prompt

