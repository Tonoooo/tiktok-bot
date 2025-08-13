import undetected_chromedriver as uc
import time
import math
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, NoSuchElementException, StaleElementReferenceException
import pickle
import os
import re
import json # BARU: Untuk mengelola JSON dari DB
import datetime

# Import fungsi dari service files
from .transcription_service import get_video_transcript
from .llm_service import generate_ai_reply

# BARU: Import db dan model dari backend
from backend.models import db, User, CreatorSettings
from flask import current_app # Untuk mengakses app context dari Flask

# --- CUSTOM EXPECTED CONDITION BARU UNTUK MENUNGGU TOMBOL AKTIF ---
class element_attribute_is(object):
    """An expectation for checking if the given attribute of an element has a specific value.
    This is useful for boolean attributes like 'aria-disabled'."""
    def __init__(self, locator, attribute, value):
        self.locator = locator
        self.attribute = attribute
        self.value = value

    def __call__(self, driver):
        try:
            element = driver.find_element(*self.locator)
            if element.get_attribute(self.attribute) == self.value:
                return element
            return False
        except:
            return False
# -------------------------------------------------------------------

# --- FUNGSI UTAMA BOT, DIPANGGIL DARI FLASK APP ---
def run_tiktok_bot_task(creator_id: int):
    # Akses Flask app context untuk operasi database
    with current_app.app_context():
        creator_settings = CreatorSettings.query.get(creator_id)
        if not creator_settings:
            print(f"ERROR: Creator settings not found for ID {creator_id}. Aborting bot task.")
            return

        user = User.query.get(creator_settings.user_id)
        if not user:
            print(f"ERROR: User not found for Creator ID {creator_id}. Aborting bot task.")
            return

        print(f"MEMULAI OPERASI 'TEMBUS PERISAI' untuk {creator_settings.tiktok_username}...")

        target_akun = creator_settings.tiktok_username
        target_url = f"https://www.tiktok.com/@{target_akun}"
        
        # Ambil pengaturan dari database
        creator_character_description = creator_settings.creator_character_description
        
        # Ambil cookies dan processed_video_urls dari database
        cookies = json.loads(creator_settings.cookies_json) if creator_settings.cookies_json else []
        processed_video_urls = set(json.loads(creator_settings.processed_video_urls_json) if creator_settings.processed_video_urls_json else [])

        # Konfigurasi LLM API Key di llm_service.py (sementara, akan diperbaiki)
        # Untuk saat ini, kita asumsikan llm_service menggunakan API_KEY dari env var atau hardcoded di dalamnya.
        # Nanti kita bisa passing API key dari sini jika perlu isolasi per creator.
        # import google.generativeai as genai
        # genai.configure(api_key=creator_settings.gemini_api_key) # Jika LLM service diinisialisasi di sini

    driver = None # Inisialisasi driver di luar try utama
    login_successful = False

    try:
        options = uc.ChromeOptions()
        # Biarkan kosong untuk saat ini, kita bisa menambahkan proxy nanti
        driver = uc.Chrome(options=options) # Inisialisasi driver di sini
        
        # --- Coba muat cookies yang sudah ada ---
        if cookies:
            print(f"Cookies ditemukan di database untuk {target_akun}. Mencoba memuat cookies...")
            try:
                driver.get("https://www.tiktok.com/") # Harus membuka domain sebelum menambahkan cookies
                for cookie in cookies:
                    # Filter cookies yang tidak valid untuk driver.add_cookie
                    # Beberapa properti cookie (seperti 'sameSite') mungkin perlu disesuaikan atau dihapus
                    if 'expiry' in cookie and isinstance(cookie['expiry'], float):
                        cookie['expiry'] = int(cookie['expiry'])
                    # Hapus 'sameSite' jika ada dan nilainya tidak valid ('None')
                    if 'sameSite' in cookie and cookie['sameSite'] not in ['Strict', 'Lax', 'None']:
                        del cookie['sameSite']
                    elif 'sameSite' in cookie and cookie['sameSite'] == 'None': # Khusus untuk 'None' string
                        cookie['sameSite'] = 'None' # Pastikan ini adalah string 'None' bukan NoneType
                    
                    driver.add_cookie(cookie)
                
                driver.get(target_url) # Navigasi ke URL target dengan cookies
                print("Cookies berhasil dimuat dan browser diarahkan ke profil.")
                login_successful = True
                time.sleep(10) # Beri waktu halaman termuat
            except Exception as e:
                print(f"Gagal memuat atau menggunakan cookies untuk {target_akun}: {e}. Melanjutkan dengan alur login QR code.")
                if driver: driver.quit()
                options = uc.ChromeOptions()
                driver = uc.Chrome(options=options)
                time.sleep(5)

        # --- Jika login belum berhasil (baik karena tidak ada cookies atau cookies gagal) ---
        if not login_successful:
            print(f"File cookies tidak ditemukan atau gagal dimuat untuk {target_akun}. Memulai alur login QR code...")
            driver.get(target_url) # Buka halaman target untuk memulai login QR
            time.sleep(10) # tunggu 10 detik agar halaman awal termuat dengan baik

            # --- ATTEMPT LOGIN FLOW 1: Melalui modal "chose your interest" jika ada ---
            try:
                print("Mencoba mendeteksi modal 'chose your interest'...")
                modal_interest_button = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '[data-e2e="bottom-login"]'))
                )
                modal_interest_button.click()
                print("Tombol 'log in' di modal 'chose your interest' diklik.")
                time.sleep(5)

                # Klik tombol "Use QR code"
                qr_button_interest = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//div[@role='link' and .//div[text()='Use QR code']]"))
                )
                qr_button_interest.click()
                print("Tombol 'Use QR code' diklik.")

                print("Menunggu QR code discan (tampilan 'QR code scanned' muncul)...")
                WebDriverWait(driver, 300).until(
                    EC.presence_of_element_located((By.XPATH, "//p[text()='QR code scanned']"))
                )
                print("QR code berhasil discan. Menunggu konfirmasi 'Masuk' di ponsel...")

                print("Menunggu modal QR code menghilang (menandakan user klik 'Masuk' di HP)...")
                WebDriverWait(driver, 300).until(
                    EC.invisibility_of_element_located((By.CSS_SELECTOR, '[data-e2e="qr-code"]'))
                )
                print("Modal QR code telah menghilang.")
                
                print(f"Memverifikasi redirect ke URL profil: {target_url} (setelah modal hilang)...")
                WebDriverWait(driver, 60).until(
                    EC.url_to_be(target_url)
                )
                print("Berhasil dialihkan ke halaman profil.")
                login_successful = True

            except (TimeoutException, ElementClickInterceptedException) as e:
                print(f"Gagal login via modal 'chose your interest' atau scan QR untuk {target_akun}. Mencoba alur alternatif. Error: {e}")
            except Exception as e:
                print(f"Terjadi error tak terduga dalam alur login 'chose your interest' untuk {target_akun}: {e}")


            if not login_successful:
                try:
                    print(f"Login untuk {target_akun} belum berhasil, mencoba alur login melalui tombol 'Ikuti'...")
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

                    print("Menunggu QR code discan (tampilan 'QR code scanned' muncul)...")
                    WebDriverWait(driver, 300).until(
                        EC.presence_of_element_located((By.XPATH, "//p[text()='QR code scanned']"))
                    )
                    print("QR code berhasil discan. Menunggu konfirmasi 'Masuk' di ponsel...")

                    print("Menunggu modal QR code menghilang (menandakan user klik 'Masuk' di HP)...")
                    WebDriverWait(driver, 300).until(
                        EC.invisibility_of_element_located((By.CSS_SELECTOR, '[data-e2e="qr-code"]'))
                    )
                    print("Modal QR code telah menghilang.")
                    
                    print(f"Memverifikasi redirect ke URL profil: {target_url} (setelah modal hilang)...")
                    WebDriverWait(driver, 60).until(
                        EC.url_to_be(target_url)
                    )
                    print("Berhasil dialihkan ke halaman profil.")
                    login_successful = True

                except (TimeoutException, ElementClickInterceptedException) as e:
                    print(f"Gagal login via tombol 'Ikuti' atau scan QR untuk {target_akun}. Error: {e}")
                    print(f"Login gagal setelah semua upaya untuk {target_akun}. Periksa halaman secara manual.")
                except Exception as e:
                    print(f"Terjadi error tak terduga dalam alur login 'Ikuti' untuk {target_akun}: {e}")
                    print(f"Login gagal setelah semua upaya untuk {target_akun}. Periksa halaman secara manual.")

            # BARU: Simpan cookies ke database jika login berhasil
            if login_successful:
                with current_app.app_context():
                    creator_settings.cookies_json = json.dumps(driver.get_cookies())
                    db.session.add(creator_settings)
                    db.session.commit()
                print(f"Cookies berhasil disimpan ke database untuk {target_akun}.")
    
        if login_successful:
            print(f"Login berhasil terdeteksi dan halaman profil {target_akun} dimuat.")
            print(f"Berhasil menavigasi ke profil: {target_akun}")
            print("PERISAI BERHASIL DITEMBUS. Deteksi dasar berhasil dilewati.")

            time.sleep(5) # Beri waktu tambahan setelah login berhasil sebelum berinteraksi lebih lanjut

            max_videos_to_process = 15 # Batasi jumlah video yang akan diproses per sesi

            # --- LANGKAH BARU: GULIR HALAMAN PROFIL UNTUK MEMUAT SEMUA VIDEO ---
            print(f"Mulai menggulir halaman profil {target_akun} untuk memuat semua video...")
            profile_scrollable_element = driver.find_element(By.TAG_NAME, 'body') 
            last_profile_height = driver.execute_script("return arguments[0].scrollHeight", profile_scrollable_element)
            profile_scroll_attempts = 0
            max_profile_scroll_attempts = 5 

            while profile_scroll_attempts < max_profile_scroll_attempts:
                driver.execute_script("arguments[0].scrollTo(0, arguments[0].scrollHeight);", profile_scrollable_element)
                time.sleep(2)
                new_profile_height = driver.execute_script("return arguments[0].scrollHeight", profile_scrollable_element)
                if new_profile_height == last_profile_height:
                    print(f"Tidak ada video baru yang dimuat setelah {profile_scroll_attempts+1} scroll profil. Berhenti.")
                    break
                last_profile_height = new_profile_height
                profile_scroll_attempts += 1
                print(f"Digulir profil {profile_scroll_attempts} kali. Tinggi baru: {new_profile_height}")
            print("Selesai menggulir halaman profil.")

            # --- Kumpulkan semua URL video unik yang memenuhi kriteria setelah menggulir profil ---
            all_video_elements_after_scroll = []
            try:
                all_video_elements_after_scroll = WebDriverWait(driver, 15).until(
                    EC.presence_of_all_elements_located((By.XPATH, "//div[@data-e2e='user-post-item' and .//a[contains(@href, '/video/')]]"))
                )
                print(f"Ditemukan total {len(all_video_elements_after_scroll)} elemen video di DOM setelah scrolling.")
            except TimeoutException:
                print("Tidak ada elemen video yang valid dengan tautan video ditemukan dalam waktu yang ditentukan setelah scrolling. Mengakhiri proses.")
                all_video_elements_after_scroll = []

            unique_unprocessed_video_urls = []
            for video_item_element in all_video_elements_after_scroll:
                try:
                    video_link_element = video_item_element.find_element(By.CSS_SELECTOR, 'a[href*="/video/"]')
                    video_url = video_link_element.get_attribute('href')
                    
                    is_pinned = False
                    try:
                        pinned_badge = video_item_element.find_element(By.XPATH, ".//div[@data-e2e='video-card-badge' and (text()='Pinned' or text()='Disematkan')]")
                        is_pinned = True
                    except NoSuchElementException:
                        pass

                    if not is_pinned and video_url not in processed_video_urls:
                        unique_unprocessed_video_urls.append(video_url)
                        # processed_video_urls.add(video_url) # Akan disimpan ke DB setelah video selesai diproses
                        print(f"   -> Video yang akan diproses ditambahkan ke antrian: {video_url}")
                    else:
                        if is_pinned:
                            print(f"   -> Video disematkan/Pinned ditemukan, melewati (URL: {video_url}).")
                        elif video_url in processed_video_urls:
                            print(f"   -> Video sudah ada di daftar proses (URL: {video_url}), melewati.")
                        else:
                            print(f"   -> Video tidak valid/lainnya, melewati (URL: {video_url}).")

                except NoSuchElementException:
                    print("   -> Peringatan: Tautan video tidak ditemukan dalam item video. Melewati.")
                    continue
                except StaleElementReferenceException:
                    print("   -> StaleElementReferenceException saat mencari tautan video di pengumpulan awal. Melewati.")
                    continue

            if not unique_unprocessed_video_urls:
                print("Tidak ada video terbaru (tidak disematkan/Pinned, belum diproses) yang ditemukan setelah pengguliran profil. Mengakhiri proses.")
            else:
                print(f"Mulai memproses {min(len(unique_unprocessed_video_urls), max_videos_to_process)} video dari antrian.")
                
                videos_processed_count = 0 
                for video_url_to_process in unique_unprocessed_video_urls:
                    if videos_processed_count >= max_videos_to_process:
                        print(f"Batasan {max_videos_to_process} video tercapai. Berhenti memproses video.")
                        break 

                    print(f"\n--- Memproses video: {video_url_to_process} ---")
                    try: # START OF OUTER TRY FOR VIDEO PROCESSING
                        driver.get(target_url) # Kembali ke profil untuk menemukan elemen video yang baru
                        print("Kembali ke halaman profil untuk re-fresh elemen.")
                        time.sleep(5) 

                        video_item_element_on_profile = WebDriverWait(driver, 15).until(
                            EC.presence_of_element_located((By.XPATH, f"//div[@data-e2e='user-post-item']//a[@href='{video_url_to_process}']//ancestor::div[@data-e2e='user-post-item']"))
                        )
                        
                        print(f"Mencoba mengklik video: {video_url_to_process}")
                        WebDriverWait(driver, 15).until(
                            EC.element_to_be_clickable(video_item_element_on_profile)
                        )
                        video_item_element_on_profile.click()
                        print("Video terbaru berhasil diklik.")
                        time.sleep(2) # Beri waktu halaman video dimuat

                        # --- KOREKSI LOGIKA: Cek apakah ini video TikTok Shop (dengan toast) ---
                        tiktok_shop_toast_selector = (By.XPATH, "//div[contains(@class, 'TUXTopToast-content') and text()='View TikTok Shop videos in the TikTok app']")
                        is_tiktok_shop_video = False
                        try:
                            print("   -> Mencoba mendeteksi toast 'Lihat video TikTok Shop'...")
                            WebDriverWait(driver, 2).until( # Tunggu maks 2 detik untuk toast
                                EC.presence_of_element_located(tiktok_shop_toast_selector)
                            )
                            print("   -> TOAST TIKTOK SHOP DITEMUKAN. Ini adalah video TikTok Shop.")
                            is_tiktok_shop_video = True
                        except TimeoutException:
                            print("   -> Toast TikTok Shop TIDAK ditemukan. Ini adalah video reguler.")
                        
                        if not is_tiktok_shop_video:
                            print("   -> Ini bukan video TikTok Shop. Melewatkan video ini karena bot fokus pada video Shop.")
                            # Kembali ke halaman profil sebelum melanjutkan ke video berikutnya
                            driver.get(target_url)
                            print("   -> Kembali ke halaman profil setelah melewatkan video reguler.")
                            time.sleep(5) # Beri waktu profil termuat
                            videos_processed_count += 1 # Hitung sebagai video yang 'diproses' (dilewati)
                            processed_video_urls.add(video_url_to_process) # Tandai sudah diproses/dilewati
                            continue # Lewati sisa alur pemrosesan video ini, lanjut ke video berikutnya
                        # -------------------------------------------------------------------------

                        # --- Dapatkan Transkrip Video ---
                        print(f"Mencoba mendapatkan transkrip untuk video: {video_url_to_process}")
                        video_transcript = get_video_transcript(video_url_to_process) # Panggil fungsi baru
                        
                        if not video_transcript: # BARU: Cek jika transkrip kosong atau gagal
                            print("   -> Transkrip video kosong atau gagal didapatkan. Melewatkan video ini.")
                            driver.get(target_url) # Kembali ke halaman profil
                            print("   -> Kembali ke halaman profil setelah melewatkan video tanpa transkrip.")
                            time.sleep(5) # Beri waktu profil termuat
                            videos_processed_count += 1 # Hitung sebagai video yang 'diproses' (dilewati)
                            processed_video_urls.add(video_url_to_process) # Tandai sudah diproses/dilewati
                            continue # Lanjut ke video berikutnya di loop
                        else:
                            print(f"Transkrip berhasil didapatkan (potongan): {video_transcript[:100]}...")

                        # --- PROSES KOMENTAR ---
                        print("Video terbuka. Menunggu komentar untuk dimuat dan memprosesnya...")
                        
                        comment_count_element_selector = (By.XPATH, "//div[contains(@class, 'DivTabItem') and starts-with(text(), 'Comments (')]")
                        num_comments = 0
                        try: # Inner try for comment count
                            comment_count_element = WebDriverWait(driver, 15).until(
                                EC.presence_of_element_located(comment_count_element_selector)
                            )
                            comment_count_text = comment_count_element.text
                            num_comments_str = comment_count_text.split('(')[1].split(')')[0].replace(',', '')
                            num_comments = int(num_comments_str)
                            print(f"Total komentar terdeteksi: {num_comments}")

                            if num_comments == 0:
                                print("Tidak ada komentar pada video ini (jumlah = 0). Melewatkan balasan komentar.")
                                raise StopIteration # Menggunakan StopIteration untuk keluar dari blok try
                            else:
                                print("Komentar ditemukan, melanjutkan pemrosesan.")
                        except TimeoutException:
                            print("Tidak dapat menemukan elemen jumlah komentar dalam waktu yang ditentukan. Asumsi ada komentar dan melanjutkan.")
                        except ValueError:
                            print(f"Gagal mengurai jumlah komentar dari teks: '{comment_count_text}'. Melanjutkan tanpa jumlah pasti.")
                        except StopIteration:
                            pass # Tangani StopIteration yang kita sengaja picu
                        except Exception as e:
                            print(f"Error tak terduga saat membaca jumlah komentar: {e}. Melanjutkan tanpa jumlah pasti.")

                        if num_comments > 0 or (num_comments == 0 and "Gagal mengurai" in locals().get('e', '')):
                            try: # Inner try for comment processing
                                WebDriverWait(driver, 10).until(
                                    EC.presence_of_element_located((By.CSS_SELECTOR, '[data-e2e="comment-level-1"]'))
                                )
                                print("Setidaknya satu komentar awal dimuat.")

                                scrollable_comment_panel_selector = (By.CSS_SELECTOR, '.css-1qp5gj2-DivCommentListContainer') 
                                
                                try: # Inner try for finding scrollable element
                                    scrollable_element = WebDriverWait(driver, 5).until(
                                        EC.presence_of_element_located(scrollable_comment_panel_selector)
                                    )
                                    print("Elemen scrollable komentar ditemukan.")
                                except:
                                    print("Elemen scrollable komentar tidak ditemukan. Mencoba scroll body.")
                                    scrollable_element = driver.find_element(By.TAG_NAME, 'body')

                                last_height = driver.execute_script("return arguments[0].scrollHeight", scrollable_element)
                                scroll_attempts = 0
                                
                                initial_comments_on_load = 20 
                                comments_per_scroll_load = 20

                                if num_comments > initial_comments_on_load:
                                    estimated_scrolls_needed = math.ceil((num_comments - initial_comments_on_load) / comments_per_scroll_load)
                                    max_scroll_attempts = min(estimated_scrolls_needed, 50)
                                else:
                                    max_scroll_attempts = 0

                                scroll_pause_time = 2

                                print(f"Mulai menggulir komentar (diperkirakan {max_scroll_attempts} upaya)...")
                                while scroll_attempts < max_scroll_attempts:
                                    driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", scrollable_element)
                                    time.sleep(scroll_pause_time)
                                    new_height = driver.execute_script("return arguments[0].scrollHeight", scrollable_element)
                                    if new_height == last_height:
                                        print(f"Tidak ada komentar baru yang dimuat setelah {scroll_attempts+1} scroll. Berhenti.")
                                        break
                                    last_height = new_height
                                    scroll_attempts += 1
                                    print(f"Digulir {scroll_attempts} kali. Tinggi baru: {new_height}")

                                print("Selesai menggulir komentar.")
                                
                                all_comments_elements = driver.find_elements(By.CSS_SELECTOR, '.css-1i7ohvi-DivCommentItemContainer.eo72wou0')
                                print(f"Total {len(all_comments_elements)} komentar ditemukan untuk diproses setelah scrolling.")
                                
                                comment_replied_in_video = False
                                comments_processed_count_in_video = 0 
                                max_comments_to_process_per_video = 50 

                                for comment_element in all_comments_elements:
                                    if comments_processed_count_in_video >= max_comments_to_process_per_video:
                                        print(f"Batasan {max_comments_to_process_per_video} komentar tercapai. Berhenti memproses komentar di video ini.")
                                        break

                                    comment_text = ""
                                    try:
                                        comment_text_element = comment_element.find_element(By.CSS_SELECTOR, '[data-e2e^="comment-level-"]')
                                        comment_text = comment_text_element.text
                                    except NoSuchElementException:
                                        print("Gagal mendapatkan teks komentar. Melewati.")
                                        continue
                                    except StaleElementReferenceException:
                                        print("StaleElementReferenceException: Melewati komentar ini, mungkin perlu me-refresh daftar.")
                                        continue

                                    print(f"\nMemproses komentar: '{comment_text}'")

                                    # Filter 1: Cek apakah komentar hanya terdiri dari emoji (tanpa teks alfanumerik)
                                    stripped_comment_text = re.sub(r'\s+', '', comment_text)
                                    if not any(char.isalnum() for char in stripped_comment_text):
                                        print("   -> Komentar hanya terdiri dari emoji. Melewati.")
                                        continue

                                    # Filter 2: Cek apakah komentar berisi indikator foto/gambar
                                    comment_text_lower = comment_text.lower()
                                    if "[写真]" in comment_text_lower or "[foto]" in comment_text_lower or "[image]" in comment_text_lower or "[photo]" in comment_text_lower:
                                        print("   -> Komentar berisi indikator foto/gambar. Melewati.")
                                        continue

                                    # Filter 3: Cek apakah komentar dibuat oleh Creator (Filter yang sudah ada)
                                    is_creator_comment = False
                                    try:
                                        creator_badge = comment_element.find_element(By.XPATH, ".//span[contains(@data-e2e, 'comment-creator-') and (text()='Creator' or text()='Pembuat')]")
                                        is_creator_comment = True
                                    except NoSuchElementException:
                                        pass

                                    if is_creator_comment:
                                        print("   -> Ini adalah komentar dari Creator. Melewati.")
                                        continue

                                    # Filter 4: Cek apakah komentar sudah dibalas oleh Creator (Filter yang sudah ada)
                                    has_creator_replied = False
                                    try:
                                        reply_container = comment_element.find_element(By.CSS_SELECTOR, ".css-zn6r1p-DivReplyContainer.eo72wou1")
                                        creator_reply = reply_container.find_element(By.XPATH, ".//div[contains(@class, 'DivCommentContentContainer')]//span[contains(@data-e2e, 'comment-creator-') and (text()='Creator' or text()='Pembuat')]")
                                        has_creator_replied = True
                                    except NoSuchElementException:
                                        pass

                                    if has_creator_replied:
                                        print("   -> Komentar ini sudah dibalas oleh Creator. Melewati.")
                                        continue
                                    
                                    print(f"   -> Lolos filter. Mencoba membalas komentar: '{comment_text}'")
                                    try: # Inner try for replying
                                        # Tambahkan wait untuk memastikan elemen pengganggu tidak ada
                                        try: # Innermost try for invisibility
                                            WebDriverWait(driver, 2).until(
                                                EC.invisibility_of_element_located((By.CSS_SELECTOR, '.css-3yeu18-DivTabMenuContainer.e1aa9wve0'))
                                            )
                                            print("   -> Elemen tab menu pengganggu tidak terlihat.")
                                        except TimeoutException:
                                            print("   -> Elemen tab menu pengganggu tidak menjadi tidak terlihat dalam waktu yang ditentukan, melanjutkan.")
                                        
                                        answer_comment_button = comment_element.find_element(By.CSS_SELECTOR, '[data-e2e^="comment-reply-"]')
                                        WebDriverWait(driver, 5).until(EC.element_to_be_clickable(answer_comment_button))
                                        answer_comment_button.click()
                                        print("   -> Tombol 'Jawab' berhasil diklik.")
                                        time.sleep(1)
                                        
                                        # Bersihkan teks komentar dari emoji non-BMP sebelum mengirim
                                        cleaned_comment_for_reply = re.sub(r'[^\U00000000-\U0000FFFF]', '', comment_text)

                                        text_box = WebDriverWait(driver, 10).until(
                                            EC.presence_of_element_located((By.XPATH, "//div[@role='textbox' and @contenteditable='true']"))
                                        )
                                        
                                        # --- PENGGUNAAN LLM BARU UNTUK MENGHASILKAN BALASAN ---
                                        if video_transcript:
                                            ai_generated_reply = generate_ai_reply(
                                                video_transcript, 
                                                cleaned_comment_for_reply, 
                                                creator_character_description
                                            )
                                            
                                            # Filter balasan AI dari emoji non-BMP
                                            ai_generated_reply_cleaned = re.sub(r'[^\U00000000-\U0000FFFF]', '', ai_generated_reply)
                                            
                                            # Cek apakah AI menginstruksikan untuk tidak membalas
                                            if ai_generated_reply_cleaned == "[TIDAK_MEMBALAS]":
                                                print("   -> AI menginstruksikan untuk TIDAK MEMBALAS komentar ini karena tidak relevan/valid.")
                                                print("   -> Melewati balasan karena instruksi AI.")
                                                comments_processed_count_in_video += 1
                                                time.sleep(1)
                                                continue # Lewati ke komentar berikutnya di loop

                                            reply_text_to_send = ai_generated_reply_cleaned
                                        else:
                                            print("   -> Peringatan: Transkrip video tidak tersedia. Menggunakan balasan default.")
                                            reply_text_to_send = ":)"
                                        # ---------------------------------------------------
                                        
                                        text_box.send_keys(reply_text_to_send)
                                        print(f"   -> Mengetik balasan AI: \"{reply_text_to_send}\"")
                                        time.sleep(1)
                                        
                                        post_button_selector = (By.XPATH, "//div[@role='button' and @aria-label='Post']") 

                                        WebDriverWait(driver, 10).until(
                                            element_attribute_is(post_button_selector, "aria-disabled", "false")
                                        )
                                        print("   -> Tombol 'Post' terdeteksi aktif secara logis (aria-disabled='false').")

                                        # Tunggu elemen pengganggu (pesan sukses/loading) menghilang sebelum klik Post
                                        interfering_element_selector = (By.CSS_SELECTOR, '.css-1ml20fp-DivTextContainer.e1hknyby2')
                                        try:
                                            WebDriverWait(driver, 2).until(
                                                EC.invisibility_of_element_located(interfering_element_selector)
                                            )
                                            print("   -> Elemen pengganggu 'Post' (DivTextContainer) tidak terlihat.")
                                        except TimeoutException:
                                            print("   -> Peringatan: Elemen pengganggu 'Post' masih terlihat atau tidak menghilang dalam waktu yang ditentukan.")
                                        
                                        post_button = WebDriverWait(driver, 5).until(
                                            EC.element_to_be_clickable(post_button_selector)
                                        )
                                        post_button.click()
                                        print("   -> Tombol 'Post' berhasil diklik.")
                                        comment_replied_in_video = True
                                        comments_processed_count_in_video += 1
                                        time.sleep(2)
                                        # Hapus 'break' di bawah ini untuk membalas lebih dari satu komentar per video
                                        # break 
                                        
                                    except TimeoutException as e:
                                        print(f"   -> Gagal berinteraksi dengan elemen balasan (timeout): {e}. Melewati balasan ini.")
                                    except ElementClickInterceptedException as e:
                                        print(f"   -> Tombol/text box terhalang: {e}. Melewati balasan ini.")
                                    except Exception as e:
                                        print(f"   -> Terjadi error tak terduga saat membalas komentar: {e}. Melewati balasan ini.")
                                        
                                if not comment_replied_in_video:
                                    print("Tidak ada komentar yang memenuhi kriteria filter untuk dibalas di video ini.")

                            except TimeoutException:
                                print("Tidak ada komentar yang terlihat (initial load) pada video ini dalam waktu yang ditentukan. Melewatkan balasan komentar.")
                            except Exception as e:
                                print(f"Terjadi error tak terduga saat memproses komentar (di luar loop balasan): {e}. Melewatkan balasan komentar.")

                        # --- KLIK TOMBOL CLOSE VIDEO UNTUK KEMBALI KE PROFIL ---
                        print("Selesai memproses komentar di video ini. Mencoba menutup video untuk kembali ke profil.")
                        try: # Inner try for closing
                            close_button_selector = (By.XPATH, "//button[@role='button' and @aria-label='Close']")
                            close_button = WebDriverWait(driver, 10).until(
                                EC.element_to_be_clickable(close_button_selector)
                            )
                            close_button.click()
                            print("Tombol 'Close' video berhasil diklik.")
                            time.sleep(5)
                            WebDriverWait(driver, 10).until(EC.url_to_be(target_url))
                            print("Berhasil kembali ke halaman profil.")
                            # videos_processed_count += 1 # Sudah dihitung di atas
                        except TimeoutException as e:
                            print(f"Gagal menemukan atau mengklik tombol 'Close' video: {e}. Mungkin sudah di halaman profil atau ada masalah lain.")
                            driver.get(target_url)
                            print("Melakukan navigasi paksa kembali ke halaman profil.")
                            time.sleep(5)
                            # videos_processed_count += 1 # Sudah dihitung di atas
                        except Exception as e:
                            print(f"Terjadi error tak terduga saat menutup video: {e}.")
                            # videos_processed_count += 1 # Sudah dihitung di atas
                    
                    except Exception as e: # This is the except for try at line ~256
                        print(f"Terjadi error saat mencoba klik atau memproses video dari profil: {e}. Melanjutkan ke video berikutnya jika ada.")
                        driver.get(target_url) 
                        print("Melakukan navigasi paksa kembali ke halaman profil setelah error video.")
                        time.sleep(5)
                    finally:
                        # Pastikan kita selalu menambahkan URL ke processed_video_urls setelah mencoba memproses video
                        # Ini mencegah bot mengulang video yang gagal sekalipun
                        processed_video_urls.add(video_url_to_process)
                        videos_processed_count += 1 # Pastikan ini selalu bertambah setelah setiap video dicoba
                        # BARU: Simpan processed_video_urls ke database setelah setiap video
                        with current_app.app_context():
                            creator_settings.processed_video_urls_json = json.dumps(list(processed_video_urls))
                            db.session.add(creator_settings)
                            db.session.commit()
                        print(f"URL video {video_url_to_process} ditambahkan ke processed_video_urls dan disimpan ke DB.")


                print(f"Selesai memproses {videos_processed_count} video untuk {target_akun}.")

            # BARU: Update last_run_at di database
            with current_app.app_context():
                creator_settings.last_run_at = datetime.now()
                db.session.add(creator_settings)
                db.session.commit()
            print(f"Waktu terakhir bot dijalankan untuk {target_akun} diperbarui di database.")

        else:
            print(f"Login gagal untuk {target_akun}, tidak bisa melanjutkan operasi video dan komentar.")


    finally:
        if driver:
            driver.quit()
            print(f"Operasi selesai untuk {target_akun}. Browser ditutup.")
        else:
            print(f"Operasi selesai untuk {target_akun}. Driver tidak diinisialisasi atau sudah ditutup.")
