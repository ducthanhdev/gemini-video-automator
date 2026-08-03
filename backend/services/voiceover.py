import asyncio
import logging
from pathlib import Path
import edge_tts

logger = logging.getLogger(__name__)

VOICE_MAPPING = {
    "hoaimy": "vi-VN-HoaiMyNeural",
    "namminh": "vi-VN-NamMinhNeural"
}

async def generate_voiceover(text: str, output_audio_path: Path, voice_key: str = "hoaimy") -> bool:
    """
    Sinh file âm thanh mp3 từ văn bản tiếng Việt bằng Microsoft Edge Neural TTS.
    """
    try:
        if not text or not text.strip():
            logger.warning("Văn bản lồng tiếng rỗng, bỏ qua sinh giọng đọc.")
            return False

        voice_name = VOICE_MAPPING.get(voice_key.lower(), "vi-VN-HoaiMyNeural")
        clean_text = text.strip()
        
        logger.info(f"Đang sinh giọng đọc AI ({voice_name}) cho văn bản: '{clean_text[:40]}...'")
        
        output_audio_path.parent.mkdir(parents=True, exist_ok=True)
        communicate = edge_tts.Communicate(clean_text, voice_name)
        await communicate.save(str(output_audio_path.resolve()))
        
        if output_audio_path.exists() and output_audio_path.stat().st_size > 0:
            logger.info(f"⚡ Sinh giọng đọc AI thành công: {output_audio_path.name}")
            return True
        else:
            logger.error("File âm thanh đầu ra có dung lượng bằng 0.")
            return False
            
    except Exception as e:
        logger.error(f"Lỗi khi sinh giọng đọc AI bằng edge-tts: {e}", exc_info=True)
        return False

async def merge_audio_with_video(video_path: Path, audio_path: Path, output_video_path: Path) -> bool:
    """
    Sử dụng FFmpeg để ghép file âm thanh lồng tiếng vào file video MP4.
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

        # Lệnh FFmpeg: Kết hợp video và audio, tự động căn chỉnh thời lượng
        # -c:v copy : Giữ nguyên định dạng video (không mã hóa lại, cực nhanh)
        # -c:a aac : Mã hóa audio chuẩn AAC
        # -shortest : Căn theo file có thời lượng ngắn hơn hoặc giữ vừa vặn
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path.resolve()),
            "-i", str(audio_path.resolve()),
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(temp_output.resolve())
        ]

        logger.info("Đang tiến hành ghép âm thanh lồng tiếng vào video bằng FFmpeg...")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0 and temp_output.exists() and temp_output.stat().st_size > 0:
            # Thay thế file cũ bằng file đã ghép âm thanh
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

async def process_video_voiceover(video_path: Path, voiceover_text: str, voice_key: str = "hoaimy") -> bool:
    """
    Quy trình trọn gói: Sinh âm thanh TTS -> Lồng âm thanh vào video MP4.
    """
    if not voiceover_text or not voiceover_text.strip():
        logger.info("Không có kịch bản lồng tiếng, giữ nguyên video gốc.")
        return True

    temp_audio = video_path.with_suffix(".temp_voice.mp3")
    try:
        # Step 1: Generate audio
        audio_ok = await generate_voiceover(voiceover_text, temp_audio, voice_key)
        if not audio_ok:
            logger.warning("Không thể sinh file giọng đọc, bỏ qua bước ghép âm thanh.")
            return False

        # Step 2: Merge audio into video
        merge_ok = await merge_audio_with_video(video_path, temp_audio, video_path)
        return merge_ok

    finally:
        # Cleanup temp audio file
        if temp_audio.exists():
            try:
                temp_audio.unlink(missing_ok=True)
            except Exception:
                pass
