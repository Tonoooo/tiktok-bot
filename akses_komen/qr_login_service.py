import undetected_chromedriver as uc
import time
import os
import json
import base64 # BARU: Import modul base64
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException, ElementNotInteractableException, StaleElementReferenceException 
from flask import Flask 
from backend.models import db, User 
# from PIL import Image # TIDAK PERLU LAGI PIL, BISA DIHAPUS

QR_CODE_TEMP_DIR = 'qr_codes_temp'
os.makedirs(QR_CODE_TEMP_DIR, exist_ok=True)

def generate_qr_and_wait_for_login(user_id: int, app_instance: Flask):
    driver = None
    qr_image_path = os.path.join(QR_CODE_TEMP_DIR, f'qrcode_{user_id}.png')
    
    # Hapus QR code lama jika ada (untuk memulai sesi baru dengan bersih)
    if os.path.exists(qr_image_path):
        os.remove(qr_image_path)
        print(f"QR code lama untuk user {user_id} dihapus.")

    try:
        options = uc.ChromeOptions()
        options.add_argument('--headless') # Jalankan browser tanpa GUI
        options.add_argument('--disable-gpu') # Diperlukan untuk headless di beberapa sistem
        options.add_argument('--no-sandbox') # Diperlukan untuk headless di Linux server
        options.add_argument('--disable-dev-shm-usage') # Mengatasi masalah resource di Docker/VPS
        
        driver = uc.Chrome(options=options)
        print(f"WebDriver berhasil diinisialisasi untuk user {user_id} (headless).") 

        with app_instance.app_context():
            user = User.query.get(user_id)
            if not user:
                print(f"ERROR: User {user_id} tidak ditemukan untuk alur QR login.")
                return False

            target_url = f"https://www.tiktok.com/@{user.tiktok_username}" 
            if not user.tiktok_username:
                print(f"Peringatan: User {user_id} belum memiliki tiktok_username. Akan mencoba login ke tiktok.com")
                driver.get("https://www.tiktok.com/")
            else:
                driver.get(target_url)

            time.sleep(5) 

            # --- Alur Klik Tombol Login untuk Memunculkan QR Code ---
            try:
                print("Mencoba mendeteksi modal 'chose your interest'...")
                modal_interest_button = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '[data-e2e="bottom-login"]'))
                )
                modal_interest_button.click()
                print("Tombol 'log in' di modal 'chose your interest' diklik.")
                time.sleep(5)

                qr_button_interest = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//div[@role='link' and .//div[text()='Use QR code']]"))
                )
                qr_button_interest.click()
                print("Tombol 'Use QR code' diklik.")

            except (TimeoutException, ElementNotInteractableException, NoSuchElementException) as e:
                print(f"Modal 'chose your interest' atau QR button tidak ditemukan, mencoba alur 'Ikuti'. Error: {e}")
                try:
                    follow_button = WebDriverWait(driver, 15).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-e2e="follow-button"]'))
                    )
                    follow_button.click()
                    print("Tombol 'Ikuti' diklik.")
                    time.sleep(5)

                    qr_button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//div[@role='link' and .//div[text()='Use QR code']]"))
                    )
                    qr_button.click()
                    print("Tombol 'Use QR code' diklik.")
                except Exception as e_follow:
                    print(f"Gagal memicu QR code melalui tombol 'Ikuti'. Pastikan halaman TikTok dapat dimuat. Error: {e_follow}")
                    return False 

            print(f"Menunggu elemen QR code (canvas) muncul untuk user {user_id}...")
            qr_element_locator = (By.CSS_SELECTOR, '[data-e2e="qr-code"] canvas') 
            
            # Tunggu elemen <canvas> itu sendiri
            qr_canvas_element = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located(qr_element_locator) 
            )
            print(f"Elemen QR code (canvas) terdeteksi untuk user {user_id}.")

            # --- Loop untuk terus-menerus mengambil screenshot QR code terbaru dari canvas ---
            login_successful = False
            last_qr_data = "" # Untuk mendeteksi perubahan QR code
            QR_REFRESH_INTERVAL = 30 # detik (waktu untuk mencoba mengambil QR baru)
            MAX_LOGIN_WAIT_TIME = 300 # detik (total 5 menit)

            start_time = time.time()
            while (time.time() - start_time) < MAX_LOGIN_WAIT_TIME:
                current_time = time.time()
                
                # Cek apakah sudah waktunya mengambil QR code terbaru (atau yang pertama)
                if (current_time - last_screenshot_time) >= QR_REFRESH_INTERVAL or last_qr_data == "":
                    print(f"Mencoba mendapatkan QR code terbaru dari canvas untuk user {user_id}...")
                    qr_data_url = None
                    try:
                        # Re-locate elemen <canvas> setiap kali untuk menghindari StaleElementReferenceException
                        qr_canvas_element_fresh = WebDriverWait(driver, 5).until( 
                            EC.presence_of_element_located(qr_element_locator) 
                        )
                        # Eksekusi JavaScript untuk mendapatkan data URI dari canvas
                        qr_data_url = driver.execute_script("return arguments[0].toDataURL('image/png');", qr_canvas_element_fresh)
                        
                        if qr_data_url and qr_data_url.startswith("data:image/png;base64,"):
                            # Potong header data URI dan decode base64
                            base64_data = qr_data_url.split(',')[1]
                            decoded_image = base64.b64decode(base64_data)
                            
                            # Simpan gambar ke file
                            with open(qr_image_path, 'wb') as f:
                                f.write(decoded_image)
                            
                            print(f"QR code terbaru disimpan ke: {qr_image_path}")
                            last_qr_data = base64_data # Simpan data untuk perbandingan
                            last_screenshot_time = current_time # Update waktu screenshot berhasil
                        else:
                            print("Peringatan: Data URI QR code tidak valid atau kosong. Mencoba lagi.")
                            time.sleep(2) # Jeda sebelum retry
                    except StaleElementReferenceException:
                        print("Peringatan: Elemen QR code (canvas) menjadi stale saat mengambil data. Mencoba lagi...")
                        time.sleep(2) 
                    except Exception as e:
                        print(f"ERROR: Gagal mendapatkan data QR code dari canvas: {e}. Mencoba lagi.")
                        time.sleep(2)
                
                # Cek apakah login berhasil (modal menghilang dan URL berubah)
                try:
                    WebDriverWait(driver, 10).until(
                        EC.invisibility_of_element_located((By.CSS_SELECTOR, '[data-e2e="qr-code"]'))
                    )
                    print("Modal QR code telah menghilang. Menunggu konfirmasi URL profil.")

                    WebDriverWait(driver, 10).until(EC.url_to_be(target_url))
                    
                    login_successful = True
                    print(f"Login QR code berhasil untuk user {user_id}. Berhasil dialihkan ke halaman profil.")
                    break 
                except TimeoutException:
                    print(f"Login belum dikonfirmasi. Terus menunggu dan me-refresh QR. Waktu berlalu: {int(time.time() - start_time)}s.")
                except WebDriverException as we:
                    print(f"WebDriver ERROR saat menunggu login konfirmasi untuk user {user_id}: {we}. Mencoba me-refresh halaman atau driver.")
                    try:
                        driver.get(target_url) 
                        time.sleep(5)
                    except Exception as nav_e:
                        print(f"Gagal me-refresh halaman setelah WebDriver error: {nav_e}. Driver mungkin rusak.")
                        raise nav_e 

            if login_successful:
                user.cookies_json = json.dumps(driver.get_cookies())
                db.session.add(user)
                db.session.commit()
                print(f"Cookies berhasil disimpan ke database untuk user {user_id}.")
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
