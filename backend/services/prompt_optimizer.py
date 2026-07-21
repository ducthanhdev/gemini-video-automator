import logging
from typing import Any
from pathlib import Path
from PIL import Image
from google import genai
from google.genai import types
from backend.config import DEFAULT_SYSTEM_INSTRUCTION, DEFAULT_META_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

import re

def parse_prompt_response(text: str) -> dict[str, str]:
    """Phân tách văn bản phản hồi từ Gemini thành các thành phần prompt, caption và hashtags."""
    if not text:
        return {"prompt": "", "caption": "", "hashtags": ""}
        
    text = text.strip()
    
    # Tìm các vị trí thẻ nhãn PROMPT, CAPTION, HASHTAGS bằng regex (chấp nhận cả markdown **, #, số thứ tự)
    prompt_match = re.search(r'(?:\*\*|#|\d+\.\s*)?PROMPT(?:\*\*|:|\s)*\n?', text, re.IGNORECASE)
    caption_match = re.search(r'(?:\*\*|#|\d+\.\s*)?CAPTION(?:\*\*|:|\s)*\n?', text, re.IGNORECASE)
    hashtags_match = re.search(r'(?:\*\*|#|\d+\.\s*)?HASHTAGS(?:\*\*|:|\s)*\n?', text, re.IGNORECASE)

    prompt = text
    caption = ""
    hashtags = ""

    if prompt_match and caption_match:
        p_start = prompt_match.end()
        c_start = caption_match.start()
        prompt = text[p_start:c_start].strip()

        if hashtags_match and hashtags_match.start() > c_start:
            c_end = hashtags_match.start()
            caption = text[caption_match.end():c_end].strip()
            hashtags = text[hashtags_match.end():].strip()
        else:
            caption = text[caption_match.end():].strip()
    elif caption_match:
        prompt = text[:caption_match.start()].strip()
        if hashtags_match and hashtags_match.start() > caption_match.start():
            caption = text[caption_match.end():hashtags_match.start()].strip()
            hashtags = text[hashtags_match.end():].strip()
        else:
            caption = text[caption_match.end():].strip()

    # Làm sạch ký tự thừa xung quanh prompt, caption, hashtags
    prompt = re.sub(r'^\*+|\*+$', '', prompt).strip()
    prompt = prompt.strip('"').strip("'").strip()
    
    caption = re.sub(r'^\*+|\*+$', '', caption).strip()
    hashtags = re.sub(r'^\*+|\*+$', '', hashtags).strip()

    return {
        "prompt": prompt,
        "caption": caption,
        "hashtags": hashtags
    }

def optimize_prompt(
    image_paths: list[Path],
    user_description: str,
    api_key: str | None = None,
    system_instruction: str | None = None,
    meta_prompt_template: str | None = None
) -> dict[str, str]:
    """
    Tối ưu hóa prompt tạo video từ hình ảnh và mô tả ngắn.
    Trả về dict chứa: prompt, caption, hashtags.
    """
    sys_instruction = system_instruction if system_instruction and system_instruction.strip() else DEFAULT_SYSTEM_INSTRUCTION
    meta_template = meta_prompt_template if meta_prompt_template and meta_prompt_template.strip() else DEFAULT_META_PROMPT_TEMPLATE

    if api_key and api_key.strip():
        try:
            logger.info("Đang gọi API Gemini để tối ưu hóa prompt...")
            client = genai.Client(api_key=api_key.strip())
            
            pil_images = []
            for path in image_paths:
                if path.exists():
                    pil_images.append(Image.open(path))
            
            if not pil_images:
                logger.warning("Không tìm thấy tệp ảnh nào hợp lệ để gửi cho API. Chuyển sang Meta-Prompt.")
                meta_str = _generate_meta_prompt(user_description, len(image_paths) > 1, meta_template)
                return parse_prompt_response(meta_str)

            contents: list[Any] = []
            contents.extend(pil_images)
            contents.append(f"Mô tả của người dùng: '{user_description}'")

            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=sys_instruction,
                    max_output_tokens=600,
                    temperature=0.7
                )
            )
            
            text = response.text
            if not text:
                raise Exception("Không nhận được phản hồi từ Gemini.")
                
            res_dict = parse_prompt_response(text)
            logger.info(f"Đã tối ưu hóa prompt thành công: {res_dict['prompt'][:60]}...")
            return res_dict
            
        except Exception as e:
            logger.error(f"Lỗi khi gọi API Gemini Developer: {e}. Tự động fallback sang Meta-Prompt.")
            meta_str = _generate_meta_prompt(user_description, len(image_paths) > 1, meta_template)
            return parse_prompt_response(meta_str)
    else:
        logger.info("Không có API Key. Sử dụng Meta-Prompt trực tiếp cho Web UI.")
        meta_str = _generate_meta_prompt(user_description, len(image_paths) > 1, meta_template)
        return parse_prompt_response(meta_str)

def _generate_meta_prompt(user_description: str, has_multiple_images: bool, meta_template: str) -> str:
    """Tạo Meta-Prompt tối ưu gửi thẳng cho Gemini Web."""
    try:
        formatted_prompt = meta_template.format(description=user_description)
    except Exception as e:
        logger.error(f"Lỗi định dạng meta_template: {e}. Fallback về mặc định.")
        from backend.config import DEFAULT_META_PROMPT_TEMPLATE
        formatted_prompt = DEFAULT_META_PROMPT_TEMPLATE.format(description=user_description)

    if has_multiple_images:
        if "transition" not in formatted_prompt.lower():
            formatted_prompt = "I want to create a video transitioning smoothly through these photos. " + formatted_prompt
        return formatted_prompt
    else:
        return formatted_prompt

