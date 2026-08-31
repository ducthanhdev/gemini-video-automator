import logging
import re
from typing import Any
from pathlib import Path
from PIL import Image
from google import genai
from google.genai import types
from backend.config import DEFAULT_SYSTEM_INSTRUCTION, DEFAULT_META_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

def generate_smart_caption_and_hashtags(user_description: str, prompt: str = "") -> dict[str, str]:
    """Tự động sinh Caption bán hàng hấp dẫn và 5 Hashtags chuẩn xu hướng khi Gemini chưa sinh đủ."""
    raw_desc = (user_description or "").strip()
    clean_desc = re.sub(r'https?://\S+', '', raw_desc)
    clean_desc = re.sub(r'[#\*\_\[\]]', '', clean_desc).strip()
    
    # Lấy câu ngắn gọn mô tả sản phẩm (dưới 150 ký tự)
    first_line = clean_desc.split('\n')[0].strip() if clean_desc else ""
    product_summary = first_line[:120] if first_line else "sản phẩm chất lượng cao"
    
    caption = (
        f"🔥 Khám phá ngay {product_summary}! ✨\n"
        f"Chất lượng vượt trội, thiết kế sang trọng và mang đến trải nghiệm tuyệt vời. "
        f"Đừng bỏ lỡ cơ hội sở hữu ngay hôm nay với ưu đãi siêu hấp dẫn! 🛒👇"
    )
    
    # Tạo 5 hashtags chuẩn xu hướng, linh hoạt theo tên sản phẩm nếu có
    words = [re.sub(r'\W+', '', w).lower() for w in product_summary.split() if len(w) > 2]
    tags = []
    for w in words[:2]:
        if len(w) >= 3 and w not in ["cua", "cho", "cac", "nhung", "duoc", "khong", "mang"]:
            tags.append(f"#{w}")
            
    default_tags = ["#xuhuong", "#review", "#sanphamhot", "#muataitiktokshop", "#trending", "#fyp"]
    for t in default_tags:
        if t not in tags:
            tags.append(t)
        if len(tags) >= 5:
            break
            
    hashtags = " ".join(tags[:5])
    
    return {
        "caption": caption,
        "hashtags": hashtags
    }

def ensure_caption_and_hashtags(data: dict[str, Any], user_description: str = "") -> dict[str, str]:
    """Đảm bảo chắc chắn dữ liệu có đầy đủ prompt, voiceover, caption và hashtags không bao giờ bị rỗng."""
    prompt = (data.get("prompt") or "").strip()
    voiceover = (data.get("voiceover") or "").strip()
    caption = (data.get("caption") or "").strip()
    hashtags = (data.get("hashtags") or "").strip()
    
    # Nếu chưa có caption hoặc caption quá ngắn, tạo smart caption
    if not caption or len(caption) < 15:
        smart_data = generate_smart_caption_and_hashtags(user_description, prompt)
        caption = smart_data["caption"]
        if not hashtags or len(hashtags) < 5:
            hashtags = smart_data["hashtags"]
            
    # Nếu hashtags vẫn trống hoặc không chứa dấu #, bổ sung 5 hashtags
    if not hashtags or "#" not in hashtags:
        smart_data = generate_smart_caption_and_hashtags(user_description, prompt)
        hashtags = smart_data["hashtags"]
    else:
        # Chuẩn hóa chỉ lấy tối đa đúng 5 hashtags
        found_tags = re.findall(r'#\w+', hashtags)
        if found_tags:
            hashtags = ' '.join(found_tags[:5])
            
    # Nếu voiceover còn trống, tự động trích xuất từ caption
    if not voiceover:
        clean_src = re.sub(r'#\w+', '', caption).strip()
        clean_src = re.sub(r'PROMPT:|CAPTION:|HASHTAGS:|VOICEOVER:', '', clean_src, flags=re.IGNORECASE).strip()
        words = clean_src.split()
        if words:
            voiceover = ' '.join(words[:30])
            
    return {
        "prompt": prompt,
        "voiceover": voiceover,
        "caption": caption,
        "hashtags": hashtags
    }

