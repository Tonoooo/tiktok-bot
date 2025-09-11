import undetected_chromedriver as uc
import time
import os
import json
import base64 
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException, ElementNotInteractableException, StaleElementReferenceException 

# PERUBAHAN: Ganti import Flask, db, User dengan APIClient
from akses_komen.api_client import APIClient 

QR_CODE_TEMP_DIR = 'qr_codes_temp'
os.makedirs(QR_CODE_TEMP_DIR, exist_ok=True)

# Helper function untuk membuka modal QR code
def _open_tiktok_qr_modal(driver):
    """
    Mengklik tombol yang diperlukan untuk menampilkan modal login QR code.
    Mengembalikan True jika modal QR berhasil dipicu, False jika gagal.
    """
    try:
        # --------------------------------------- chose your interest ---------------------------------------
        print("Mencoba mendeteksi modal 'chose your interest'...")
        overlay_locator = (By.CSS_SELECTOR, '.TUXModal-overlay[data-transition-status="open"]')
        try:
            WebDriverWait(driver, 3).until(EC.invisibility_of_element_located(overlay_locator))
            print("Overlay modal awal tidak terlihat.")
        except TimeoutException:
            print("Peringatan: Overlay modal awal masih terlihat atau tidak menghilang. Melanjutkan.")

        # jika modal 'chose your interest' muncul, klik tombol 'log in'
        modal_interest_button = WebDriverWait(driver, 8).until( 
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-e2e="bottom-login"]'))
        )
        modal_interest_button.click()
        print("Tombol 'log in' di modal 'chose your interest' diklik.")
        time.sleep(5)

        # MEMPERBARUI: Meningkatkan timeout untuk stabilitas
        qr_button_interest = WebDriverWait(driver, 8).until( 
            EC.element_to_be_clickable((By.XPATH, "//div[@role='link' and .//div[text()='Use QR code']]"))
        )
        qr_button_interest.click()
        print("Tombol 'Use QR code' diklik.")
        return True

    except (TimeoutException, ElementNotInteractableException, NoSuchElementException, WebDriverException) as e:
        # ---------------------------------------- jika modal 'chose your interest' tidak muncul | klik tombol 'Ikuti' ----------------------------------------
        print(f"Modal 'chose your interest' atau QR button tidak ditemukan, mencoba alur 'Ikuti'. Error: {e}")
        try:
            # MEMPERBAIKI: Pastikan overlay modal tidak ada sebelum mengklik (jika ada)
            overlay_locator = (By.CSS_SELECTOR, '.TUXModal-overlay[data-transition-status="open"]')
            try:
                WebDriverWait(driver, 3).until(EC.invisibility_of_element_located(overlay_locator))
                print("Overlay modal awal tidak terlihat.")
            except TimeoutException:
                print("Peringatan: Overlay modal awal masih terlihat atau tidak menghilang. Melanjutkan.")

            follow_button = WebDriverWait(driver, 10).until( 
                EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-e2e="follow-button"]'))
            )
            follow_button.click()
            print("Tombol 'Ikuti' diklik.")
            time.sleep(3)

            # MEMPERBARUI: Meningkatkan timeout untuk stabilitas
            qr_button = WebDriverWait(driver, 8).until( 
                EC.element_to_be_clickable((By.XPATH, "//div[@role='link' and .//div[text()='Use QR code']]"))
            )
            qr_button.click()
            print("Tombol 'Use QR code' diklik.")
            return True
        except Exception as e_follow:
            print(f"Gagal memicu QR code melalui tombol 'Ikuti'. Pastikan halaman TikTok dapat dimuat. Error: {e_follow}")
            return False


