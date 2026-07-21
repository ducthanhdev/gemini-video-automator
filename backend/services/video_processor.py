import subprocess
import tempfile
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def get_video_duration(video_path: Path) -> float:
    """Lấy thời lượng chính xác của video bằng ffprobe (trả về giây)."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(result.stdout.strip())
    except Exception as e:
        logger.error(f"Lỗi khi lấy thời lượng video {video_path}: {e}")
        # Mặc định trả về 8s nếu có lỗi xảy ra
        return 8.0

def extract_last_frame(video_path: Path, output_image_path: Path) -> bool:
    """Trích xuất khung hình cuối cùng của video lưu thành ảnh tĩnh."""
    try:
        # Sử dụng -sseof -0.1 để seek đến 0.1s cuối cùng của video và lấy 1 frame
        cmd = [
            "ffmpeg", "-y",
            "-sseof", "-0.1",
            "-i", str(video_path),
            "-update", "1",
            "-q:v", "2",
            "-vframes", "1",
            str(output_image_path)
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        logger.info(f"Đã trích xuất khung hình cuối của {video_path} thành {output_image_path}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Lỗi FFmpeg khi trích xuất khung hình cuối: {e.stderr.decode('utf-8', errors='ignore')}")
        return False
    except Exception as e:
        logger.error(f"Lỗi không xác định khi trích xuất khung hình cuối: {e}")
        return False

def concatenate_videos_direct(video_paths: list[Path], output_path: Path) -> bool:
    """Ghép nối trực tiếp các video (không hiệu ứng) sử dụng concat demuxer (lossless & nhanh)."""
    if not video_paths:
        return False
    if len(video_paths) == 1:
        # Copy file trực tiếp
        try:
            import shutil
            shutil.copy2(video_paths[0], output_path)
            return True
        except Exception as e:
            logger.error(f"Lỗi sao chép file video đơn: {e}")
            return False

    # Tạo file danh sách tạm thời cho concat demuxer
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        list_file_path = Path(f.name)
        for path in video_paths:
            # Viết đường dẫn tuyệt đối dạng an toàn cho FFmpeg
            f.write(f"file '{path.resolve()}'\n")

    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_file_path),
            "-c", "copy",
            str(output_path)
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        logger.info(f"Đã ghép nối trực tiếp {len(video_paths)} video thành {output_path}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Lỗi FFmpeg khi ghép nối video trực tiếp: {e.stderr.decode('utf-8', errors='ignore')}")
        return False
    finally:
        # Xóa file danh sách tạm
        if list_file_path.exists():
            list_file_path.unlink()

def concatenate_videos_xfade(video_paths: list[Path], output_path: Path, transition_duration: float = 0.5) -> bool:
    """Ghép nối các video sử dụng hiệu ứng crossfade (yêu cầu re-encode sang H264 yuv420p)."""
    if not video_paths:
        return False
    if len(video_paths) == 1:
        return concatenate_videos_direct(video_paths, output_path)

    # Lấy thời lượng của từng video để tính offset chính xác
    durations = [get_video_duration(p) for p in video_paths]
    
    # Xây dựng các tham số đầu vào cho FFmpeg
    cmd = ["ffmpeg", "-y"]
    for path in video_paths:
        cmd.extend(["-i", str(path)])

    # Xây dựng filter complex cho hiệu ứng xfade
    # Ví dụ với 3 video:
    # [0:v][1:v]xfade=transition=fade:duration=0.5:offset=7.5[v1];
    # [v1][2:v]xfade=transition=fade:duration=0.5:offset=15.0[vout]
    filter_parts = []
    current_input = "[0:v]"
    current_offset = 0.0

    for i in range(1, len(video_paths)):
        next_input = f"[{i}:v]"
        # Offset cho transition i là: tổng thời lượng của các video trước đó trừ đi số lần chuyển cảnh
        # Cụ thể: offset = thời lượng video trước đó - transition_duration
        current_offset += durations[i-1] - transition_duration
        
        output_label = f"[v{i}]" if i < len(video_paths) - 1 else "[vout]"
        filter_parts.append(
            f"{current_input}{next_input}xfade=transition=fade:duration={transition_duration}:offset={current_offset:.3f}{output_label}"
        )
        current_input = f"[v{i}]"

    filter_complex = ";".join(filter_parts)
    
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        str(output_path)
    ])

    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        logger.info(f"Đã ghép nối crossfade {len(video_paths)} video thành {output_path}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Lỗi FFmpeg khi ghép nối crossfade: {e.stderr.decode('utf-8', errors='ignore')}")
        return False
    except Exception as e:
        logger.error(f"Lỗi không xác định khi ghép nối crossfade: {e}")
        return False
