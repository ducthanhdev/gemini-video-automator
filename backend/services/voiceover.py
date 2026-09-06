import asyncio
import logging
import subprocess
from pathlib import Path
import edge_tts
from backend.services.video_qc import probe_media
from backend.services.capcut_tts import generate_capcut_tts, CAPCUT_VOICE_CATALOG

logger = logging.getLogger(__name__)

VOICE_MAPPING = {
    "hoaimy": "vi-VN-HoaiMyNeural",
    "namminh": "vi-VN-NamMinhNeural"
}

def get_audio_duration(audio_path: Path) -> float:
    """Đo thời lượng chính xác của file âm thanh bằng ffprobe (trả về số giây)."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path.resolve())
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(res.stdout.strip())
    except Exception as e:
        logger.warning(f"Không thể đo thời lượng audio {audio_path.name}: {e}")
        return 0.0

async def generate_voiceover(text: str, output_audio_path: Path, voice_key: str = "capcut_cogaighoatngon", rate: str = "+0%") -> bool:
    """
    Sinh file âm thanh mp3 từ văn bản tiếng Việt.
    Hỗ trợ:
    1. Giọng CapCut/TikTok (Cô Gái Hoạt Ngôn, Nhỏ Ngọt Ngào, Thanh Niên Tự Tin, v.v.)
    2. Microsoft Edge Neural TTS (Hoài Mỹ, Nam Minh)
    Tự động Fallback sang Edge-TTS nếu CapCut API không phản hồi.
    """
    try:
        if not text or not text.strip():
            logger.warning("Văn bản lồng tiếng rỗng, bỏ qua sinh giọng đọc.")
            return False

        import re
        clean_text = re.sub(r'^(VOICEOVER|KỊCH BẢN LỒNG TIẾNG|LỒNG TIẾNG|THUYẾT MINH)\s*:?\s*', '', text.strip(), flags=re.IGNORECASE).strip()
        clean_text = re.sub(r'#\w+', '', clean_text).strip()

        output_audio_path.parent.mkdir(parents=True, exist_ok=True)
        v_key = (voice_key or "capcut_cogaighoatngon").lower()

        # 1. Nếu người dùng chọn giọng CapCut / TikTok
        if v_key in CAPCUT_VOICE_CATALOG or v_key.startswith("capcut_") or v_key.startswith("bv"):
            logger.info(f"🎤 Bắt đầu sinh giọng đọc CapCut/TikTok: {v_key}...")
            capcut_success = await generate_capcut_tts(clean_text, v_key, output_audio_path)
            if capcut_success and output_audio_path.exists() and output_audio_path.stat().st_size > 500:
                logger.info(f"✨ Giọng đọc CapCut/TikTok sinh thành công: {output_audio_path.name}")
                return True
            
            logger.warning("⚠️ CapCut TTS không thành công. Tự động fallback sang Microsoft Edge-TTS dự phòng...")
            # Xác định giọng fallback phù hợp theo giới tính
            voice_info = CAPCUT_VOICE_CATALOG.get(v_key, {})
            fallback_voice = "vi-VN-NamMinhNeural" if voice_info.get("gender") == "male" else "vi-VN-HoaiMyNeural"
        else:
            fallback_voice = VOICE_MAPPING.get(v_key, "vi-VN-HoaiMyNeural")

        # 2. Sinh bằng Microsoft Edge Neural TTS (hoặc khi Fallback)
        logger.info(f"Đang sinh giọng đọc Edge-TTS ({fallback_voice}, rate={rate}) cho: '{clean_text[:45]}...'")
        for attempt in range(1, 4):
            try:
                communicate = edge_tts.Communicate(clean_text, fallback_voice, rate=rate)
                await communicate.save(str(output_audio_path.resolve()))
                
                if output_audio_path.exists() and output_audio_path.stat().st_size > 0:
                    logger.info(f"⚡ Sinh giọng đọc Edge-TTS thành công (lần thử {attempt}): {output_audio_path.name}")
                    return True
            except Exception as ex:
                logger.warning(f"Lần thử {attempt}/3 sinh Edge-TTS gặp lỗi: {ex}")
                if attempt < 3:
                    await asyncio.sleep(0.8)
                else:
                    raise ex

        return False
            
    except Exception as e:
        logger.error(f"Lỗi khi sinh giọng đọc AI: {e}", exc_info=True)
        return False

def adjust_audio_duration(audio_path: Path, target_duration: float, max_ratio: float = 0.88) -> bool:
    """
    Kiểm tra thời lượng audio do TTS sinh ra so với thời lượng video:
    - Nếu audio_duration <= target_duration * max_ratio (ví dụ <= 8.8s cho video 10s): Hoàn hảo.
    - Nếu audio_duration > target_duration * max_ratio: Tự động tăng tốc độ audio (atempo)
      để giọng đọc kết thúc gọn gàng trước khi video hết, tránh bị cắt ngang câu.
    """
    try:
        audio_dur = get_audio_duration(audio_path)
        safe_duration = max(2.0, target_duration * max_ratio)
        
        logger.info(f"⏱️ Kiểm tra thời lượng TTS: Audio = {audio_dur:.2f}s | Video an toàn = {safe_duration:.2f}s (Tổng video: {target_duration:.2f}s)")
        
        if audio_dur <= safe_duration:
            return True

        # Cần tăng tốc audio
        speed_factor = audio_dur / safe_duration
        # Giới hạn speed_factor tối đa 1.35x để giọng đọc không bị quá nhanh/méo tiếng
        clamped_factor = min(1.35, max(1.05, speed_factor))
        logger.info(f"⚡ Audio dài hơn ngưỡng an toàn! Tự động tăng tốc atempo={clamped_factor:.2f}x để vừa vặn video...")

        temp_speed = audio_path.with_name(f"speed_{audio_path.name}")
        cmd = [
            "ffmpeg", "-y",
            "-i", str(audio_path.resolve()),
            "-filter:a", f"atempo={clamped_factor:.2f}",
            "-b:a", "192k",
            str(temp_speed.resolve())
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        if temp_speed.exists() and temp_speed.stat().st_size > 0:
            temp_speed.replace(audio_path)
            new_dur = get_audio_duration(audio_path)
            logger.info(f"✅ Đã tối ưu thời lượng audio thành công: {audio_dur:.2f}s -> {new_dur:.2f}s")
            return True
        return False

    except Exception as e:
        logger.warning(f"Lỗi khi điều chỉnh thời lượng audio: {e}")
        return False

async def merge_audio_with_video(video_path: Path, audio_path: Path, output_video_path: Path) -> bool:
    """
    Sử dụng FFmpeg để ghép file âm thanh lồng tiếng vào file video MP4.
    Tự động ducking: Nhạc nền giảm xuống 25%, giọng đọc AI nổi bật 120%.
    """
    try:
        if not video_path.exists():
            logger.error(f"File video không tồn tại: {video_path}")
            return False
        if not audio_path.exists():
            logger.error(f"File âm thanh không tồn tại: {audio_path}")
            return False

        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        temp_output = output_video_path.with_name(f"temp_merged_{output_video_path.name}")

        # Trộn nhạc nền của video gốc [0:a] (giảm volume 0.25) với giọng đọc AI [1:a] (tăng volume 1.2)
        cmd_mix = [
            "ffmpeg", "-y",
            "-i", str(video_path.resolve()),
            "-i", str(audio_path.resolve()),
            "-filter_complex", "[0:a]volume=0.25[bg];[1:a]volume=1.2[vo];[bg][vo]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "0:v:0",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(temp_output.resolve())
        ]

        logger.info("Đang trộn âm thanh lồng tiếng (ducking music 25%, voice 120%) vào video...")
        process = await asyncio.create_subprocess_exec(
            *cmd_mix,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            # Nếu video gốc không chứa luồng âm thanh [0:a], gán trực tiếp luồng audio giọng đọc [1:a:0]
            cmd_fallback = [
                "ffmpeg", "-y",
                "-i", str(video_path.resolve()),
                "-i", str(audio_path.resolve()),
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                str(temp_output.resolve())
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd_fallback,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

        if process.returncode == 0 and temp_output.exists() and temp_output.stat().st_size > 0:
            if temp_output.resolve() != output_video_path.resolve():
                temp_output.replace(output_video_path)
            logger.info(f"🚀 Đã ghép giọng đọc lồng tiếng vào video thành công: {output_video_path.name}")
            return True
        else:
            logger.error(f"Lỗi FFmpeg (Exit code {process.returncode}): {stderr.decode('utf-8', errors='ignore')}")
            if temp_output.exists():
                temp_output.unlink(missing_ok=True)
            return False

    except Exception as e:
        logger.error(f"Lỗi ghép âm thanh vào video: {e}", exc_info=True)
        return False

async def process_video_voiceover(
    video_path: Path,
    voiceover_text: str,
    voice_key: str = "capcut_cogaighoatngon",
    target_duration: float | None = None
) -> bool:
    """
    Quy trình trọn gói: Sinh âm thanh TTS -> Kiểm tra & khớp duration -> Lồng âm thanh vào video MP4.
    """
    if not voiceover_text or not voiceover_text.strip():
        logger.info("Không có kịch bản lồng tiếng, giữ nguyên video gốc.")
        return True

    temp_audio = video_path.with_suffix(".temp_voice.mp3")
    try:
        # Step 1: Sinh file giọng đọc AI
        audio_ok = await generate_voiceover(voiceover_text, temp_audio, voice_key)
        if not audio_ok:
            logger.warning("Không thể sinh file giọng đọc, bỏ qua bước ghép âm thanh.")
            return False

        # Step 2: Xác định duration của video và tối ưu duration của audio nếu cần
        if target_duration is None or target_duration <= 0:
            meta = probe_media(video_path)
            target_duration = meta.get("duration", 10.0)

        # Điều chỉnh audio để kết thúc trước khi video hết (tránh bị cắt cụt câu)
        await asyncio.to_thread(adjust_audio_duration, temp_audio, target_duration, 0.88)

        # Step 3: Ghép audio vào video với ducking
        merge_ok = await merge_audio_with_video(video_path, temp_audio, video_path)
        return merge_ok

    finally:
        # Dọn dẹp file audio tạm
        if temp_audio.exists():
            try:
                temp_audio.unlink(missing_ok=True)
            except Exception:
                pass
