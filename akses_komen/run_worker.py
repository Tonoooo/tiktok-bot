# akses_komen/run_worker.py
import os
import sys
import redis
from rq import Worker, Queue
# from rq.connections import Connection

# Tambahkan direktori proyek ke sys.path agar impor lokal berfungsi
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if project_root not in sys.path:
    sys.path.append(project_root)

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

if __name__ == '__main__':
    print("Memulai RQ Worker secara terprogram...")
    # Daftarkan koneksi Redis ke RQ Worker
    worker = Worker(queues=[q], connection=redis_conn)
    worker.work()