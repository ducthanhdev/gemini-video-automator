import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Dict, Optional, Tuple
import requests

try:
    from capcut_tts_api import CapCutClient
except ImportError:
    CapCutClient = None

logger = logging.getLogger(__name__)

# Danh mục các giọng CapCut Tiếng Việt phổ biến và viral nhất trên TikTok
CAPCUT_VOICE_CATALOG: Dict[str, Dict[str, str]] = {
    "capcut_cogaighoatngon": {
        "voice_type": "BV074_streaming",
        "resource_id": "7102355709945188865",
        "display_name": "Cô Gái Hoạt Ngôn (TikTok Bán Hàng Viral)",
        "gender": "female"
    },
    "capcut_nhongotngao": {
        "voice_type": "BV421_vivn_streaming",
        "resource_id": "7252594014782755330",
        "display_name": "Nhỏ Ngọt Ngào (Mỹ phẩm, Decor, Dễ thương)",
        "gender": "female"
    },
    "capcut_thanhnientutin": {
        "voice_type": "BV075_streaming",
        "resource_id": "7102355803792740865",
        "display_name": "Thanh Niên Tự Tin (Công nghệ, Gia dụng, Năng động)",
        "gender": "male"
    },
    "capcut_nuphothong": {
        "voice_type": "vi_female_huong",
        "resource_id": "7264854897953083905",
        "display_name": "Giọng Nữ Phổ Thông (Chị Google CapCut)",
        "gender": "female"
    },
    "capcut_namtram": {
        "voice_type": "multi_male_felipe_uranus_bigtts",
        "resource_id": "7637456729696996628",
        "display_name": "Giọng Nam Trầm (Điện ảnh, Uy tín)",
        "gender": "male"
    },
    "capcut_reviewphim": {
        "voice_type": "multi_female_richgirl_uranus_bigtts",
        "resource_id": "7637460351541447956",
        "display_name": "Review Phim New (Lôi cuốn, Nhấn nhá)",
        "gender": "female"
    },
    "capcut_banmai": {
        "voice_type": "multi_female_yangguangnv_uranus_bigtts",
        "resource_id": "7637456432522218773",
        "display_name": "Ban Mai (Tươi tắn, Năng lượng)",
        "gender": "female"
    },
    "capcut_mai": {
        "voice_type": "BV562_streaming",
        "resource_id": "7483736254694035984",
        "display_name": "Mai (Trầm lắng, Nhẹ nhàng)",
        "gender": "female"
    },
    "capcut_giongge": {
        "voice_type": "BV074_streaming_dsp",
        "resource_id": "7550087831092251920",
        "display_name": "Giọng Bé (Đáng yêu, Hoạt hình)",
        "gender": "female"
    },
    "capcut_vietmeo": {
        "voice_type": "BV075_streaming_vibrato_dsp",
        "resource_id": "7569450639810465040",
        "display_name": "Việt Méo (Hài hước, Meme)",
        "gender": "male"
    },
    "capcut_bantin1": {
        "voice_type": "multi_female_quanweinv_uranus_bigtts",
        "resource_id": "7637458743197732117",
        "display_name": "Bản Tin 1 (Thời sự, Trang trọng)",
        "gender": "female"
    },
    "capcut_sunnyidol": {
        "voice_type": "multi_female_kiwi_uranus_bigtts",
        "resource_id": "7637457995882089749",
        "display_name": "Sunny Idol (Thần tượng, Trẻ trung)",
        "gender": "female"
    },
    "capcut_gaimoilon": {
        "voice_type": "multi_female_peiqi_uranus_bigtts",
        "resource_id": "7637458789033151751",
        "display_name": "Gái Mới Lớn (Ngây thơ, Trong trẻo)",
        "gender": "female"
    },
    "capcut_robot": {
        "voice_type": "BV075_streaming_robot_dsp",
        "resource_id": "7538698409633516816",
        "display_name": "Robot VN (Công nghệ, Sci-Fi)",
        "gender": "male"
    }
}

