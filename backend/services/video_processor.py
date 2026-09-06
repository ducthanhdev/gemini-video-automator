import subprocess
import tempfile
from pathlib import Path
from typing import Any
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

def get_vietnamese_font_path() -> str:
    """Tìm đường dẫn font chữ hỗ trợ đầy đủ tiếng Việt Unicode trên hệ thống."""
    candidate_fonts = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf"),
        Path("/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
        Path("/usr/share/fonts/truetype/freefont/FreeSans.ttf"),
    ]
    for font in candidate_fonts:
        if font.exists():
            return str(font.resolve())
    return "Sans"

def apply_text_overlay(
    video_path: Path,
    overlay_items: list[dict[str, Any]],
    output_path: Path
) -> bool:
    """
    Vẽ phụ đề/hook nổi bật (On-Screen Text) lên video bằng FFmpeg drawtext filter:
    - Tự động tìm font tiếng Việt Unicode
    - Căn giữa màn hình, đặt ở vùng an toàn (Safe Zone) chuẩn TikTok/Shorts (y=28% chiều cao)
    - Hiển thị theo từng mốc thời gian start -> end của kịch bản
    - Kiểu dáng chuẩn TVC/TikTok: Chữ vàng/trắng tương phản viền đen, nền box bán trong suốt
    """
    if not video_path.exists():
        logger.error(f"File video nguồn không tồn tại: {video_path}")
        return False

    if not overlay_items:
        logger.info("Không có overlay_text, bỏ qua bước vẽ chữ lên video.")
        return True

    font_file = get_vietnamese_font_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output_path.with_name(f"temp_text_{output_path.name}")

    drawtext_filters = []
    colors = ["yellow", "white", "#FFE600", "white"]

    for idx, item in enumerate(overlay_items):
        if not isinstance(item, dict):
            continue
        raw_text = str(item.get("text", "")).strip()
        if not raw_text:
            continue

        start_t = max(0.0, float(item.get("start", 0.0)))
        end_t = max(start_t + 0.5, float(item.get("end", start_t + 3.0)))
        color = colors[idx % len(colors)]

        # Escape các ký tự đặc biệt theo cú pháp FFmpeg drawtext
        clean_text = raw_text.replace('\\', '\\\\').replace("'", "").replace(':', '\\:').replace('%', '\\%')
        
        # Style chuyên nghiệp cho TikTok:
        # Font size 42-44, viền đen 3px, box nền mờ đen 50% bo lề 10px, vị trí y=28%
        flt = (
            f"drawtext=fontfile='{font_file}':text='{clean_text}':"
            f"fontsize=42:fontcolor={color}:borderw=3:bordercolor=black:"
            f"box=1:boxcolor=black@0.52:boxborderw=10:"
            f"x=(w-text_w)/2:y=(h-text_h)*0.28:enable='between(t,{start_t:.2f},{end_t:.2f})'"
        )
        drawtext_filters.append(flt)

    if not drawtext_filters:
        logger.info("Danh sách filter drawtext rỗng, bỏ qua.")
        return True

    filter_complex = ",".join(drawtext_filters)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path.resolve()),
        "-vf", filter_complex,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        str(temp_output.resolve())
    ]

    try:
        logger.info(f"🎨 Đang áp dụng {len(drawtext_filters)} câu text overlay lên video bằng FFmpeg...")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        
        if temp_output.exists() and temp_output.stat().st_size > 50000:
            if temp_output.resolve() != output_path.resolve():
                temp_output.replace(output_path)
            logger.info(f"✨ Đã vẽ On-screen text overlay lên video thành công: {output_path.name}")
            return True
        else:
            logger.error(f"File video sau khi vẽ text không hợp lệ.")
            if temp_output.exists():
                temp_output.unlink(missing_ok=True)
            return False

    except subprocess.CalledProcessError as e:
        logger.error(f"Lỗi FFmpeg drawtext: {e.stderr.decode('utf-8', errors='ignore')}")
        if temp_output.exists():
            temp_output.unlink(missing_ok=True)
        return False
    except Exception as e:
        logger.error(f"Lỗi không xác định khi áp dụng text overlay: {e}")
        if temp_output.exists():
            temp_output.unlink(missing_ok=True)
        return False