def _capture_save_and_upload_qr_code(driver, user_id, api_client, qr_canvas_element, qr_image_path):
    """
    Mengambil gambar QR code dari elemen canvas, menyimpannya secara lokal,
    dan mengunggahnya ke VPS.
    Mengembalikan True jika berhasil, False jika gagal.
    """
    try:
        qr_data_url = driver.execute_script("return arguments[0].toDataURL('image/png');", qr_canvas_element)
        if qr_data_url and qr_data_url.startswith("data:image/png;base64,"):
            base64_data = qr_data_url.split(',')[1]
            decoded_image = base64.b64decode(base64_data)
            with open(qr_image_path, 'wb') as f:
                f.write(decoded_image)
            print(f"QR code disimpan ke: {qr_image_path}")

            # Selalu coba upload ke VPS jika QR code berhasil diambil
            try:
                api_client.upload_qr_image_to_vps(user_id, qr_image_path)
                print(f"QR code untuk user {user_id} berhasil diupload ke VPS.")
            except Exception as upload_e:
                print(f"ERROR: Gagal mengupload gambar QR code ke VPS: {upload_e}")
            return True
        else:
            print("Peringatan: Data URI QR code tidak valid atau kosong.")
            return False
    except StaleElementReferenceException:
        print("Peringatan: Elemen QR code (canvas) menjadi stale saat mengambil data.")
        return False
    except Exception as e:
        print(f"ERROR: Gagal mendapatkan data QR code dari canvas: {e}.")
        return False

