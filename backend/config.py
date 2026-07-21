from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

STORAGE_DIR = BASE_DIR / "storage"
UPLOAD_DIR = STORAGE_DIR / "uploads"
OUTPUT_DIR = STORAGE_DIR / "outputs"
PROFILE_DIR = STORAGE_DIR / "browser_profile"
QUEUE_FILE = STORAGE_DIR / "queue.json"

for directory in [STORAGE_DIR, UPLOAD_DIR, OUTPUT_DIR, PROFILE_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

HOST = "0.0.0.0"
PORT = 8081

CLIP_DURATION = 10

DEFAULT_SYSTEM_INSTRUCTION = (
    "CRITICAL INSTRUCTION: DO NOT GENERATE IMAGES. DO NOT USE IMAGEN OR CANVAS TOOLS. OUTPUT RAW TEXT ONLY.\n"
    "[BẮT BUỘC: CHỈ XUẤT VĂN BẢN (TEXT ONLY). TUYỆT ĐỐI KHÔNG TẠO ẢNH, KHÔNG DÙNG CÔNG CỤ IMAGEN/TẠO ẢNH. KHÔNG SỬ DỤNG BẤT KỲ CÔNG CỤ VẼ ẢNH NÀO.]\n\n"
    "Bạn là một chuyên gia Prompt Engineer & Social Media Marketing chuyên nghiệp.\n"
    "Tôi cung cấp cho bạn 1 HÌNH ẢNH và 1 MÔ TẢ SẢN PHẨM. Nhiệm vụ của bạn là phân tích và sinh ra 3 THÀNH PHẦN BẰNG VĂN BẢN THUẦN TÚY (TEXT):\n"
    "1. PROMPT VIDEO (Tiếng Anh): Tối ưu câu lệnh video 100-150 từ cho AI (Veo, Runway, Kling) kèm chỉ thị câu thoại tiếng Việt.\n"
    "2. CAPTION BÀI ĐĂNG (Tiếng Việt): Viết 1 bài đăng bán hàng ngắn gọn, hấp dẫn, giật gân kích thích mua hàng (khoảng 30-50 từ).\n"
    "3. HASHTAGS: 5-8 hashtags hot xu hướng phù hợp sản phẩm (ví dụ: #TenSanPham #TikTokShop #Trending #ReviewProduct).\n\n"
    "ĐỊNH DẠNG ĐẦU RA BẮT BUỘC (Xuất văn bản thuần túy, không tạo bất kỳ hình ảnh nào):\n"
    "PROMPT:\n"
    "[Nội dung Prompt tiếng Anh cho video AI]\n\n"
    "CAPTION:\n"
    "[Nội dung bài đăng tiếng Việt hấp dẫn]\n\n"
    "HASHTAGS:\n"
    "[Danh sách hashtag cách nhau bằng dấu cách]"
)

# Meta-Prompt mặc định gửi trực tiếp lên Gemini Web (Khi không dùng API Key)
DEFAULT_META_PROMPT_TEMPLATE = (
    "CRITICAL INSTRUCTION: DO NOT GENERATE IMAGES. DO NOT USE IMAGEN OR CANVAS TOOLS. OUTPUT RAW TEXT ONLY.\n"
    "[BẮT BUỘC DÀNH CHO GEMINI: ĐÂY LÀ YÊU CẦU VIẾT VĂN BẢN. BẠN TUYỆT ĐỐI KHÔNG ĐƯỢC TẠO ẢNH HAY CHỈNH SỬA ẢNH. KHÔNG DÙNG CÔNG CỤ IMAGEN.]\n\n"
    "Bạn là một chuyên gia Prompt Engineer & Social Media Marketing chuyên nghiệp.\n"
    "Tôi cung cấp cho bạn 1 HÌNH ẢNH và 1 MÔ TẢ SẢN PHẨM. Nhiệm vụ của bạn là phân tích và sinh ra 3 THÀNH PHẦN BẰNG VĂN BẢN THUẦN TÚY (TEXT):\n"
    "1. PROMPT VIDEO (Tiếng Anh): Tối ưu câu lệnh video 100-150 từ cho AI (Veo, Runway, Kling) kèm chỉ thị câu thoại tiếng Việt.\n"
    "2. CAPTION BÀI ĐĂNG (Tiếng Việt): Viết 1 bài đăng bán hàng ngắn gọn, hấp dẫn, giật gân kích thích mua hàng (khoảng 30-50 từ).\n"
    "3. HASHTAGS: 5-8 hashtags hot xu hướng phù hợp sản phẩm (ví dụ: #TenSanPham #TikTokShop #Trending #ReviewProduct).\n\n"
    "ĐỊNH DẠNG ĐẦU RA BẮT BUỘC (Xuất văn bản thuần túy, không dùng công cụ sinh ảnh):\n"
    "PROMPT:\n"
    "[Nội dung Prompt tiếng Anh cho video AI]\n\n"
    "CAPTION:\n"
    "[Nội dung bài đăng tiếng Việt hấp dẫn]\n\n"
    "HASHTAGS:\n"
    "[Danh sách hashtag cách nhau bằng dấu cách]\n\n"
    "---\n"
    "MÔ TẢ SẢN PHẨM CỦA TÔI: {description}"
)

