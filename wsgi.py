# File: /home/fisika/tiktok-bot/wsgi.py
import sys
import os
from datetime import datetime # Impor datetime untuk timestamp

print(f"[{datetime.now()}] !!! WSGI.PY TELAH DIMUAT DAN DIJALANKAN !!!") # <--- NEW PRINT HERE

# Tambahkan direktori proyek ke sys.path
# Ini penting agar Python dapat menemukan paket 'backend'
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root) # Menggunakan insert(0, ...) untuk memprioritaskan path ini

# Untuk debugging, cetak sys.path yang sedang digunakan
print(f"[{datetime.now()}] DEBUG: sys.path di wsgi.py: {sys.path}")

# Impor objek `app` dari backend.app dan tetapkan ke variabel 'application'
# Pastikan 'backend' dikenali sebagai paket (membutuhkan backend/__init__.py)
try:
    from backend.app import app as application
    print(f"[{datetime.now()}] DEBUG: 'application' berhasil diimpor dari backend.app.")
except ImportError as e:
    print(f"[{datetime.now()}] ERROR: Gagal mengimpor aplikasi dari backend.app: {e}")
    sys.exit(1) # Keluar jika gagal mengimpor aplikasi

# Ini adalah entry point untuk Gunicorn. Gunicorn akan memanggil objek 'application'.
# if __name__ == "__main__": # Baris ini tidak lagi diperlukan saat dijalankan oleh Gunicorn
#     application.run()      # Baris ini tidak lagi diperlukan saat dijalankan oleh Gunicorn