import os
import sys
import redis
import time
import threading
from rq import Worker, Queue # PERUBAHAN: Hapus 'Connection' dari import
from uuid import uuid4
from datetime import datetime

# Tambahkan direktori proyek ke sys.path agar impor lokal berfungsi
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if project_root not in sys.path:
    sys.path.append(project_root)
    
from backend.tasks import heartbeat_task

# Konfigurasi Redis
REDIS_URL = os.getenv('REDIS_URL', 'redis://103.52.114.253:6379/0')

# --- Fungsi Heartbeat di Thread Terpisah ---
WORKER_UNIQUE_ID = str(uuid4())[:8]
HEARTBEAT_INTERVAL_SECONDS = 60

def send_heartbeat_periodically(redis_url, worker_id):
    """Fungsi yang akan berjalan di thread terpisah untuk mengirim heartbeat."""
    while True:
        try:
            redis_conn_hb = redis.from_url(redis_url)
            q_hb = Queue('default', connection=redis_conn_hb)
            q_hb.enqueue(heartbeat_task, worker_id, job_timeout=10)
            print(f"[{datetime.now()}] Heartbeat task diantrekan oleh worker {worker_id}.")
        except Exception as e:
            print(f"[{datetime.now()}] ERROR saat mengantrekan heartbeat: {e}")
        time.sleep(HEARTBEAT_INTERVAL_SECONDS)

def main_worker_loop():
    """Loop utama yang akan menjalankan worker dan mencoba menyambung kembali jika gagal."""
    while True:
        try:
            print(f"[{datetime.now()}] Mencoba terhubung ke Redis untuk memulai worker...")
            redis_conn = redis.from_url(REDIS_URL)
            redis_conn.ping()
            print(f"[{datetime.now()}] Koneksi Redis berhasil. Memulai worker...")
            
            # PERUBAHAN: Hapus 'with Connection(...)'
            # Masukkan 'connection=redis_conn' langsung ke Worker
            queues = [Queue('default', connection=redis_conn)]
            worker = Worker(queues, connection=redis_conn)
            
            # with_scheduler=True sudah tidak digunakan lagi di argumen work()
            worker.work(with_scheduler=False) 
        
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError) as e:
            print(f"[{datetime.now()}] Koneksi Redis terputus: {e}. Mencoba menyambung kembali dalam 10 detik...")
            time.sleep(10)
        except Exception as e:
            print(f"[{datetime.now()}] Terjadi error tak terduga pada worker: {e}. Merestart dalam 15 detik...")
            time.sleep(15)

if __name__ == '__main__':
    print(f"Memulai RQ Worker secara terprogram dengan ID: {WORKER_UNIQUE_ID}...")

    heartbeat_thread = threading.Thread(target=send_heartbeat_periodically, args=(REDIS_URL, WORKER_UNIQUE_ID))
    heartbeat_thread.daemon = True
    heartbeat_thread.start()
    print(f"Thread heartbeat dimulai, akan mengirim setiap {HEARTBEAT_INTERVAL_SECONDS} detik.")

    main_worker_loop()