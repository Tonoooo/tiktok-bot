import os
import sys
import redis
from rq import Queue
from datetime import datetime, timedelta

# Tambahkan direktori proyek ke sys.path agar impor lokal berfungsi
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if project_root not in sys.path:
    sys.path.append(project_root)

# Import bot functions
from akses_komen.qr_login_service import generate_qr_and_wait_for_login
from akses_komen.bot import run_tiktok_bot_task
from akses_komen.api_client import APIClient # Bot functions still need APIClient

# --- Konfigurasi Redis & RQ Queue (Harus sama dengan di app.py) ---
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0') # Menggunakan variabel lingkungan atau default
redis_conn = redis.from_url(REDIS_URL)
q = Queue(connection=redis_conn)

# --- Fungsi Pembungkus Tugas untuk RQ Worker ---

def enqueue_qr_login_task(user_id: int):
    """
    Menempatkan tugas login QR code ke antrean RQ.
    Bot worker akan mengambil dan menjalankan tugas generate_qr_and_wait_for_login.
    """
    # NOTE: generate_qr_and_wait_for_login akan memanggil APIClient di dalamnya.
    # Kita perlu memastikan APIClient diakses dari konteks Flask (jika dibutuhkan)
    # atau diinisialisasi di dalam worker environment (sudah dilakukan di worker.py)
    job = q.enqueue(generate_qr_and_wait_for_login, user_id)
    print(f"Tugas QR login untuk user {user_id} di antrean RQ: {job.id}")
    return job

def enqueue_comment_processing_task(user_id: int):
    """
    Menempatkan tugas pemrosesan komentar ke antrean RQ.
    Bot worker akan mengambil dan menjalankan tugas run_tiktok_bot_task.
    """
    # NOTE: run_tiktok_bot_task akan memanggil APIClient di dalamnya.
    job = q.enqueue(run_tiktok_bot_task, user_id)
    print(f"Tugas pemrosesan komentar untuk user {user_id} di antrean RQ: {job.id}")
    return job

# Fungsi yang akan dipanggil oleh worker.py
# Ini hanya untuk memastikan RQ dapat mengimpor dan menjalankannya
if __name__ == '__main__':
    print("This file contains RQ task definitions. Run `python -m akseskomen.worker` to start the RQ worker.")
