import time
import requests
import json
import os
import threading
from datetime import datetime, timedelta

from akses_komen.api_client import APIClient
from akses_komen.qr_login_service import generate_qr_and_wait_for_login
from akses_komen.bot import run_tiktok_bot_task
import requests

import redis
from rq import Worker, Connection, Queue

# ==================================================
# KONFIGURASI BOT WORKER (SESUAIKAN INI)
# ==================================================
# URL dasar API Flask yang berjalan di VPS Anda
VPS_API_BASE_URL = "http://103.52.114.253:5000"  # GANTI DENGAN Public IP VPS Anda
API_BOT_KEY = "super_secret_bot_key_123"        # GANTI dengan API_BOT_KEY yang sama di backend/app.py

REDIS_URL = os.getenv('REDIS_URL', 'redis://103.52.114.253:6379/0')

# Interval pengecekan tugas baru dari VPS
# Bot akan memeriksa VPS setiap berapa detik/menit
TASK_CHECK_INTERVAL_SECONDS = 300 # Setiap 5 menit

# ==================================================
# API Client Initialization
# ==================================================
api_client = APIClient(VPS_API_BASE_URL, API_BOT_KEY)


# ==================================================
# Fungsi utama RQ Worker
# ==================================================
def run_worker():
    # Membuat koneksi Redis
    redis_conn = redis.from_url(REDIS_URL)
    
    # Daftar antrean yang akan didengarkan oleh worker ini
    # Jika Anda hanya memiliki satu antrean, cukup gunakan nama antrean yang sama.
    # Nama antrean default di Flask app adalah 'default'.
    with Connection(redis_conn):
        # Inisialisasi worker yang akan mendengarkan antrean 'default'
        # Jika Anda ingin worker ini bisa menjalankan banyak jenis tugas, biarkan default.
        # Jika ingin worker spesifik, bisa dibuat antrean berbeda (misal: 'qr_queue', 'comment_queue')
        worker = Worker(['default']) # Worker ini akan mendengarkan antrean 'default'
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] RQ Worker dimulai, mendengarkan antrean: {worker.queues[0].name}")
        worker.work() # Mulai bekerja: mendengarkan antrean dan menjalankan tugas


# ==================================================
# Fungsi untuk mengupload QR code image ke VPS
# ==================================================
def upload_qr_image_to_vps(user_id: int, image_path: str):
    """
    Mengupload gambar QR code dari lokal ke VPS agar bisa diakses oleh frontend.
    """
    try:
        with open(image_path, 'rb') as f:
            files = {'file': (os.path.basename(image_path), f, 'image/png')}
            response = requests.post(f"{VPS_API_BASE_URL}/api/upload_qr_image/{user_id}", 
                                     headers={"X-API-Key": API_BOT_KEY}, 
                                     files=files)
            response.raise_for_status()
            print(f"Gambar QR code untuk user {user_id} berhasil diupload ke VPS.")
            return response.json()
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Gagal mengupload gambar QR code untuk user {user_id} ke VPS: {e}")
        return None

if __name__ == '__main__':
    # Untuk menjalankan satu RQ worker:
    # python akses_komen/worker.py

    # Untuk menjalankan beberapa RQ worker (misalnya 3 worker) secara paralel di terminal berbeda:
    # terminal 1: python akses_komen/worker.py
    # terminal 2: python akses_komen/worker.py
    # terminal 3: python akses_komen/worker.py

    # Atau gunakan utility `rq` langsung (lebih disarankan):
    # cd ke root project Anda (folder tiktok-bot)
    # Pastikan Redis berjalan: redis-server
    # Aktifkan virtual environment: .venv/Scripts/activate
    # Jalankan RQ worker: rq worker -u redis://localhost:6379/0 default
    # Untuk menjalankan beberapa worker:
    # rq worker -u redis://localhost:6379/0 default & rq worker -u redis://localhost:6379/0 default &
    
    run_worker()