import json
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

def generate_smart_overlay_text(user_description: str, prompt: str = "") -> list[dict[str, Any]]:
    """Tạo bộ text overlay (phụ đề chữ nổi bật trên video) gồm 3 nhịp chuẩn TikTok e-commerce."""
    clean_desc = re.sub(r'https?://\S+', '', user_description or "").strip()
    clean_desc = re.sub(r'[#\*\_\[\]]', '', clean_desc).strip()
    first_line = clean_desc.split('\n')[0].strip() if clean_desc else ""
    prod_name = first_line[:40] if first_line else "sản phẩm hot"

    return [
        {"text": f"Bí quyết sở hữu {prod_name}?", "start": 0.5, "end": 3.0},
        {"text": "Thiết kế thông minh - Cực kỳ tiện lợi!", "start": 3.0, "end": 7.0},
        {"text": "Bấm ngay giỏ hàng nhận ưu đãi! 🛒", "start": 7.0, "end": 9.5}
    ]

def clean_visual_prompt(prompt: str) -> str:
    """
    Làm sạch visual prompt cho AI Video (Veo/Runway):
    1. Lọc bỏ toàn bộ chỉ dẫn âm thanh, nhạc nền, giọng đọc lồng tiếng (tránh làm phân tán model video).
    2. Chuẩn hóa bộ lọc nhạy cảm (safety filter).
    3. Xóa các phân đoạn Scene 1, Scene 2 thừa.
    """
    if not prompt:
        return ""

    p = prompt.strip().strip('"').strip("'").strip()

    # 1. Loại bỏ các đoạn văn mô tả âm thanh/nhạc nền/lồng tiếng nếu có
    audio_patterns = [
        r'Kết hợp âm thanh[^\.\n]*(\.|$)',
        r'nhạc nền quảng cáo[^\.\n]*(\.|$)',
        r'nhạc nền TVC[^\.\n]*(\.|$)',
        r'giọng đọc thuyết minh[^\.\n]*(\.|$)',
        r'thuyết minh lồng tiếng[^\.\n]*(\.|$)',
        r'lồng tiếng Tiếng Việt[^\.\n]*(\.|$)',
        r'âm thanh sống động[^\.\n]*(\.|$)',
        r'đọc lời giới thiệu[^\.\n]*(\.|$)',
        r'VOICEOVER:?.*$',
        r'KỊCH BẢN LỒNG TIẾNG:?.*$'
    ]
    for pattern in audio_patterns:
        p = re.sub(pattern, '', p, flags=re.IGNORECASE)

    # 2. Xóa định dạng Scene 1, Scene 2
    if "Scene 1" in p or "Scene 2" in p:
        p = re.sub(r'Scene\s*\d+:[^\n]*', '', p, flags=re.IGNORECASE).strip()
        p = re.sub(r'\n+', ' ', p).strip()

    # 3. Tự động thay thế từ ngữ nhạy cảm dính bộ lọc an toàn của Google Veo
    sensitive_replacements = [
        (r'chai\s+dung\s*dịch\s*vệ\s*sinh\s*(phụ\s*nữ)?\s*(pH\s*Care)?', 'chai gel chăm sóc da pH Care'),
        (r'dung\s*dịch\s*vệ\s*sinh\s*(phụ\s*nữ)?\s*(pH\s*Care)?', 'gel chăm sóc da pH Care'),
        (r'vệ\s*sinh\s*phụ\s*nữ', 'chăm sóc da tươi mát'),
        (r'vùng\s*kín', 'vùng da nhạy cảm'),
        (r'kháng\s*khuẩn', 'làm sạch dịu nhẹ'),
    ]
    for pat, rep in sensitive_replacements:
        p = re.sub(pat, rep, p, flags=re.IGNORECASE)

    # Làm sạch khoảng trắng và dấu câu thừa
    p = re.sub(r'\s+', ' ', p).strip()
    p = re.sub(r'^[,\.\-\s]+|[,\-\s]+$', '', p).strip()
    if p and not p.endswith('.'):
        p += '.'

    return p

