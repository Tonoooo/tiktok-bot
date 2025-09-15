# akses_komen/run_worker.py
import os
import sys
import redis
import time # BARU: Untuk time.sleep
import threading # BARU: Untuk menjalankan heartbeat di thread terpisah
from rq import Worker, Queue
from uuid import uuid4 # BARU: Untuk membuat ID unik worker
from datetime import datetime # BARU: Untuk timestamp log

# Tambahkan direktori proyek ke sys.path agar impor lokal berfungsi
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if project_root not in sys.path:
    sys.path.append(project_root)
    
    
from backend.tasks import heartbeat_task

# Konfigurasi Redis
# Pastikan URL ini sama dengan yang digunakan di backend/app.py dan backend/tasks.py
REDIS_URL = os.getenv('REDIS_URL', 'redis://103.52.114.253:6379/0')

# Inisialisasi koneksi Redis dengan socket_timeout=0
# Ini memberitahu klien Redis untuk tidak timeout saat menunggu data
# dari server, membiarkan koneksi tetap terbuka meskipun idle.
print(f"Menginisialisasi koneksi Redis dengan socket_timeout=0 ke {REDIS_URL}")
redis_conn = redis.from_url(REDIS_URL, socket_timeout=0, socket_keepalive=True)

# Inisialisasi Queue (antrean)
# Secara default, worker akan mendengarkan antrean 'default'
q = Queue('default', connection=redis_conn)

# --- BARU: Fungsi Heartbeat di Thread Terpisah ---
WORKER_UNIQUE_ID = str(uuid4())[:8] # Buat ID unik untuk worker ini (8 karakter pertama)
HEARTBEAT_INTERVAL_SECONDS = 120 # Kirim heartbeat setiap 2 menit (harus lebih pendek dari timeout jaringan)

def send_heartbeat_periodically(queue_obj, worker_id):
    """Fungsi yang akan berjalan di thread terpisah untuk mengirim heartbeat."""
    while True:
        try:
            # Enqueue task heartbeat. Timeout sangat singkat karena tugasnya ringan.
            # Job timeout ini untuk task heartbeat itu sendiri, bukan untuk koneksi.
            queue_obj.enqueue(heartbeat_task, worker_id, job_timeout=5)
            print(f"[{datetime.now()}] Heartbeat task diantrekan oleh worker {worker_id}.")
        except Exception as e:
            print(f"[{datetime.now()}] ERROR saat mengantrekan heartbeat: {e}")
        time.sleep(HEARTBEAT_INTERVAL_SECONDS)

if __name__ == '__main__':
    print(f"Memulai RQ Worker secara terprogram dengan ID: {WORKER_UNIQUE_ID}...")

    # BARU: Mulai thread heartbeat
    # Thread daemon akan otomatis mati saat program utama (worker RQ) mati
    heartbeat_thread = threading.Thread(target=send_heartbeat_periodically, args=(q, WORKER_UNIQUE_ID))
    heartbeat_thread.daemon = True
    heartbeat_thread.start()
    print(f"Thread heartbeat dimulai, akan mengirim setiap {HEARTBEAT_INTERVAL_SECONDS} detik.")

    # Mulai worker utama RQ
    worker = Worker(queues=[q], connection=redis_conn)
    worker.work()