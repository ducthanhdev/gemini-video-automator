# Gemini Advanced Video Batch Automator

Ứng dụng Desktop giúp tự động hóa quá trình tạo video hàng loạt chất lượng cao từ hình ảnh và mô tả thông qua việc điều khiển trình duyệt tương tác với **Gemini Advanced Web UI**. Hỗ trợ tạo video dài bằng FFmpeg, xem màn hình Live View thời gian thực và đồng bộ hóa điều khiển qua thiết bị di động (Mobile App) bằng mã QR mạng nội bộ.

---

## ✨ Tính năng nổi bật

1. **Tự động hóa trình duyệt (Playwright):** Điều khiển Chrome chạy ngầm truy cập Gemini Advanced Web UI, tải ảnh, chọn tỉ lệ dọc (9:16), gửi prompt và tự động tải video thành phẩm.
2. **Tối ưu hóa Prompt thông minh:**
   - **Cách 1 (Gemini API):** Sử dụng API Key của Gemini Studio (mô hình 2.5 Flash) để tối ưu mô tả tiếng Việt sang Prompt tiếng Anh điện ảnh chỉ trong 1 giây.
   - **Cách 2 (Meta-Prompt):** Tải trực tiếp Meta-Prompt hướng dẫn đặc biệt lên khung chat Web để Gemini tự tối ưu hóa cảnh quay.
3. **Chế độ Video dài (10s / 20s / 30s):**
   - Vượt qua giới hạn 10 giây mặc định của Gemini bằng cách chạy nhiều chu kỳ sinh video liên tiếp.
   - Sử dụng **FFmpeg** tự động trích xuất khung hình cuối (last frame) của clip trước làm đầu vào cho clip sau nhằm đảm bảo tính liền mạch.
   - Hỗ trợ ghép nối video trực tiếp hoặc chuyển tiếp mờ chồng (Crossfade).
4. **Live View & Đăng nhập:** Hiển thị ảnh chụp màn hình trình duyệt Chrome theo thời gian thực trên giao diện điều khiển. Cho phép mở cửa sổ đăng nhập tài khoản Google khi cần thiết.
5. **Giao diện đa thiết bị (Desktop & Mobile):** Giao diện Glassmorphism cao cấp tối ưu hóa cho cả máy tính và màn hình điện thoại di động.
6. **Mã QR mạng nội bộ:** Tự động tạo mã QR để kết nối điện thoại di động (chụp ảnh từ camera điện thoại tải lên app và tải video trực tiếp về album).

---

## 📁 Cấu trúc dự án

```text
tool_create_video/
├── backend/
│   ├── config.py             # Quản lý hằng số, cổng mạng và các thư mục lưu trữ
│   ├── app.py                # Máy chủ API FastAPI chính
│   └── services/
│       ├── automation.py     # Logic Playwright tự động hóa Gemini Web App
│       ├── prompt_optimizer.py # Xử lý tối ưu hóa prompt bằng API/Meta-prompt
│       └── video_processor.py # Xử lý video bằng FFmpeg (ghép nối, trích xuất ảnh)
├── frontend/
│   ├── templates/
│   │   └── index.html        # Giao diện HTML chính (Responsive)
│   └── static/
│       ├── css/
│       │   └── style.css     # Premium Glassmorphic Dark Mode
│       └── js/
│           └── app.js        # Logic điều khiển, API polling, render QR Code
├── storage/                  # Thư mục sinh tự động khi chạy app
│   ├── uploads/              # Nơi lưu trữ ảnh tải lên
│   ├── outputs/              # Nơi lưu trữ video thành phẩm
│   └── browser_profile/      # Lưu phiên làm việc/session đăng nhập Google
├── run.py                    # Entrypoint chạy song song FastAPI + PyWebview
├── build.py                  # Script đóng gói dự án bằng PyInstaller
└── requirements.txt          # Danh sách thư viện Python phụ thuộc
```

---

## 🛠️ Yêu cầu hệ thống

- **Hệ điều hành:** Linux, Windows, macOS.
- **Python:** Phiên bản `>= 3.10`
- **Công cụ:** Đã cài đặt sẵn **FFmpeg** trên hệ thống (để xử lý ghép nối và cắt ảnh video).
- **Trình duyệt:** Google Chrome.

---

## 🚀 Hướng dẫn cài đặt & Khởi chạy

### 1. Cài đặt môi trường ảo và thư viện

```bash
# Di chuyển vào thư mục dự án
cd tool_create_video

# Khởi tạo môi trường ảo Python
python3 -m venv .venv

# Kích hoạt môi trường ảo
source .venv/bin/activate

# Cài đặt các thư viện phụ thuộc
pip install -r requirements.txt
```

### 2. Khởi chạy ứng dụng

Sử dụng trực tiếp đường dẫn của môi trường ảo để khởi chạy giao diện Desktop (không cần lo lắng về việc thiếu thư viện hệ thống):

```bash
.venv/bin/python run.py
```

Khi khởi chạy thành công:
- Một cửa sổ Desktop sẽ tự động mở ra.
- Ứng dụng sẽ hiển thị địa chỉ URL mạng Wi-Fi và mã QR để bạn quét truy cập bằng điện thoại di động.

---

## 📱 Cách kết nối điện thoại di động

1. Đảm bảo điện thoại di động và máy tính chạy ứng dụng đang kết nối **chung một mạng Wi-Fi**.
2. Trên màn hình máy tính, quét mã QR trong mục **"Kết nối điện thoại di động"** bằng camera điện thoại.
3. Giao diện Web tối ưu riêng cho mobile sẽ mở ra. Bạn có thể chọn ảnh từ thư viện điện thoại, viết mô tả và theo dõi quá trình sinh video trực tiếp trên điện thoại của mình.

---

## 📦 Đóng gói ứng dụng thành file chạy độc lập (.exe/.bin)

Để biên dịch toàn bộ dự án thành một file thực thi duy nhất (người dùng cuối không cần cài đặt Python):

```bash
# Chạy script đóng gói
.venv/bin/python build.py
```

Sau khi biên dịch hoàn tất, file chạy nhị phân sẽ được lưu tại:
- **Linux/macOS:** `dist/GeminiVideoAutomator`
- **Windows:** `dist/GeminiVideoAutomator.exe`