def ensure_caption_and_hashtags(data: dict[str, Any], user_description: str = "") -> dict[str, Any]:
    """Đảm bảo chắc chắn dữ liệu có đầy đủ prompt, voiceover, overlay_text, caption và hashtags không bị rỗng."""
    prompt = clean_visual_prompt(data.get("prompt") or "")
    voiceover = (data.get("voiceover") or "").strip()
    caption = (data.get("caption") or "").strip()
    hashtags = (data.get("hashtags") or "").strip()
    overlay_text = data.get("overlay_text")
    
    # Chuẩn hóa voiceover: loại bỏ prefix nếu còn sót
    voiceover = re.sub(r'^(VOICEOVER|KỊCH BẢN LỒNG TIẾNG|LỒNG TIẾNG|THUYẾT MINH)\s*:?\s*', '', voiceover, flags=re.IGNORECASE).strip()
    voiceover = re.sub(r'#\w+', '', voiceover).strip()

    # Tối ưu độ dài voiceover: cho video 8-10s, voiceover lý tưởng là 15-22 từ (tối đa 25 từ)
    words = voiceover.split()
    if len(words) > 25:
        voiceover = ' '.join(words[:22])
        if not voiceover.endswith(('.', '!', '?')):
            voiceover += '!'

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
        found_tags = re.findall(r'#\w+', hashtags)
        if found_tags:
            hashtags = ' '.join(found_tags[:5])
            
    # Nếu voiceover còn trống, tự động trích xuất ngắn gọn (15-20 từ) từ caption
    if not voiceover:
        clean_src = re.sub(r'#\w+', '', caption).strip()
        clean_src = re.sub(r'PROMPT:|CAPTION:|HASHTAGS:|VOICEOVER:', '', clean_src, flags=re.IGNORECASE).strip()
        c_words = clean_src.split()
        if c_words:
            voiceover = ' '.join(c_words[:20])
            if not voiceover.endswith(('.', '!', '?')):
                voiceover += '!'

    # Đảm bảo có overlay_text hợp lệ
    if not isinstance(overlay_text, list) or len(overlay_text) == 0:
        overlay_text = generate_smart_overlay_text(user_description, prompt)
    else:
        # Chuẩn hóa cấu trúc từng mục overlay
        normalized_overlay = []
        for item in overlay_text:
            if isinstance(item, dict) and "text" in item:
                t = str(item.get("text", "")).strip()
                if t:
                    s = float(item.get("start", 0.0))
                    e = float(item.get("end", s + 3.0))
                    normalized_overlay.append({"text": t, "start": s, "end": e})
            elif isinstance(item, str) and item.strip():
                normalized_overlay.append({"text": item.strip(), "start": 0.0, "end": 3.0})
        overlay_text = normalized_overlay if normalized_overlay else generate_smart_overlay_text(user_description, prompt)

    return {
        "prompt": prompt,
        "voiceover": voiceover,
        "overlay_text": overlay_text,
        "caption": caption,
        "hashtags": hashtags
    }