def generate_capcut_tts_sync(
    text: str,
    voice_key: str,
    output_audio_path: Path,
    rate: str = "1.0",
    max_retries: int = 2
) -> bool:
    """
    Sinh file âm thanh từ văn bản bằng CapCut / TikTok TTS API (chạy đồng bộ).
    Đã xử lý sửa lỗi kiểm tra status 'succeed' và tải file trực tiếp từ CDN TikTok.
    """
    if CapCutClient is None:
        logger.error("Thư viện capcut-tts-api chưa được cài đặt.")
        return False

    voice_info = CAPCUT_VOICE_CATALOG.get(voice_key)
    if not voice_info:
        # Nếu truyền trực tiếp voice_type của CapCut (vd: BV074_streaming)
        voice_type = voice_key
        resource_id = None
        display_name = voice_key
    else:
        voice_type = voice_info["voice_type"]
        resource_id = voice_info.get("resource_id")
        display_name = voice_info["display_name"]

    import re
    clean_text = re.sub(r'^(VOICEOVER|KỊCH BẢN LỒNG TIẾNG|LỒNG TIẾNG|THUYẾT MINH)\s*:?\s*', '', text.strip(), flags=re.IGNORECASE).strip()
    clean_text = re.sub(r'#\w+', '', clean_text).strip()

    if not clean_text:
        logger.warning("Văn bản TTS rỗng sau khi làm sạch.")
        return False

    output_audio_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"🎙️ Đang gọi CapCut/TikTok TTS: Giọng='{display_name}' ({voice_type}) cho text: '{clean_text[:45]}...'")

    for attempt in range(1, max_retries + 1):
        try:
            client = CapCutClient()
            create_res = client.create_tts_task(
                texts=clean_text,
                voice=voice_type,
                resource_id=resource_id,
                rate=rate
            )

            tasks = (create_res.get("data") or {}).get("tasks") or []
            if not tasks:
                logger.warning(f"CapCut API không trả về task (Lần {attempt}): {create_res}")
                time.sleep(1.0)
                continue

            task_id = tasks[0]["id"]
            token = tasks[0]["token"]

            # Polling tối đa 15 giây (CapCut thường xử lý trong 1-2 giây)
            audio_download_url = None
            for _ in range(15):
                query_res = client.query_tts_task(task_id, token)
                query_tasks = (query_res.get("data") or {}).get("tasks") or []
                if query_tasks:
                    status = query_tasks[0].get("status")
                    if status in ("succeed", "success"):
                        payload_str = query_tasks[0].get("payload", "{}")
                        try:
                            payload = json.loads(payload_str)
                            subtitles = payload.get("audio_subtitles", [])
                            if subtitles and subtitles[0].get("speech_url"):
                                audio_download_url = subtitles[0]["speech_url"]
                                break
                        except Exception as pe:
                            logger.warning(f"Không thể parse payload CapCut: {pe}")
                    elif status == "failed":
                        logger.warning(f"CapCut Task báo lỗi: {query_tasks[0]}")
                        break
                time.sleep(0.8)

            if not audio_download_url:
                logger.warning(f"Không nhận được URL audio từ CapCut sau khi polling (Lần {attempt}).")
                continue

            # Tải audio từ CDN
            resp = requests.get(
                audio_download_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                timeout=20
            )
            if resp.status_code == 200 and len(resp.content) > 500:
                with open(output_audio_path, "wb") as f:
                    f.write(resp.content)
                logger.info(f"✅ Tải giọng đọc CapCut/TikTok thành công: {output_audio_path.name} ({len(resp.content)} bytes)")
                return True
            else:
                logger.warning(f"Tải audio từ CDN thất bại: HTTP {resp.status_code}, size={len(resp.content)}")

        except Exception as e:
            logger.warning(f"Lỗi khi gọi CapCut TTS (Lần {attempt}/{max_retries}): {e}")
            time.sleep(1.0)

    return False

async def generate_capcut_tts(
    text: str,
    voice_key: str,
    output_audio_path: Path,
    rate: str = "1.0",
    max_retries: int = 2
) -> bool:
    """Gọi generate_capcut_tts_sync bất đồng bộ trong asyncio loop executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        generate_capcut_tts_sync,
        text,
        voice_key,
        output_audio_path,
        rate,
        max_retries
    )
