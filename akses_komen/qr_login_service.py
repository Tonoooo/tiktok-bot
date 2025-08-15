import undetected_chromedriver as uc
import time
import os
import json
import base64 
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException, ElementNotInteractableException, StaleElementReferenceException 
from flask import Flask 
from backend.models import db, User 

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
        # MEMPERBARUI: Meningkatkan timeout untuk stabilitas
        modal_interest_button = WebDriverWait(driver, 15).until( # Ditingkatkan dari 10 menjadi 15
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-e2e="bottom-login"]'))
        )
        modal_interest_button.click()
        print("Tombol 'log in' di modal 'chose your interest' diklik.")
        time.sleep(5)

        # MEMPERBARUI: Meningkatkan timeout untuk stabilitas
        qr_button_interest = WebDriverWait(driver, 15).until( # Ditingkatkan dari 10 menjadi 15
            EC.element_to_be_clickable((By.XPATH, "//div[@role='link' and .//div[text()='Use QR code']]"))
        )
        qr_button_interest.click()
        print("Tombol 'Use QR code' diklik.")
        return True

    except (TimeoutException, ElementNotInteractableException, NoSuchElementException) as e:
        print(f"Modal 'chose your interest' atau QR button tidak ditemukan, mencoba alur 'Ikuti'. Error: {e}")
        try:
            # MEMPERBARUI: Meningkatkan timeout untuk stabilitas
            follow_button = WebDriverWait(driver, 20).until( # Ditingkatkan dari 15 menjadi 20
                EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-e2e="follow-button"]'))
            )
            follow_button.click()
            print("Tombol 'Ikuti' diklik.")
            time.sleep(3)

            # MEMPERBARUI: Meningkatkan timeout untuk stabilitas
            qr_button = WebDriverWait(driver, 15).until( # Ditingkatkan dari 10 menjadi 15
                EC.element_to_be_clickable((By.XPATH, "//div[@role='link' and .//div[text()='Use QR code']]"))
            )
            qr_button.click()
            print("Tombol 'Use QR code' diklik.")
            return True
        except Exception as e_follow:
            print(f"Gagal memicu QR code melalui tombol 'Ikuti'. Pastikan halaman TikTok dapat dimuat. Error: {e_follow}")
            return False

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

            time.sleep(10) # DIPERBARUI: Tambahkan jeda awal lebih lama setelah navigasi untuk stabilitas halaman

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

            # --- Loop untuk terus-menerus mendapatkan QR code baru dengan keluar-masuk modal ---
            login_successful = False
            
            QR_REGENERATE_INTERVAL = 60 # DIPERBARUI: detik (waktu untuk menutup dan membuka lagi modal QR)
            MAX_LOGIN_WAIT_TIME = 420 # DIPERBARUI: detik (total 7 menit)

            start_time = time.time()
            time_of_last_qr_regen = time.time() # Waktu terakhir QR di-regenerate

            while (time.time() - start_time) < MAX_LOGIN_WAIT_TIME:
                current_time = time.time()
                
                # Cek apakah sudah waktunya untuk mendapatkan QR code baru dengan keluar-masuk modal
                if (current_time - time_of_last_qr_regen) >= QR_REGENERATE_INTERVAL:
                    print(f"Waktunya me-regenerate QR code untuk user {user_id}. Menutup dan membuka kembali modal...")
                    time_of_last_qr_regen = current_time # Update waktu regen sebelum mencoba

                    # 1. Coba tutup modal QR code saat ini
                    try:
                        close_button_locator = (By.CSS_SELECTOR, '[data-e2e="modal-close-inner-button"][aria-label="Close"]')
                        close_button = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(close_button_locator))
                        close_button.click()
                        print("Tombol 'X' (tutup modal QR) diklik.")
                        WebDriverWait(driver, 10).until(EC.invisibility_of_element_located(close_button_locator))
                        print("Modal QR code berhasil ditutup.")
                        time.sleep(2) # Beri waktu modal untuk menghilang sepenuhnya
                    except TimeoutException:
                        print("Peringatan: Tombol 'X' atau modal QR tidak menghilang. Melanjutkan untuk mencoba membuka ulang.")
                    except Exception as e:
                        print(f"Error saat menutup modal QR: {e}. Mencoba membuka ulang.")

                    # 2. Buka kembali modal QR code
                    if not _open_tiktok_qr_modal(driver):
                        print("Gagal membuka kembali modal QR code setelah regenerasi. Mengakhiri loop login.")
                        break # Keluar dari loop jika tidak bisa membuka modal lagi

                    # 3. Tunggu elemen <canvas> QR code baru muncul lagi
                    try:
                        qr_canvas_element = WebDriverWait(driver, 15).until(
                            EC.presence_of_element_located(qr_element_locator) 
                        )
                        print("Elemen QR code (canvas) baru terdeteksi setelah regenerasi.")
                        time.sleep(3) # Jeda 3 detik untuk rendering visual yang stabil setelah regenerasi
                    except TimeoutException:
                        print("Peringatan: Elemen QR code (canvas) tidak muncul kembali setelah regenerasi. Mengakhiri loop login.")
                        break # Keluar jika QR tidak muncul

                # Ambil data QR code terbaru dari canvas yang baru dibuka/diregenerasi
                qr_data_url = None
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
                        print("Peringatan: Data URI QR code tidak valid atau kosong (setelah regenerasi).")
                except StaleElementReferenceException:
                    print("Peringatan: Elemen QR code (canvas) menjadi stale saat mengambil data (setelah regenerasi).")
                except Exception as e:
                    print(f"ERROR: Gagal mendapatkan data QR code dari canvas (setelah regenerasi): {e}.")
                
                # Cek apakah login berhasil
                try:
                    # PRIORITAS: Tunggu hingga modal QR code menghilang (indikator paling andal untuk login sukses di HP)
                    print(f"Menunggu modal QR code menghilang (maks {QR_REGENERATE_INTERVAL} detik)...")
                    WebDriverWait(driver, QR_REGENERATE_INTERVAL).until( 
                        EC.invisibility_of_element_located((By.CSS_SELECTOR, '[data-e2e="qr-code"]'))
                    )
                    print("Modal QR code telah menghilang. Login di HP kemungkinan berhasil.")

                    # Setelah modal menghilang, baru verifikasi pengalihan ke URL profil.
                    # Ini seharusnya terjadi cukup cepat setelah modal hilang.
                    print(f"Memverifikasi redirect ke URL profil: {target_url} (maks 60 detik)...")
                    WebDriverWait(driver, 60).until( 
                        EC.url_to_be(target_url)
                    )
                    print("Berhasil dialihkan ke halaman profil.")

                    # Debugging/Logging: Coba cek teks "QR code scanned" jika perlu, tapi jangan sampai menghentikan proses
                    try:
                        scanned_text_element = driver.find_element(By.XPATH, "//p[text()='QR code scanned']")
                        if scanned_text_element.is_displayed():
                            print("DEBUG: Teks 'QR code scanned' sempat terdeteksi.")
                    except NoSuchElementException:
                        print("DEBUG: Teks 'QR code scanned' tidak terdeteksi (mungkin fleeting atau tidak dirender di headless).")
                    
                    login_successful = True
                    print(f"Login QR code berhasil untuk user {user_id}. Berhasil dialihkan ke halaman profil.")
                    break 
                except TimeoutException:
                    # Jika modal tidak hilang atau URL tidak berubah dalam waktu yang ditentukan, berarti login belum berhasil.
                    print(f"Login belum dikonfirmasi (modal tidak hilang / URL tidak berubah) dalam {QR_REGENERATE_INTERVAL} detik. Mencoba me-regenerate QR code. Waktu berlalu total: {int(time.time() - start_time)}s.")
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