def parse_prompt_response(text: str) -> dict[str, Any]:
    """
    Phân tách văn bản phản hồi từ Gemini (hỗ trợ cả định dạng JSON lẫn text có nhãn).
    Đầu ra chuẩn: prompt (thuần visual, sạch audio), voiceover (15-22 từ), overlay_text, caption, hashtags.
    """
    if not text:
        return {"prompt": "", "voiceover": "", "overlay_text": [], "caption": "", "hashtags": ""}
        
    text = text.strip()
    
    # 1. Thử parse dạng JSON trước (Gemini 2.5 Flash có thể trả về JSON trực tiếp hoặc trong ```json ... ```)
    json_candidate = ""
    if "```json" in text:
        match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
        if match:
            json_candidate = match.group(1)
    elif text.startswith("{") and text.endswith("}"):
        json_candidate = text
    elif "{" in text and "}" in text:
        # Tìm block json đầu tiên
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        if start_idx != -1 and end_idx > start_idx:
            json_candidate = text[start_idx:end_idx + 1]

    if json_candidate:
        try:
            parsed = json.loads(json_candidate)
            if isinstance(parsed, dict):
                prompt = str(parsed.get("prompt") or parsed.get("video_prompt") or "").strip()
                voiceover = str(parsed.get("voiceover") or parsed.get("voice_over") or "").strip()
                caption = str(parsed.get("caption") or "").strip()
                raw_tags = parsed.get("hashtags") or ""
                if isinstance(raw_tags, list):
                    hashtags = " ".join([f"#{t.lstrip('#')}" for t in raw_tags])
                else:
                    hashtags = str(raw_tags).strip()
                overlay_text = parsed.get("overlay_text") or parsed.get("overlay") or []

                return {
                    "prompt": clean_visual_prompt(prompt),
                    "voiceover": voiceover,
                    "overlay_text": overlay_text,
                    "caption": caption,
                    "hashtags": hashtags
                }
        except Exception as e:
            logger.debug(f"Không thể parse text dưới dạng JSON: {e}. Chuyển sang parse regex truyền thống.")

    # 2. Parse dạng Text với các nhãn: PROMPT, VOICEOVER, OVERLAY_TEXT, CAPTION, HASHTAGS
    prompt_match = re.search(r'(?:\*\*|#|\d+\.\s*)?(?:PROMPT(?:\s*VIDEO)?|CÂU\s*LỆNH|PROMPT)(?:\s*\(.*?\))?(?:\*\*|:|\s)*\n?', text, re.IGNORECASE)
    voiceover_match = re.search(r'(?:\*\*|#|\d+\.\s*)?(?:VOICEOVER|KỊCH\s*BẢN\s*LỒNG\s*TIẾNG|LỒNG\s*TIẾNG|THUYẾT\s*MINH|VOICE\s*OVER)(?:\s*\(.*?\))?(?:\*\*|:|\s)*\n?', text, re.IGNORECASE)
    overlay_match = re.search(r'(?:\*\*|#|\d+\.\s*)?(?:OVERLAY_TEXT|OVERLAY|TEXT\s*OVERLAY|PHỤ\s*ĐỀ|CHỮ\s*MÀN\s*HÌNH)(?:\s*\(.*?\))?(?:\*\*|:|\s)*\n?', text, re.IGNORECASE)
    caption_match = re.search(r'(?:\*\*|#|\d+\.\s*)?(?:CAPTION(?:\s*BÀI\s*ĐĂNG)?|BÀI\s*ĐĂNG|NỘI\s*DUNG\s*BÀI\s*VIẾT|BÀI\s*VIẾT|TIÊU\s*ĐỀ\s*BÀI\s*ĐĂNG)(?:\s*\(.*?\))?(?:\*\*|:|\s)*\n?', text, re.IGNORECASE)
    hashtags_match = re.search(r'(?:\*\*|#|\d+\.\s*)?(?:HASHTAGS?|THẺ\s*HASHTAGS?|THẺ\s*TAGS?|TAGS?)(?:\s*\(.*?\))?(?:\*\*|:|\s)*\n?', text, re.IGNORECASE)

    prompt = text
    voiceover = ""
    caption = ""
    hashtags = ""
    raw_overlay = ""

    matches = []
    if prompt_match:
        matches.append(('prompt', prompt_match.start(), prompt_match.end()))
    if voiceover_match:
        matches.append(('voiceover', voiceover_match.start(), voiceover_match.end()))
    if overlay_match:
        matches.append(('overlay_text', overlay_match.start(), overlay_match.end()))
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
        raw_overlay = sections.get('overlay_text', '')
        caption = sections.get('caption', '')
        hashtags = sections.get('hashtags', '')

    # Làm sạch ký tự thừa
    voiceover = re.sub(r'^\*+|\*+$', '', voiceover).strip()
    caption = re.sub(r'^\*+|\*+$', '', caption).strip()
    hashtags = re.sub(r'^\*+|\*+$', '', hashtags).strip()

    # Trích xuất overlay_text từ raw_overlay nếu có
    overlay_text = []
    if raw_overlay:
        # Thử parse JSON array
        try:
            arr_match = re.search(r'\[.*?\]', raw_overlay, re.DOTALL)
            if arr_match:
                parsed_arr = json.loads(arr_match.group(0))
                if isinstance(parsed_arr, list):
                    overlay_text = parsed_arr
        except Exception:
            pass

        # Fallback: parse từng dòng
        if not overlay_text:
            lines = [line.strip('- *•') for line in raw_overlay.split('\n') if line.strip()]
            for line in lines:
                time_m = re.search(r'(\d+(?:\.\d+)?)\s*s?\s*-\s*(\d+(?:\.\d+)?)\s*s?:\s*(.*)', line)
                if time_m:
                    overlay_text.append({
                        "start": float(time_m.group(1)),
                        "end": float(time_m.group(2)),
                        "text": time_m.group(3).strip()
                    })
                elif line:
                    overlay_text.append({"text": line, "start": 0.0, "end": 3.0})

    # Nếu chưa có Voiceover, tự động trích xuất đoạn kịch bản ngắn (15-20 từ) từ Caption
    if not voiceover:
        target_src = caption if caption else text
        clean_src = re.sub(r'#\w+', '', target_src).strip()
        clean_src = re.sub(r'PROMPT:|CAPTION:|HASHTAGS:|VOICEOVER:|OVERLAY_TEXT:', '', clean_src, flags=re.IGNORECASE).strip()
        words = clean_src.split()
        if words:
            voiceover = ' '.join(words[:20])

    # LÀM SẠCH PROMPT: Veo prompt chỉ tập trung 100% vào visual, TUYỆT ĐỐI KHÔNG GHÉP ÂM THANH!
    prompt = clean_visual_prompt(prompt)

    # Giới hạn chỉ lấy tối đa đúng 5 hashtags
    if hashtags:
        found_tags = re.findall(r'#\w+', hashtags)
        if found_tags:
            hashtags = ' '.join(found_tags[:5])

    return {
        "prompt": prompt,
        "voiceover": voiceover,
        "overlay_text": overlay_text,
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
    Trả về dict chứa: prompt (visual sạch), voiceover, overlay_text, caption, hashtags.
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
                    max_output_tokens=800,
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

