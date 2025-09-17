# File: /home/fisika/tiktok-bot/wsgi.py
import sys
import os

# Tambahkan direktori proyek ke sys.path
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root) # Menggunakan insert(0, ...) untuk memprioritaskan path ini

# Impor objek `app` dari backend.app dan tetapkan ke variabel 'application'
from backend.app import app as application # <--- BARIS INI YANG BERUBAH

# Ini adalah entry point untuk Gunicorn
# if __name__ == "__main__": # Baris ini tidak lagi diperlukan saat dijalankan oleh Gunicorn
#     application.run()      # Baris ini tidak lagi diperlukan saat dijalankan oleh Gunicorn