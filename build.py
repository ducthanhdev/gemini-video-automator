import os
import sys
import subprocess
import shutil

def clean_previous_builds():
    """Dọn dẹp các thư mục build cũ để tránh xung đột dữ liệu."""
    dirs_to_clean = ["build", "dist"]
    files_to_clean = ["GeminiVideoAutomator.spec"]
    
    for d in dirs_to_clean:
        if os.path.exists(d):
            print(f"🧹 Đang xóa thư mục: {d}...")
            shutil.rmtree(d)
            
    for f in files_to_clean:
        if os.path.exists(f):
            print(f"🧹 Đang xóa file: {f}...")
            os.remove(f)

def run_pyinstaller():
    """Chạy lệnh đóng gói PyInstaller."""
    separator = ";" if sys.platform.startswith("win") else ":"
    
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        f"--add-data=frontend/templates{separator}frontend/templates",
        f"--add-data=frontend/static{separator}frontend/static",
        "--name=GeminiVideoAutomator",
        "run.py"
    ]
    
    print("\n📦 BẮT ĐẦU ĐÓNG GÓI ỨNG DỤNG BẰNG PYINSTALLER...")
    print(f"   Lệnh thực thi: {' '.join(cmd)}\n")
    
    try:
        subprocess.run(cmd, check=True)
        print("\n🎉 ĐÓNG GÓI THÀNH CÔNG!")
        print(f"   File chạy nhị phân đã được lưu tại: {os.path.abspath('dist/GeminiVideoAutomator')}\n")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ LỖI ĐÓNG GÓI: Lệnh pyinstaller trả về mã lỗi {e.returncode}")
        sys.exit(1)
    except FileNotFoundError:
        print("\n❌ LỖI: Không tìm thấy thư viện PyInstaller. Hãy chạy 'pip install pyinstaller' trước.")
        sys.exit(1)

if __name__ == "__main__":
    clean_previous_builds()
    run_pyinstaller()