def generate_qr_and_wait_for_login(user_id: int, api_client: APIClient):
    driver = None
    qr_image_path = os.path.join(QR_CODE_TEMP_DIR, f'qrcode_{user_id}.png')
    
    # Hapus QR code lama jika ada (untuk memulai sesi baru dengan bersih)
    if os.path.exists(qr_image_path):
        os.remove(qr_image_path)
        print(f"QR code lama untuk user {user_id} dihapus.")

    try:
        # =========================
        # STEALTH HEADLESS OPTIONS
        # =========================
        options = uc.ChromeOptions()
        # options.add_argument('--headless') # Jalankan browser tanpa GUI
        # options.add_argument('--disable-gpu') # Diperlukan untuk headless di beberapa sistem
        # options.add_argument('--no-sandbox') # Diperlukan untuk headless di Linux server
        # options.add_argument('--disable-dev-shm-usage') # Mengatasi masalah resource di Docker/VPS
        driver = uc.Chrome(options=options)

        print(f"WebDriver berhasil diinisialisasi untuk user {user_id}.") 

        # PERUBAHAN: Mengambil user settings dari APIClient
        user_settings = api_client.get_user_settings(user_id)
        if not user_settings:
            print(f"ERROR: User {user_id} tidak ditemukan di API atau gagal mengambil pengaturan.")
            return False

        tiktok_username = user_settings.get('tiktok_username')
        
        target_url = f"https://www.tiktok.com/@{tiktok_username}" 
        if not tiktok_username:
            print(f"Peringatan: User {user_id} belum memiliki tiktok_username. Akan mencoba login ke tiktok.com")
            driver.get("https://www.tiktok.com/")
        else:
            driver.get(target_url)

        print("Menunggu halaman TikTok selesai dimuat...")
        WebDriverWait(driver, 15).until(lambda driver: driver.execute_script('return document.readyState') == 'complete')
        time.sleep(3) # Tambahkan jeda awal lebih lama setelah navigasi untuk stabilitas halaman

        # Awalnya, picu modal QR code
        max_modal_qr_retries = 2
        modal_qr_triggered = False
        for i in range(max_modal_qr_retries):
            if _open_tiktok_qr_modal(driver):
                modal_qr_triggered = True
                break
            else:
                print(f"Gagal memicu modal QR code (percobaan {i+1}/{max_modal_qr_retries}). Mencoba refresh halaman...")
                driver.refresh()
                time.sleep(8) # Jeda setelah refresh
                print("Halaman direfresh. Mencoba memicu modal QR code lagi.")
                WebDriverWait(driver, 15).until(lambda driver: driver.execute_script('return document.readyState') == 'complete') # Tunggu refresh selesai
        
        if not modal_qr_triggered:
            print("Gagal membuka modal QR code saat inisialisasi awal setelah beberapa percobaan. Mengakhiri proses login QR.")
            return False

        print(f"Menunggu elemen QR code (canvas) muncul untuk user {user_id}...")
        qr_element_locator = (By.CSS_SELECTOR, '[data-e2e="qr-code"] canvas') 
        
        # Tunggu elemen <canvas> itu sendiri
        qr_canvas_element = WebDriverWait(driver, 15).until( # Tingkatkan timeout
            EC.presence_of_element_located(qr_element_locator) 
        )
        print(f"Elemen QR code (canvas) terdeteksi untuk user {user_id}.")
        time.sleep(3) # Jeda untuk rendering visual yang stabil

        # ----- Ambil screenshot QR code awal (yang pertama kali muncul) -----
        if not _capture_save_and_upload_qr_code(driver, user_id, api_client, qr_canvas_element, qr_image_path):
            print("Gagal menangkap atau mengunggah QR code awal. Mengakhiri proses login QR.")
            return False

        login_successful = False
        MAX_LOGIN_WAIT_TIME = 600 # detik (total 10 menit)
        RECHECK_INTERVAL = 5 # detik, untuk cek status

        # Interval dan waktu terakhir untuk mengambil screenshot QR code
        QR_SCREENSHOT_INTERVAL = 10
        last_screenshot_time = time.time()

        start_time = time.time()

        # Base URL for comparison (without query parameters like ?lang=en)
        target_url_base = target_url.split('?')[0]

        # --- Loop untuk terus-menerus mendeteksi status login ---
        while (time.time() - start_time) < MAX_LOGIN_WAIT_TIME:
            current_time = time.time()

            # --- Ambil data QR code terbaru dari canvas (untuk visualisasi di frontend) ---
            # Pastikan ini selalu dieksekusi jika interval sudah lewat, TIDAK DI DALAM TRY/EXCEPT LOGIN UTAMA
            if (current_time - last_screenshot_time) >= QR_SCREENSHOT_INTERVAL:
                last_screenshot_time = current_time
                try:
                    # Re-locate elemen <canvas> setiap kali untuk menghindari StaleElementReferenceException
                    qr_canvas_element_fresh = WebDriverWait(driver, 5).until( 
                        EC.presence_of_element_located(qr_element_locator) 
                    )
                    _capture_save_and_upload_qr_code(driver, user_id, api_client, qr_canvas_element_fresh, qr_image_path)
                except StaleElementReferenceException:
                    print("Peringatan: Elemen QR code (canvas) menjadi stale saat mengambil data (update periodik).")
                except Exception as e:
                    print(f"ERROR: Gagal mendapatkan data QR code dari canvas (update periodik): {e}.")

            # ---------- Deteksi Login Berhasil (dengan timeout pendek untuk setiap langkah) ----------
            try:
                # Sinyal Awal (Opsional, untuk debugging): Deteksi tampilan "QR code scanned" overlay
                try:
                    print("DEBUG: Mencoba mendeteksi tampilan 'QR code scanned' overlay (maks 5 detik)...")
                    scanned_overlay_locator = (By.CSS_SELECTOR, '[data-e2e="qr-code"] .css-n2w5z3-DivCodeMask') 
                    WebDriverWait(driver, 5).until(EC.presence_of_element_located(scanned_overlay_locator))
                    print("DEBUG: Tampilan 'QR code scanned' overlay terdeteksi.")
                except TimeoutException:
                    pass # Lewati jika tidak terdeteksi

                # Sinyal Awal (Opsional, untuk debugging): Deteksi notifikasi "Logged in"
                try:
                    print("DEBUG: Mencoba mendeteksi notifikasi 'Logged in' (maks 5 detik)...")
                    logged_in_toast_locator = (By.XPATH, "//div[@role='alert']/span[text()='Logged in']")
                    WebDriverWait(driver, 5).until(EC.presence_of_element_located(logged_in_toast_locator))
                    print("DEBUG: Notifikasi 'Logged in' terdeteksi.")
                except TimeoutException:
                    pass # Lewati jika tidak terdeteksi


                # PRIORITAS UTAMA 1: Modal QR code menghilang
                # PERUBAHAN: Gunakan RECHECK_INTERVAL sebagai timeout. Jika gagal, loop akan berlanjut dan QR terupdate.
                print(f"Menunggu modal QR code menghilang (maks {RECHECK_INTERVAL} detik)...")
                WebDriverWait(driver, RECHECK_INTERVAL).until( 
                    EC.invisibility_of_element_located((By.CSS_SELECTOR, '[data-e2e="qr-code"]'))
                )
                print("Modal QR code telah menghilang. Lanjut ke verifikasi akhir.")

                # Jika modal sudah menghilang, baru kita bisa memberikan waktu tunggu yang lebih lama untuk redirect/profil
                # PRIORITAS UTAMA 2: Redirect ke URL profil (konfirmasi final)
                print(f"Memverifikasi redirect ke URL profil: {target_url_base} (maks 15 detik)...")
                WebDriverWait(driver, 15).until( 
                    EC.url_contains(target_url_base)
                )
                print("Berhasil dialihkan ke halaman profil.")

                # PRIORITAS UTAMA 3: Deteksi tombol profil user (indikator kuat setelah redirect)
                print("Menunggu tombol profil user muncul (indikator login berhasil)...")
                profile_button_locator = (By.CSS_SELECTOR, 'button[aria-haspopup="dialog"] img[class*="ImgAvatar"]')
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located(profile_button_locator)
                )
                print("Tombol profil user (avatar) terdeteksi. Login berhasil dikonfirmasi.")
                
                login_successful = True # Hanya set True jika SEMUA 3 langkah utama berhasil
                print(f"Login QR code berhasil untuk user {user_id}. Berhasil dialihkan ke halaman profil.")
                break # Keluar dari loop utama karena login berhasil

            except TimeoutException: # Ini akan menangkap kegagalan dari salah satu dari 3 prioritas utama yang timeout
                # Jika salah satu dari 3 prioritas utama (termasuk modal menghilang) timeout
                print(f"Login belum dikonfirmasi (salah satu indikator utama timeout). Waktu berlalu total: {int(current_time - start_time)}s. Mencoba lagi.")
                # Tidak perlu time.sleep(RECHECK_INTERVAL) lagi di sini, karena loop while akan tidur secara alami jika tidak ada yang lain untuk dilakukan,
                # atau QR update akan menangani jeda jika perlu. Loop akan langsung ke iterasi berikutnya.
                continue # Lanjutkan loop utama untuk update QR dan retry deteksi login

            except WebDriverException as we: # Ini menangkap error WebDriver yang lebih umum
                print(f"WebDriver ERROR saat menunggu login konfirmasi untuk user {user_id}: {we}. Mencoba me-refresh halaman atau driver.")
                try:
                    driver.get(target_url)
                    time.sleep(5)
                except Exception as nav_e:
                    print(f"Gagal me-refresh halaman setelah WebDriver error: {nav_e}. Driver mungkin rusak.")
                    raise nav_e

        if login_successful:
            # PERUBAHAN: Simpan cookies melalui APIClient
            cookies_json = json.dumps(driver.get_cookies())
            api_client.update_user_cookies(user_id, cookies_json)
            print(f"Cookies berhasil disimpan ke database untuk user {user_id} melalui API.")
            # Hapus QR code lokal setelah login berhasil dan cookies disimpan
            if os.path.exists(qr_image_path):
                os.remove(qr_image_path)
                print(f"QR code lokal untuk user {user_id} dihapus setelah login berhasil.")
            return True
        else:
            print(f"Login gagal setelah {MAX_LOGIN_WAIT_TIME/60} menit menunggu untuk user {user_id}.")
            if os.path.exists(qr_image_path):
                os.remove(qr_image_path)
                print(f"QR code lokal untuk user {user_id} dihapus karena login gagal.")
            return False

    except TimeoutException:
        print(f"Timeout: QR code tidak discan atau login gagal dalam waktu yang ditentukan untuk user {user_id} (main try-catch).")
        if os.path.exists(qr_image_path):
            os.remove(qr_image_path)
            print(f"QR code lokal untuk user {user_id} dihapus karena timeout.")
        return False
    except WebDriverException as we:
        print(f"WebDriver ERROR untuk user {user_id} (main try-catch): {we}")
        if os.path.exists(qr_image_path):
            os.remove(qr_image_path)
            print(f"QR code lokal untuk user {user_id} dihapus karena WebDriver error.")
        return False
    except Exception as e:
        print(f"ERROR tak terduga dalam alur QR login untuk user {user_id} (main try-catch): {e}")
        if os.path.exists(qr_image_path):
            os.remove(qr_image_path)
            print(f"QR code lokal untuk user {user_id} dihapus karena error tak terduga.")
        return False
    finally:
        if driver:
            driver.quit()
            print(f"WebDriver ditutup untuk user {user_id}.")