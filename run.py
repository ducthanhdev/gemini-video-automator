import uvicorn
import webview
import threading
import time
import socket
import sys
from backend.config import HOST, PORT

def get_local_ip() -> str:
    """Lấy địa chỉ IP mạng nội bộ Wi-Fi."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def start_fastapi_server():
    """Khởi chạy máy chủ FastAPI bằng Uvicorn."""
    logger_config = uvicorn.config.LOGGING_CONFIG
    # Đảm bảo in log ra console gọn gàng
    uvicorn.run(
        "backend.app:app",
        host=HOST,
        port=PORT,
        log_level="info",
        reload=False  # Tắt reload ở môi trường desktop để tránh xung đột luồng
    )

if __name__ == "__main__":
    server_thread = threading.Thread(target=start_fastapi_server, daemon=True)
    server_thread.start()
    
    time.sleep(1.5)
    
    local_url = f"http://127.0.0.1:{PORT}"
    network_ip = get_local_ip()
    network_url = f"http://{network_ip}:{PORT}"
    
    print("\n" + "="*70)
    print("🚀 MÁY CHỦ BATCH VIDEO GEMINI ĐÃ SẴN SÀNG KHỞI CHẠY!")
    print(f"   - Truy cập Desktop: {local_url}")
    print(f"   - Kết nối Wi-Fi Điện thoại: {network_url}")
    print("="*70 + "\n")
    
    webview.create_window(
        title="Gemini Advanced Video Automator",
        url=local_url,
        width=1280,
        height=850,
        min_size=(1000, 700),
        resizable=True,
        text_select=True,
        background_color="#080c14"
    )
    
    try:
        webview.start()
    except Exception as e:
        print(f"\n⚠️ Cảnh báo: Không thể khởi động giao diện Desktop (PyWebview): {e}")
        print("🌐 Đang tự động mở ứng dụng trên trình duyệt web mặc định của bạn...")
        import webbrowser
        webbrowser.open(local_url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nĐang dừng ứng dụng...")
            
    sys.exit(0)
