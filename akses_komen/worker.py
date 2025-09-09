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
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Meminta daftar user aktif dari VPS...")
            # Panggil endpoint baru untuk mendapatkan daftar user aktif
            active_users_response = api_client._make_request("GET", "api/active_users_for_bot")
            users_to_process_list = active_users_response.get('users', [])

            if not users_to_process_list:
                print(f"Tidak ada user aktif yang perlu diproses saat ini. Mencoba lagi dalam {TASK_CHECK_INTERVAL_SECONDS} detik.")
                time.sleep(TASK_CHECK_INTERVAL_SECONDS)
                continue

            print(f"Ditemukan {len(users_to_process_list)} user yang perlu diproses.")

            for user_info in users_to_process_list:
                user_id = user_info['user_id']
                tiktok_username = user_info['tiktok_username']
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Memproses user ID: {user_id} ({tiktok_username}).")

                # --- Ambil user settings lengkap untuk cek cookies ---
                user_data = api_client.get_user_settings(user_id)
                if not user_data:
                    print(f"ERROR: Gagal mengambil pengaturan user {user_id} dari VPS. Melewati.")
                    continue

                # --- Proses Login QR Code (jika belum ada cookies) ---
                cookies_exist = user_data.get('cookies_json') and json.loads(user_data['cookies_json'])
                
                if not cookies_exist:
                    print(f"User {user_id} belum login TikTok. Memulai proses QR login...")
                    qr_login_successful = generate_qr_and_wait_for_login(user_id, api_client)
                    
                    # Setelah generate_qr_and_wait_for_login selesai, upload QR image terakhir ke VPS
                    qr_image_path_local = os.path.join("qr_codes_temp", f'qrcode_{user_id}.png')
                    if os.path.exists(qr_image_path_local):
                        upload_qr_image_to_vps(user_id, qr_image_path_local)
                        os.remove(qr_image_path_local) # Hapus lokal setelah upload

                    if not qr_login_successful:
                        print(f"ERROR: Login QR code gagal untuk user {user_id}. Tidak dapat menjalankan bot. Mencoba lagi dalam {TASK_CHECK_INTERVAL_SECONDS} detik.")
                        continue # Lanjutkan ke user berikutnya setelah ini jika ada
                    else:
                        print(f"Login QR code berhasil untuk user {user_id}. Melanjutkan ke tugas bot.")
                else:
                    print(f"User {user_id} sudah login TikTok (cookies ada).")

                # --- Jalankan Tugas Bot Auto-Responder ---
                print(f"Memulai tugas auto-responder untuk user {user_id}...")
                run_tiktok_bot_task(user_id, api_client)
                print(f"Tugas auto-responder selesai untuk user {user_id}.")

                # PERUBAHAN: Update last_run_at melalui APIClient
                api_client.update_user_last_run_api(user_id)
                print(f"last_run_at diperbarui untuk user {user_id}.")

        except requests.exceptions.ConnectionError as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERROR: Gagal terhubung ke VPS API. Pastikan Flask API berjalan di {VPS_API_BASE_URL} dan dapat diakses. Error: {e}")
        except Exception as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERROR tak terduga di Bot Worker: {e}")
        
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Tidur selama {TASK_CHECK_INTERVAL_SECONDS} detik sebelum memeriksa tugas berikutnya.")
        time.sleep(TASK_CHECK_INTERVAL_SECONDS)

if __name__ == '__main__':
    # Untuk menjalankan bot worker secara terus-menerus
    bot_worker_loop()