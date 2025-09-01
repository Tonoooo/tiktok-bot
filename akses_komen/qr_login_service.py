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
        print("Mencoba mendeteksi modal 'chose your interest'...")
        # MEMPERBAIKI: Pastikan overlay modal tidak ada sebelum mengklik (jika ada)
        overlay_locator = (By.CSS_SELECTOR, '.TUXModal-overlay[data-transition-status="open"]')
        try:
            WebDriverWait(driver, 5).until(EC.invisibility_of_element_located(overlay_locator))
            print("Overlay modal awal tidak terlihat.")
        except TimeoutException:
            print("Peringatan: Overlay modal awal masih terlihat atau tidak menghilang. Melanjutkan.")

        # MEMPERBARUI: Meningkatkan timeout untuk stabilitas
        modal_interest_button = WebDriverWait(driver, 15).until( 
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-e2e="bottom-login"]'))
        )
        modal_interest_button.click()
        print("Tombol 'log in' di modal 'chose your interest' diklik.")
        time.sleep(5)

        # MEMPERBARUI: Meningkatkan timeout untuk stabilitas
        qr_button_interest = WebDriverWait(driver, 15).until( 
            EC.element_to_be_clickable((By.XPATH, "//div[@role='link' and .//div[text()='Use QR code']]"))
        )
        qr_button_interest.click()
        print("Tombol 'Use QR code' diklik.")
        return True

    except (TimeoutException, ElementNotInteractableException, NoSuchElementException) as e:
        print(f"Modal 'chose your interest' atau QR button tidak ditemukan, mencoba alur 'Ikuti'. Error: {e}")
        try:
            # MEMPERBAIKI: Pastikan overlay modal tidak ada sebelum mengklik (jika ada)
            overlay_locator = (By.CSS_SELECTOR, '.TUXModal-overlay[data-transition-status="open"]')
            try:
                WebDriverWait(driver, 5).until(EC.invisibility_of_element_located(overlay_locator))
                print("Overlay modal awal tidak terlihat.")
            except TimeoutException:
                print("Peringatan: Overlay modal awal masih terlihat atau tidak menghilang. Melanjutkan.")

            # MEMPERBARUI: Meningkatkan timeout untuk stabilitas
            follow_button = WebDriverWait(driver, 20).until( 
                EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-e2e="follow-button"]'))
            )
            follow_button.click()
            print("Tombol 'Ikuti' diklik.")
            time.sleep(3)

            # MEMPERBARUI: Meningkatkan timeout untuk stabilitas
            qr_button = WebDriverWait(driver, 15).until( 
                EC.element_to_be_clickable((By.XPATH, "//div[@role='link' and .//div[text()='Use QR code']]"))
            )
            qr_button.click()
            print("Tombol 'Use QR code' diklik.")
            return True
        except Exception as e_follow:
            print(f"Gagal memicu QR code melalui tombol 'Ikuti'. Pastikan halaman TikTok dapat dimuat. Error: {e_follow}")
            return False

