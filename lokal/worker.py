import time
import requests
import json
import os
import threading
from datetime import datetime, timedelta

from akses_komen.api_client import APIClient
from akses_komen.qr_login_service import generate_qr_and_wait_for_login
from akses_komen.bot import run_tiktok_bot_task

# ==================================================
# KONFIGURASI BOT WORKER (SESUAIKAN INI)
# ==================================================
# URL dasar API Flask yang berjalan di VPS Anda
VPS_API_BASE_URL = "http://103.52.114.253:5000"  # GANTI DENGAN Public IP VPS Anda
API_BOT_KEY = "super_secret_bot_key_123"        # GANTI dengan API_BOT_KEY yang sama di backend/app.py

# Interval pengecekan tugas baru dari VPS
# Bot akan memeriksa VPS setiap berapa detik/menit
TASK_CHECK_INTERVAL_SECONDS = 300 # Setiap 5 menit

# ==================================================
# API Client Initialization
# ==================================================
api_client = APIClient(VPS_API_BASE_URL, API_BOT_KEY)

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

# ==================================================
# Fungsi utama Bot Worker
# ==================================================
def bot_worker_loop():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Bot Worker dimulai.")
    
    while True:
        try:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Mencari user aktif dari VPS...")
            # Endpoint ini belum dibuat, kita akan membuatnya di langkah selanjutnya di backend/app.py
            # Untuk sementara, kita akan mengambil user ID 1 sebagai contoh
            # Nanti akan ada endpoint seperti /api/active_users
            
            # --- Untuk saat ini, kita akan bekerja dengan user_id = 1 sebagai placeholder ---
            # Asumsi: Anda sudah membuat user dengan ID 1 di database VPS Anda
            user_id_to_process = 1 
            
            user_data = api_client.get_user_settings(user_id_to_process)
            
            if not user_data:
                print(f"Tidak ada data user ditemukan untuk ID {user_id_to_process} dari VPS. Mencoba lagi dalam {TASK_CHECK_INTERVAL_SECONDS} detik.")
                time.sleep(TASK_CHECK_INTERVAL_SECONDS)
                continue

            if not user_data.get('is_active'):
                print(f"User {user_id_to_process} tidak aktif. Melewati. Mencoba lagi dalam {TASK_CHECK_INTERVAL_SECONDS} detik.")
                time.sleep(TASK_CHECK_INTERVAL_SECONDS)
                continue

            tiktok_username = user_data.get('tiktok_username')
            if not tiktok_username:
                print(f"User {user_id_to_process} belum memiliki tiktok_username. Melewati. Mencoba lagi dalam {TASK_CHECK_INTERVAL_SECONDS} detik.")
                time.sleep(TASK_CHECK_INTERVAL_SECONDS)
                continue
            
            # Cek apakah sudah waktunya menjalankan bot berdasarkan last_run_at dan daily_run_count
            last_run_at_str = user_data.get('last_run_at')
            daily_run_count_limit = user_data.get('daily_run_count', 0) # Default 0 jika tidak diset

            should_run_bot = False
            if not last_run_at_str:
                should_run_bot = True # Belum pernah dijalankan
                print(f"User {user_id_to_process} belum pernah menjalankan bot. Akan dijalankan sekarang.")
            else:
                last_run_at = datetime.fromisoformat(last_run_at_str)
                # Cek apakah sudah 24 jam sejak pertama kali dijalankan hari ini
                if (datetime.now() - last_run_at).days >= 1:
                    # Reset daily_run_count dan jalankan
                    should_run_bot = True
                    print(f"User {user_id_to_process} sudah melewati 24 jam, akan reset run count dan jalankan.")
                    # Kita perlu endpoint untuk reset daily_run_count
                else:
                    # Cek apakah sudah mencapai batas harian
                    # Untuk daily_run_count, Anda perlu logika di backend untuk menyimpannya per hari
                    # Dan juga, bot ini akan dipanggil 3 kali sehari, jadi kita bisa cek intervalnya
                    # Untuk saat ini, kita akan asumsikan bot harus jalan jika sudah 8 jam sejak terakhir.
                    # Asumsi: run_count_limit adalah jumlah total per hari, tapi kita akan pakai interval tetap.
                    
                    # Logika sederhana: jalankan setiap 8 jam jika daily_run_count > 0
                    if daily_run_count_limit > 0: # Hanya jalankan jika creator ingin bot berjalan
                        interval_between_runs = timedelta(hours=24 / daily_run_count_limit)
                        next_run_time = last_run_at + interval_between_runs

                        if datetime.now() >= next_run_time:
                            should_run_bot = True
                            print(f"User {user_id_to_process} sudah waktunya dijalankan lagi. Next run: {next_run_time.strftime('%H:%M')}.")
                        else:
                            print(f"User {user_id_to_process} belum waktunya dijalankan. Next run: {next_run_time.strftime('%Y-%m-%d %H:%M:%S')}. Melewati.")

            if not should_run_bot:
                time.sleep(TASK_CHECK_INTERVAL_SECONDS)
                continue
            
            # --- Proses Login QR Code (jika belum ada cookies) ---
            cookies_exist = user_data.get('cookies_json') and json.loads(user_data['cookies_json'])
            
            if not cookies_exist:
                print(f"User {user_id_to_process} belum login TikTok. Memulai proses QR login...")
                qr_login_successful = generate_qr_and_wait_for_login(user_id_to_process, api_client)
                
                # Setelah generate_qr_and_wait_for_login selesai, upload QR image terakhir ke VPS
                qr_image_path_local = os.path.join("qr_codes_temp", f'qrcode_{user_id_to_process}.png')
                if os.path.exists(qr_image_path_local):
                    upload_qr_image_to_vps(user_id_to_process, qr_image_path_local)
                    os.remove(qr_image_path_local) # Hapus lokal setelah upload

                if not qr_login_successful:
                    print(f"ERROR: Login QR code gagal untuk user {user_id_to_process}. Tidak dapat menjalankan bot. Mencoba lagi dalam {TASK_CHECK_INTERVAL_SECONDS} detik.")
                    time.sleep(TASK_CHECK_INTERVAL_SECONDS)
                    continue
                else:
                    print(f"Login QR code berhasil untuk user {user_id_to_process}. Melanjutkan ke tugas bot.")
            else:
                print(f"User {user_id_to_process} sudah login TikTok (cookies ada).")

            # --- Jalankan Tugas Bot Auto-Responder ---
            print(f"Memulai tugas auto-responder untuk user {user_id_to_process}...")
            run_tiktok_bot_task(user_id_to_process, api_client)
            print(f"Tugas auto-responder selesai untuk user {user_id_to_process}.")

            # PERUBAHAN: Update last_run_at melalui APIClient
            # update_response = api_client.update_user_settings(user_id_to_process, {"last_run_at": datetime.now().isoformat()})
            # Kita sudah punya endpoint update_user_last_run_api
            api_client.update_user_last_run_api(user_id_to_process)
            print(f"last_run_at diperbarui untuk user {user_id_to_process}.")

        except requests.exceptions.ConnectionError as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERROR: Gagal terhubung ke VPS API. Pastikan Flask API berjalan di {VPS_API_BASE_URL}. Error: {e}")
        except Exception as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERROR tak terduga di Bot Worker: {e}")
        
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Tidur selama {TASK_CHECK_INTERVAL_SECONDS} detik sebelum memeriksa tugas berikutnya.")
        time.sleep(TASK_CHECK_INTERVAL_SECONDS)

if __name__ == '__main__':
    # Untuk menjalankan bot worker secara terus-menerus
    bot_worker_loop()