def parse_prompt_response(text: str) -> dict[str, str]:
    """Phân tách văn bản phản hồi từ Gemini thành các thành phần prompt, voiceover, caption và hashtags."""
    if not text:
        return {"prompt": "", "voiceover": "", "caption": "", "hashtags": ""}
        
    text = text.strip()
    
    # Tìm các vị trí thẻ nhãn PROMPT, VOICEOVER, CAPTION, HASHTAGS bằng regex mở rộng
    prompt_match = re.search(r'(?:\*\*|#|\d+\.\s*)?(?:PROMPT(?:\s*VIDEO)?|CÂU\s*LỆNH|PROMPT)(?:\s*\(.*?\))?(?:\*\*|:|\s)*\n?', text, re.IGNORECASE)
    voiceover_match = re.search(r'(?:\*\*|#|\d+\.\s*)?(?:VOICEOVER|KỊCH\s*BẢN\s*LỒNG\s*TIẾNG|LỒNG\s*TIẾNG|THUYẾT\s*MINH|VOICE\s*OVER)(?:\s*\(.*?\))?(?:\*\*|:|\s)*\n?', text, re.IGNORECASE)
    caption_match = re.search(r'(?:\*\*|#|\d+\.\s*)?(?:CAPTION(?:\s*BÀI\s*ĐĂNG)?|BÀI\s*ĐĂNG|NỘI\s*DUNG\s*BÀI\s*VIẾT|BÀI\s*VIẾT|TIÊU\s*ĐỀ\s*BÀI\s*ĐĂNG)(?:\s*\(.*?\))?(?:\*\*|:|\s)*\n?', text, re.IGNORECASE)
    hashtags_match = re.search(r'(?:\*\*|#|\d+\.\s*)?(?:HASHTAGS?|THẺ\s*HASHTAGS?|THẺ\s*TAGS?|TAGS?)(?:\s*\(.*?\))?(?:\*\*|:|\s)*\n?', text, re.IGNORECASE)

    prompt = text
    voiceover = ""
    caption = ""
    hashtags = ""

    matches = []
    if prompt_match:
        matches.append(('prompt', prompt_match.start(), prompt_match.end()))
    if voiceover_match:
        matches.append(('voiceover', voiceover_match.start(), voiceover_match.end()))
    if caption_match:
        matches.append(('caption', caption_match.start(), caption_match.end()))
    if hashtags_match:
        matches.append(('hashtags', hashtags_match.start(), hashtags_match.end()))

    matches.sort(key=lambda x: x[1])

    if matches:
        sections = {}
        for i, (key, start, end) in enumerate(matches):
            next_start = matches[i + 1][1] if i + 1 < len(matches) else len(text)
            sections[key] = text[end:next_start].strip()

        prompt = sections.get('prompt', prompt)
        voiceover = sections.get('voiceover', '')
        caption = sections.get('caption', '')
        hashtags = sections.get('hashtags', '')

    # Làm sạch ký tự thừa xung quanh prompt, voiceover, caption, hashtags
    prompt = re.sub(r'^\*+|\*+$', '', prompt).strip()
    prompt = prompt.strip('"').strip("'").strip()
    
    # Nếu Gemini lỡ trả về định dạng kịch bản dạng Scene 1, Scene 2..., tự động gom thành 1 đoạn duy nhất
    if "Scene 1" in prompt or "Scene 2" in prompt:
        prompt = re.sub(r'Scene\s*\d+:[^\n]*', '', prompt, flags=re.IGNORECASE).strip()
        prompt = re.sub(r'\n+', ' ', prompt).strip()

    voiceover = re.sub(r'^\*+|\*+$', '', voiceover).strip()
    caption = re.sub(r'^\*+|\*+$', '', caption).strip()
    hashtags = re.sub(r'^\*+|\*+$', '', hashtags).strip()

    # Tự động thay thế các từ ngữ nhạy cảm dính bộ lọc an toàn của Google Veo
    sensitive_replacements = [
        (r'chai\s+dung\s*dịch\s*vệ\s*sinh\s*(phụ\s*nữ)?\s*(pH\s*Care)?', 'chai gel chăm sóc da pH Care'),
        (r'dung\s*dịch\s*vệ\s*sinh\s*(phụ\s*nữ)?\s*(pH\s*Care)?', 'gel chăm sóc da pH Care'),
        (r'vệ\s*sinh\s*phụ\s*nữ', 'chăm sóc da tươi mát'),
        (r'vùng\s*kín', 'vùng da nhạy cảm'),
        (r'kháng\s*khuẩn', 'làm sạch dịu nhẹ'),
    ]
    for pattern, replacement in sensitive_replacements:
        prompt = re.sub(pattern, replacement, prompt, flags=re.IGNORECASE)

    # Nếu chưa có Voiceover, tự động trích xuất đoạn kịch bản ngắn (20-30 từ) từ Caption làm giọng đọc lồng tiếng
    if not voiceover:
        target_src = caption if caption else text
        clean_src = re.sub(r'#\w+', '', target_src).strip()
        clean_src = re.sub(r'PROMPT:|CAPTION:|HASHTAGS:|VOICEOVER:', '', clean_src, flags=re.IGNORECASE).strip()
        words = clean_src.split()
        if words:
            voiceover = ' '.join(words[:30])

    # Tự động chèn câu chỉ định lồng tiếng giới thiệu sản phẩm vào cuối Prompt nếu chưa có
    if voiceover and "lồng tiếng" not in prompt.lower() and "giới thiệu" not in prompt.lower():
        clean_vo = re.sub(r'^(VOICEOVER|KỊCH BẢN LỒNG TIẾNG|LỒNG TIẾNG)\s*:?\s*', '', voiceover.strip(), flags=re.IGNORECASE).strip()
        clean_vo = re.sub(r'#\w+', '', clean_vo).strip()
        if clean_vo:
            prompt = f"{prompt.rstrip('.')} Kết hợp âm thanh nhạc nền quảng cáo TVC nhẹ nhàng tươi mát, sôi động lôi cuốn cùng giọng đọc thuyết minh lồng tiếng Tiếng Việt truyền cảm, âm sắc ấm áp, giàu cảm xúc chuyên nghiệp đọc lời giới thiệu sản phẩm: '{clean_vo}'."

    # Giới hạn chỉ lấy tối đa đúng 5 hashtags
    if hashtags:
        found_tags = re.findall(r'#\w+', hashtags)
        if found_tags:
            hashtags = ' '.join(found_tags[:5])

    return {
        "prompt": prompt,
        "voiceover": voiceover,
        "caption": caption,
        "hashtags": hashtags
    }

def optimize_prompt(
    image_paths: list[Path],
    user_description: str,
    api_key: str | None = None,
    system_instruction: str | None = None,
    meta_prompt_template: str | None = None
) -> dict[str, Any]:
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
                res = parse_prompt_response(meta_str)
                return ensure_caption_and_hashtags(res, user_description)

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
            res_dict = ensure_caption_and_hashtags(res_dict, user_description)
            logger.info(f"Đã tối ưu hóa prompt thành công qua API: {res_dict['prompt'][:60]}...")
            return res_dict
            
        except Exception as e:
            logger.error(f"Lỗi khi gọi API Gemini Developer: {e}. Tự động fallback sang Meta-Prompt.")
            meta_str = _generate_meta_prompt(user_description, len(image_paths) > 1, meta_template)
            return {"prompt": meta_str, "caption": "", "hashtags": "", "is_meta": True, "api_error": True}
    else:
        logger.info("Không có API Key. Sử dụng Meta-Prompt trực tiếp cho Web UI.")
        meta_str = _generate_meta_prompt(user_description, len(image_paths) > 1, meta_template)
        return {"prompt": meta_str, "caption": "", "hashtags": "", "is_meta": True}

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