# PERUBAHAN: app_instance diganti dengan api_client
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

        print(f"WebDriver berhasil diinisialisasi untuk user {user_id} (non-headless lokal).") 

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

        time.sleep(3) # Tambahkan jeda awal lebih lama setelah navigasi untuk stabilitas halaman

        # Awalnya, picu modal QR code
        if not _open_tiktok_qr_modal(driver):
            print("Gagal membuka modal QR code saat inisialisasi awal.")
            return False

        print(f"Menunggu elemen QR code (canvas) muncul untuk user {user_id}...")
        qr_element_locator = (By.CSS_SELECTOR, '[data-e2e="qr-code"] canvas') 
        
        # Tunggu elemen <canvas> itu sendiri
        qr_canvas_element = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located(qr_element_locator) 
        )
        print(f"Elemen QR code (canvas) terdeteksi untuk user {user_id}.")
        time.sleep(3) # Jeda untuk rendering visual yang stabil

        # Ambil screenshot QR code awal (yang pertama kali muncul)
        qr_data_url = driver.execute_script("return arguments[0].toDataURL('image/png');", qr_canvas_element)
        if qr_data_url and qr_data_url.startswith("data:image/png;base64,"):
            base64_data = qr_data_url.split(',')[1]
            decoded_image = base64.b64decode(base64_data)
            with open(qr_image_path, 'wb') as f:
                f.write(decoded_image)
            print(f"QR code awal disimpan ke: {qr_image_path}")

        login_successful = False
        MAX_LOGIN_WAIT_TIME = 300 # detik (total 5 menit)
        RECHECK_INTERVAL = 5 # detik, untuk cek status

        # Interval dan waktu terakhir untuk mengambil screenshot QR code
        QR_SCREENSHOT_INTERVAL = 15 # detik
        last_screenshot_time = time.time()

        start_time = time.time()

        # Base URL for comparison (without query parameters like ?lang=en)
        target_url_base = target_url.split('?')[0]

        # --- Loop untuk terus-menerus mendeteksi status login ---
        while (time.time() - start_time) < MAX_LOGIN_WAIT_TIME:
            current_time = time.time()

            # --- Ambil data QR code terbaru dari canvas (untuk visualisasi di frontend) ---
            # Hanya ambil screenshot jika sudah melewati interval yang ditentukan
            if (current_time - last_screenshot_time) >= QR_SCREENSHOT_INTERVAL:
                last_screenshot_time = current_time
                try:
                    # Re-locate elemen <canvas> setiap kali untuk menghindari StaleElementReferenceException
                    qr_canvas_element_fresh = WebDriverWait(driver, 5).until( 
                        EC.presence_of_element_located(qr_element_locator) 
                    )
                    qr_data_url = driver.execute_script("return arguments[0].toDataURL('image/png');", qr_canvas_element_fresh)

                    if qr_data_url and qr_data_url.startswith("data:image/png;base64,"):
                        base64_data = qr_data_url.split(',')[1]
                        decoded_image = base64.b64decode(base64_data)
                        with open(qr_image_path, 'wb') as f:
                            f.write(decoded_image)
                        print(f"QR code terbaru disimpan ke: {qr_image_path}")
                    else:
                        print("Peringatan: Data URI QR code tidak valid atau kosong saat update periodik.")
                except StaleElementReferenceException:
                    print("Peringatan: Elemen QR code (canvas) menjadi stale saat mengambil data (update periodik).")
                except Exception as e:
                    print(f"ERROR: Gagal mendapatkan data QR code dari canvas (update periodik): {e}.")


            # --- Deteksi Login Berhasil (indikator yang lebih andal) ---
            try:
                # 1. Deteksi tampilan "QR code scanned" overlay
                # Ini adalah indikator prioritas utama Anda, kita akan coba deteksi ini secara agresif
                # Timeout 60 detik karena Anda bilang tampilannya bisa bertahan sampai 1 menit
                print("Menunggu tampilan 'QR code scanned' overlay (maks 60 detik)...")
                scanned_overlay_locator = (By.CSS_SELECTOR, '[data-e2e="qr-code"] .css-n2w5z3-DivCodeMask')
                WebDriverWait(driver, 60).until( 
                    EC.presence_of_element_located(scanned_overlay_locator)
                )
                print("Tampilan 'QR code scanned' overlay terdeteksi.")
                
                # Jika overlay scanned terdeteksi, langsung anggap login sukses dan verifikasi final
                login_successful = True # Set flag to True early
                
                # 2. Notifikasi "Logged in" (opsional, untuk debugging/logging saja, tidak akan memblokir)
                try:
                    print("Menunggu notifikasi 'Logged in' (opsional)...")
                    logged_in_toast_locator = (By.XPATH, "//div[@role='alert']/span[text()='Logged in']")
                    WebDriverWait(driver, 5).until( # Sangat cepat menghilang
                        EC.presence_of_element_located(logged_in_toast_locator)
                    )
                    print("Notifikasi 'Logged in' terdeteksi.")
                except TimeoutException:
                    print("DEBUG: Notifikasi 'Logged in' tidak terdeteksi (mungkin fleeting atau sudah menghilang).")

                # 3. Modal QR code menghilang (Verifikasi Penting)
                print("Menunggu modal QR code menghilang...")
                WebDriverWait(driver, 30).until( # Cukup waktu untuk modal hilang setelah scanned/redirect
                    EC.invisibility_of_element_located((By.CSS_SELECTOR, '[data-e2e="qr-code"]'))
                )
                print("Modal QR code telah menghilang.")

                # 4. Redirect ke URL profil (Verifikasi Penting)
                print(f"Memverifikasi redirect ke URL profil: {target_url_base}...")
                WebDriverWait(driver, 30).until( # Cukup waktu untuk redirect
                    EC.url_contains(target_url_base)
                )
                print("Berhasil dialihkan ke halaman profil.")
                
                # PRIORITAS UTAMA 5: Deteksi tombol profil user (indikator kuat setelah redirect)
                print("Menunggu tombol profil user muncul (indikator login berhasil)...")
                # Kita cari tombol dengan atribut aria-haspopup="dialog" yang berisi gambar avatar
                profile_button_locator = (By.CSS_SELECTOR, 'button[aria-haspopup="dialog"] img[class*="ImgAvatar"]')
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located(profile_button_locator)
                )
                print("Tombol profil user (avatar) terdeteksi. Login berhasil dikonfirmasi.")
                

                # Jika semua pengecekan di dalam try block ini berhasil, maka login memang sukses
                print(f"Login QR code berhasil untuk user {user_id}. Berhasil dialihkan ke halaman profil.")
                break # Keluar dari loop utama karena login berhasil

            except TimeoutException as te:
                # Jika "QR code scanned" atau indikator penting lainnya tidak terdeteksi dalam timeout-nya
                print(f"Timeout deteksi login ({te}). Login belum dikonfirmasi oleh indikator utama. Waktu berlalu: {int(current_time - start_time)}s. Mencoba lagi.")
                time.sleep(RECHECK_INTERVAL) # Tidur sebentar sebelum iterasi berikutnya
                continue # Lanjutkan loop

            except TimeoutException as te:
                # Jika modal tidak hilang ATAU URL tidak berubah ATAU tombol profil tidak muncul dalam waktu yang ditentukan
                print(f"Login belum dikonfirmasi (modal/URL/profil button belum terdeteksi). Waktu berlalu total: {int(current_time - start_time)}s. Mencoba lagi.")
                time.sleep(RECHECK_INTERVAL) # Tidur sebentar sebelum iterasi berikutnya
                continue # Lanjutkan loop

            except WebDriverException as we:
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
            return True
        else:
            print(f"Login gagal setelah {MAX_LOGIN_WAIT_TIME/60} menit menunggu untuk user {user_id}.")
            if os.path.exists(qr_image_path):
                os.remove(qr_image_path)
            return False

    except TimeoutException:
        print(f"Timeout: QR code tidak discan atau login gagal dalam waktu yang ditentukan untuk user {user_id} (main try-catch).")
        if os.path.exists(qr_image_path):
            os.remove(qr_image_path)
        return False
    except WebDriverException as we:
        print(f"WebDriver ERROR untuk user {user_id} (main try-catch): {we}")
        if os.path.exists(qr_image_path):
            os.remove(qr_image_path)
        return False
    except Exception as e:
        print(f"ERROR tak terduga dalam alur QR login untuk user {user_id} (main try-catch): {e}")
        if os.path.exists(qr_image_path):
            os.remove(qr_image_path)
        return False
    finally:
        if driver:
            driver.quit()
            print(f"WebDriver ditutup untuk user {user_id}.")