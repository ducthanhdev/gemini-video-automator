"""
Module Technical QC (Quality Control) cho video và âm thanh.
Sử dụng ffprobe và ffmpeg để kiểm tra tính toàn vẹn của tệp video tải về từ AI (Veo)
và video hoàn thiện sau khi ghép nối/lồng tiếng.
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

def probe_media(file_path: Path) -> dict[str, Any]:
    """
    Trích xuất toàn bộ metadata chi tiết của file media (video/audio) qua ffprobe.
    """
    if not file_path.exists():
        return {"error": "File không tồn tại"}

    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(file_path.resolve())
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        data = json.loads(res.stdout)
        
        streams = data.get("streams", [])
        format_info = data.get("format", {})
        
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
        
        # Tính toán fps
        fps = 0.0
        if video_stream:
            r_rate = video_stream.get("r_frame_rate", "0/1")
            try:
                num, den = map(float, r_rate.split("/"))
                fps = round(num / den, 2) if den > 0 else 0.0
            except Exception:
                fps = 0.0

        # Lấy duration ưu tiên từ video stream hoặc format
        duration = 0.0
        try:
            if video_stream and "duration" in video_stream:
                duration = float(video_stream["duration"])
            elif "duration" in format_info:
                duration = float(format_info["duration"])
        except Exception:
            duration = 0.0

        size_bytes = 0
        try:
            size_bytes = int(format_info.get("size", file_path.stat().st_size))
        except Exception:
            size_bytes = file_path.stat().st_size

        return {
            "valid": True,
            "duration": round(duration, 2),
            "size_bytes": size_bytes,
            "has_video": video_stream is not None,
            "has_audio": audio_stream is not None,
            "width": int(video_stream.get("width", 0)) if video_stream else 0,
            "height": int(video_stream.get("height", 0)) if video_stream else 0,
            "video_codec": video_stream.get("codec_name", "") if video_stream else "",
            "audio_codec": audio_stream.get("codec_name", "") if audio_stream else "",
            "fps": fps
        }

    except subprocess.CalledProcessError as e:
        logger.error(f"Lỗi ffprobe khi đọc file {file_path.name}: {e.stderr}")
        return {"valid": False, "error": f"Lỗi ffprobe: {e.stderr}"}
    except Exception as e:
        logger.error(f"Lỗi không xác định khi probe file {file_path.name}: {e}")
        return {"valid": False, "error": str(e)}

def detect_black_frames(video_path: Path, max_allowed_black_ratio: float = 0.3) -> tuple[bool, float]:
    """
    Phát hiện khung hình đen trong video bằng ffmpeg blackdetect filter.
    Trả về: (has_excessive_black: bool, total_black_duration: float)
    """
    try:
        cmd = [
            "ffmpeg",
            "-i", str(video_path.resolve()),
            "-vf", "blackdetect=d=0.5:pic_th=0.96",
            "-an",
            "-f", "null",
            "-"
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stderr_output = res.stderr

        import re
        black_durations = [float(m) for m in re.findall(r'black_duration:([0-9.]+)', stderr_output)]
        total_black = sum(black_durations)

        # Lấy duration video để so tỉ lệ
        info = probe_media(video_path)
        video_dur = info.get("duration", 10.0)
        if video_dur > 0 and (total_black / video_dur) > max_allowed_black_ratio:
            return True, total_black

        return False, total_black
    except Exception as e:
        logger.warning(f"Không thể chạy blackdetect trên {video_path.name}: {e}")
        return False, 0.0

def validate_clip(
    clip_path: Path,
    min_duration: float = 4.0,
    max_duration: float = 20.0,
    min_size_kb: int = 50
) -> tuple[bool, str, dict[str, Any]]:
    """
    Kiểm định kỹ thuật (Technical QC) cho một clip đơn vừa tải về từ AI:
    - Kiểm tra file tồn tại và size >= min_size_kb
    - Video stream tồn tại, đọc được độ phân giải
    - Duration nằm trong khoảng cho phép
    - FPS hợp lệ (> 15 fps)
    - Không bị đen màn hình toàn bộ
    """
    if not clip_path.exists():
        return False, "File clip không tồn tại.", {}

    size_kb = clip_path.stat().st_size / 1024
    if size_kb < min_size_kb:
        return False, f"Dung lượng clip quá nhỏ ({size_kb:.1f} KB < {min_size_kb} KB), nghi vấn file lỗi.", {}

    info = probe_media(clip_path)
    if not info.get("valid", False) or not info.get("has_video", False):
        return False, f"File không chứa luồng video hợp lệ: {info.get('error', 'Unknown')}", info

    duration = info.get("duration", 0.0)
    if duration < min_duration or duration > max_duration:
        return False, f"Thời lượng clip không hợp lệ ({duration}s, yêu cầu {min_duration}s - {max_duration}s).", info

    width = info.get("width", 0)
    height = info.get("height", 0)
    if width <= 0 or height <= 0:
        return False, f"Độ phân giải video không hợp lệ ({width}x{height}).", info

    fps = info.get("fps", 0.0)
    if fps < 15.0:
        return False, f"FPS video quá thấp ({fps} fps < 15 fps).", info

    is_black, black_dur = detect_black_frames(clip_path)
    if is_black:
        return False, f"Phát hiện clip bị đen màn hình quá nhiều ({black_dur:.1f}s).", info

    logger.info(f"✅ Technical QC PASS cho clip {clip_path.name}: {width}x{height} @ {fps}fps, {duration}s, {size_kb:.1f}KB")
    return True, "Clip đạt chuẩn chất lượng kỹ thuật.", info

def validate_final_video(
    video_path: Path,
    expected_duration: float = 10.0,
    has_audio: bool = False
) -> tuple[bool, str, dict[str, Any]]:
    """
    Kiểm định kỹ thuật cho video hoàn chỉnh sau khi ghép và lồng tiếng:
    - Dung lượng >= 100 KB
    - Có luồng video
    - Nếu yêu cầu audio (has_audio=True), phải có luồng audio
    """
    if not video_path.exists():
        return False, "File video hoàn thiện không tồn tại.", {}

    size_kb = video_path.stat().st_size / 1024
    if size_kb < 100:
        return False, f"File video đầu ra quá nhỏ ({size_kb:.1f} KB).", {}

    info = probe_media(video_path)
    if not info.get("valid", False) or not info.get("has_video", False):
        return False, f"Video không hợp lệ: {info.get('error')}", info

    if has_audio and not info.get("has_audio", False):
        return False, "Video thiếu luồng âm thanh theo yêu cầu.", info

    logger.info(f"🎉 Technical QC PASS cho video hoàn thiện {video_path.name}: {info.get('width')}x{info.get('height')}, {info.get('duration')}s, Audio: {info.get('has_audio')}")
    return True, "Video hoàn thiện đạt chuẩn chất lượng kỹ thuật.", info
