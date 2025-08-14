import undetected_chromedriver as uc
import time
import math
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, NoSuchElementException, StaleElementReferenceException, WebDriverException # Import WebDriverException
import pickle
import os
import re
import json
from datetime import datetime

# Import fungsi dari service files
from .transcription_service import get_video_transcript
from .llm_service import generate_ai_reply

# BARU: Import db dan model User, ProcessedVideo
from backend.models import db, User, ProcessedVideo 
from flask import Flask 

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
def run_tiktok_bot_task(user_id: int, app_instance: Flask):
    driver = None
    login_successful = False
    target_akun = "Unknown_User" # Inisialisasi default agar selalu tersedia di 'finally'

    try: # <--- AWALI DENGAN BLOK TRY UTAMA DI SINI
        # --- SELURUH LOGIKA BOT AKAN DIBUNGKUS DALAM SATU app_context ---
        # Ini adalah kunci untuk menghindari DetachedInstanceError
        with app_instance.app_context():
            # Fetch user data for initial setup (target_akun, description, initial cookies)
            user = User.query.get(user_id)
            if not user:
                print(f"ERROR: User settings not found for ID {user_id}. Aborting bot task.")
                return

            target_akun = user.tiktok_username # Set target_akun di sini
            target_url = f"https://www.tiktok.com/@{target_akun}"
            creator_character_description = user.creator_character_description
            cookies = json.loads(user.cookies_json) if user.cookies_json else []

            print(f"MEMULAI OPERASI 'TEMBUS PERISAI' untuk {target_akun}...")

            # --- Login Retry Logic (seluruhnya di dalam with app_instance.app_context()) ---
            MAX_LOGIN_RETRIES = 3
            login_retry_count = 0
            while not login_successful and login_retry_count < MAX_LOGIN_RETRIES:
                login_retry_count += 1
                print(f"\n--- Percobaan Login ke TikTok (Upaya {login_retry_count}/{MAX_LOGIN_RETRIES}) ---")

                if driver:
                    try:
                        driver.quit()
                        print("Driver sebelumnya ditutup untuk memulai ulang.")
                    except Exception as e:
                        print(f"Peringatan: Gagal menutup driver sebelumnya: {e}")
                
                options = uc.ChromeOptions()
                try:
                    driver = uc.Chrome(options=options)
                except Exception as e:
                    print(f"ERROR: Gagal menginisialisasi Chrome driver: {e}. Akan mencoba lagi.")
                    time.sleep(10) 
                    continue 

                try:
                    # --- Coba muat cookies yang sudah ada ---
                    if cookies:
                        print(f"Cookies ditemukan di database untuk {target_akun}. Mencoba memuat cookies...")
                        driver.get("https://www.tiktok.com/") 
                        for cookie in cookies:
                            if 'expiry' in cookie and isinstance(cookie['expiry'], float):
                                cookie['expiry'] = int(cookie['expiry'])
                            if 'sameSite' in cookie and cookie['sameSite'] not in ['Strict', 'Lax', 'None']:
                                del cookie['sameSite']
                            elif 'sameSite' in cookie and cookie['sameSite'] == 'None':
                                cookie['sameSite'] = 'None' 
                            
                            driver.add_cookie(cookie)
                        
                        driver.get(target_url) 
                        print("Cookies berhasil dimuat dan browser diarahkan ke profil.")
                        WebDriverWait(driver, 15).until(EC.url_to_be(target_url)) 
                        login_successful = True
                        time.sleep(5) 
                        user.cookies_json = json.dumps(driver.get_cookies())
                        db.session.add(user)
                        db.session.commit()
                        print(f"Cookies diperbarui dan disimpan ke database untuk {target_akun}.")

                    # --- Jika login belum berhasil dengan cookies, coba QR code ---
                    if not login_successful:
                        print(f"Cookies gagal atau tidak ditemukan untuk {target_akun}. Memulai alur login QR code...")
                        driver.get(target_url) 
                        time.sleep(10) 

                        # --- ATTEMPT LOGIN FLOW 1: Melalui modal "chose your interest" jika ada ---
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
                            print(f"Gagal login via modal 'chose your interest' atau scan QR: {e}. Mencoba alur alternatif.")
                        except Exception as e:
                            print(f"Terjadi error tak terduga dalam alur login 'chose your interest': {e}")


                    if not login_successful:
                        try:
                            print(f"Login belum berhasil, mencoba alur login melalui tombol 'Ikuti'...")
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
                            print(f"Gagal login via tombol 'Ikuti' atau scan QR: {e}")
                            print(f"Login gagal setelah semua upaya. Periksa halaman secara manual.")
                        except Exception as e:
                            print(f"Terjadi error tak terduga dalam alur login 'Ikuti': {e}")
                            print(f"Login gagal setelah semua upaya. Periksa halaman secara manual.")

                    if login_successful:
                        user.cookies_json = json.dumps(driver.get_cookies())
                        db.session.add(user)
                        db.session.commit()
                        print(f"Cookies berhasil disimpan ke database untuk {target_akun}.")
                except WebDriverException as we:
                    print(f"ERROR: WebDriver mengalami masalah: {we}. Akan mencoba lagi.")
                except Exception as e:
                    print(f"ERROR: Terjadi kesalahan umum selama proses login: {e}. Akan mencoba lagi.")
                
                if not login_successful:
                    print(f"Login gagal setelah upaya {login_retry_count}. Menunggu 10 detik sebelum retry...")
                    time.sleep(10) 
            
            if not login_successful:
                print(f"Login gagal setelah {MAX_LOGIN_RETRIES} upaya untuk {target_akun}. Tidak bisa melanjutkan operasi bot.")
                if driver: driver.quit() 
                return 

            # --- Lanjutkan jika login berhasil (masih dalam with app_instance.app_context()) ---
            print(f"Login berhasil terdeteksi dan halaman profil {target_akun} dimuat.")
            print(f"Berhasil menavigasi ke profil: {target_akun}")
            print("PERISAI BERHASIL DITEMBUS. Deteksi dasar berhasil dilewati.")

            time.sleep(5) 

            max_videos_to_process_per_run = 15 

            # --- LANGKAH: GULIR HALAMAN PROFIL UNTUK MEMUAT SEMUA VIDEO ---
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

            recent_unpinned_video_urls = []
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

                    if not is_pinned: 
                        recent_unpinned_video_urls.append(video_url)
                        print(f"   -> Video non-disematkan ditambahkan ke antrean: {video_url}")
                    else:
                        print(f"   -> Video disematkan/Pinned ditemukan, melewati (URL: {video_url}).")

                except NoSuchElementException:
                    print("   -> Peringatan: Tautan video tidak ditemukan dalam item video. Melewati.")
                    continue
                except StaleElementReferenceException:
                    print("   -> StaleElementReferenceException saat mencari tautan video di pengumpulan awal. Melewati.")
                    continue

            seen_urls = set()
            videos_to_process_this_run = []
            for url in recent_unpinned_video_urls:
                if url not in seen_urls:
                    videos_to_process_this_run.append(url)
                    seen_urls.add(url)
            
            videos_to_process_this_run = videos_to_process_this_run[:max_videos_to_process_per_run]

            if not videos_to_process_this_run:
                print("Tidak ada video terbaru (tidak disematkan/Pinned) yang ditemukan untuk diproses. Mengakhiri proses.")
            else:
                print(f"Mulai memproses {len(videos_to_process_this_run)} video dari antrian.")
                
                videos_processed_count = 0 
                MAX_VIDEO_RETRIES = 2 
                
                for video_url_to_process in videos_to_process_this_run:
                    if videos_processed_count >= max_videos_to_process_per_run:
                        print(f"Batasan {max_videos_to_process_per_run} video tercapai. Berhenti memproses video.")
                        break 

                    video_process_successful = False
                    video_retry_count = 0

                    while not video_process_successful and video_retry_count < MAX_VIDEO_RETRIES:
                        video_retry_count += 1
                        print(f"\n--- Memproses video: {video_url_to_process} (Upaya {video_retry_count}/{MAX_VIDEO_RETRIES}) ---")

                        try:
                            # NAVIGASI DAN KLIK VIDEO
                            driver.get(target_url) 
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
                            time.sleep(2) 

                            # CEK VIDEO TIKTOK SHOP
                            tiktok_shop_toast_selector = (By.XPATH, "//div[contains(@class, 'TUXTopToast-content') and text()='View TikTok Shop videos in the TikTok app']")
                            is_tiktok_shop_video = False
                            try:
                                print("   -> Mencoba mendeteksi toast 'Lihat video TikTok Shop'...")
                                WebDriverWait(driver, 2).until( 
                                    EC.presence_of_element_located(tiktok_shop_toast_selector)
                                )
                                print("   -> TOAST TIKTOK SHOP DITEMUKAN. Ini adalah video TikTok Shop.")
                                is_tiktok_shop_video = True
                            except TimeoutException:
                                print("   -> Toast TikTok Shop TIDAK ditemukan. Ini adalah video reguler.")
                            
                            if not is_tiktok_shop_video:
                                print("   -> Ini bukan video TikTok Shop. Melewatkan video ini karena bot fokus pada video Shop.")
                                video_process_successful = True 
                                continue 

                            # --- Dapatkan Transkrip Video (dengan user_id dan app_instance) ---
                            print(f"Mencoba mendapatkan transkrip untuk video: {video_url_to_process}")
                            video_transcript = get_video_transcript(video_url_to_process, user.id, app_instance) 
                            
                            if not video_transcript: 
                                print("   -> Transkrip video kosong atau gagal didapatkan. Melewatkan video ini.")
                                video_process_successful = True 
                                continue 
                            else:
                                print(f"Transkrip berhasil didapatkan (potongan): {video_transcript[:100]}...")

                            # --- PROSES KOMENTAR ---
                            print("Video terbuka. Menunggu komentar untuk dimuat dan memprosesnya...")
                            
                            comment_count_element_selector = (By.XPATH, "//div[contains(@class, 'DivTabItem') and starts-with(text(), 'Comments (')]")
                            num_comments = 0
                            try: 
                                comment_count_element = WebDriverWait(driver, 15).until(
                                    EC.presence_of_element_located(comment_count_element_selector)
                                )
                                comment_count_text = comment_count_element.text
                                num_comments_str = comment_count_text.split('(')[1].split(')')[0].replace(',', '')
                                num_comments = int(num_comments_str)
                                print(f"Total komentar terdeteksi: {num_comments}")

                                if num_comments == 0:
                                    print("Tidak ada komentar pada video ini (jumlah = 0). Melewatkan balasan komentar.")
                                    raise StopIteration 
                                else:
                                    print("Komentar ditemukan, melanjutkan pemrosesan.")
                            except TimeoutException:
                                print("Tidak dapat menemukan elemen jumlah komentar dalam waktu yang ditentukan. Asumsi ada komentar dan melanjutkan.")
                            except ValueError:
                                print(f"Gagal mengurai jumlah komentar dari teks: '{comment_count_text}'. Melanjutkan tanpa jumlah pasti.")
                            except StopIteration:
                                pass 
                            except Exception as e:
                                print(f"Error tak terduga saat membaca jumlah komentar: {e}. Melanjutkan tanpa jumlah pasti.")

                            if num_comments > 0 or (num_comments == 0 and "Gagal mengurai" in locals().get('e', '')):
                                try: 
                                    WebDriverWait(driver, 10).until(
                                        EC.presence_of_element_located((By.CSS_SELECTOR, '[data-e2e="comment-level-1"]'))
                                    )
                                    print("Setidaknya satu komentar awal dimuat.")

                                    scrollable_comment_panel_selector = (By.CSS_SELECTOR, '.css-1qp5gj2-DivCommentListContainer') 
                                    
                                    try: 
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
                                        try: 
                                            try: 
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
                                            
                                            cleaned_comment_for_reply = re.sub(r'[^\U00000000-\U0000FFFF]', '', comment_text)

                                            text_box = WebDriverWait(driver, 10).until(
                                                EC.presence_of_element_located((By.XPATH, "//div[@role='textbox' and @contenteditable='true']"))
                                            )
                                            
                                            if video_transcript:
                                                ai_generated_reply = generate_ai_reply(
                                                    video_transcript, 
                                                    cleaned_comment_for_reply, 
                                                    creator_character_description
                                                )
                                                
                                                ai_generated_reply_cleaned = re.sub(r'[^\U00000000-\U0000FFFF]', '', ai_generated_reply)
                                                
                                                if ai_generated_reply_cleaned == "[TIDAK_MEMBALAS]":
                                                    print("   -> AI menginstruksikan untuk TIDAK MEMBALAS komentar ini karena tidak relevan/valid.")
                                                    print("   -> Melewati balasan karena instruksi AI.")
                                                    comments_processed_count_in_video += 1
                                                    time.sleep(1)
                                                    continue 

                                                reply_text_to_send = ai_generated_reply_cleaned
                                            else:
                                                print("   -> Peringatan: Transkrip video tidak tersedia. Menggunakan balasan default.")
                                                reply_text_to_send = ":)"
                                                
                                            text_box.send_keys(reply_text_to_send)
                                            print(f"   -> Mengetik balasan AI: \"{reply_text_to_send}\"")
                                            time.sleep(1)
                                            
                                            post_button_selector = (By.XPATH, "//div[@role='button' and @aria-label='Post']") 

                                            WebDriverWait(driver, 10).until(
                                                element_attribute_is(post_button_selector, "aria-disabled", "false")
                                            )
                                            print("   -> Tombol 'Post' terdeteksi aktif secara logis (aria-disabled='false').")

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

                            print("Selesai memproses komentar di video ini. Mencoba menutup video untuk kembali ke profil.")
                            try: 
                                close_button_selector = (By.XPATH, "//button[@role='button' and @aria-label='Close']")
                                close_button = WebDriverWait(driver, 10).until(
                                    EC.element_to_be_clickable(close_button_selector)
                                )
                                close_button.click()
                                print("Tombol 'Close' video berhasil diklik.")
                                time.sleep(5)
                                WebDriverWait(driver, 10).until(EC.url_to_be(target_url))
                                print("Berhasil kembali ke halaman profil.")
                            except TimeoutException as e:
                                print(f"Gagal menemukan atau mengklik tombol 'Close' video: {e}. Mungkin sudah di halaman profil atau ada masalah lain.")
                                driver.get(target_url) 
                                print("Melakukan navigasi paksa kembali ke halaman profil.")
                                time.sleep(5)
                            except Exception as e:
                                print(f"Terjadi error tak terduga saat menutup video: {e}.")
                            
                            video_process_successful = True 
                        
                        except (WebDriverException, TimeoutException, ElementClickInterceptedException, StaleElementReferenceException) as e:
                            print(f"ERROR SAAT MEMPROSES VIDEO {video_url_to_process} (Upaya {video_retry_count}/{MAX_VIDEO_RETRIES}): {e}")
                            print("Mencoba me-refresh halaman profil dan menunggu sebelum mencoba lagi video yang sama...")
                            if driver:
                                try:
                                    driver.get(target_url) 
                                    time.sleep(5)
                                except WebDriverException as nav_e:
                                    print(f"ERROR: Gagal menavigasi kembali ke profil setelah error: {nav_e}. Driver mungkin perlu diinisialisasi ulang.")
                                    if driver: driver.quit()
                                    driver = None 
                                    time.sleep(5) 
                            else: 
                                print("Driver tidak aktif. Mencoba inisialisasi ulang.")
                                options = uc.ChromeOptions()
                                try:
                                    driver = uc.Chrome(options=options)
                                    time.sleep(5)
                                except Exception as init_e:
                                    print(f"ERROR: Gagal inisialisasi driver pada retry video: {init_e}. Mengakhiri retry untuk video ini.")
                                    break 
                            time.sleep(5) 
                        except Exception as e:
                            print(f"ERROR TAK TERDUGA SAAT MEMPROSES VIDEO {video_url_to_process} (Upaya {video_retry_count}/{MAX_VIDEO_RETRIES}): {e}")
                            break 

                    videos_processed_count += 1 

                if not video_process_successful:
                    print(f"Video {video_url_to_process} gagal diproses setelah {MAX_VIDEO_RETRIES} upaya. Melewatkan.")

            print(f"Selesai memproses {videos_processed_count} video untuk {target_akun}.")

            # BARU: Update last_run_at di database
            user.last_run_at = datetime.now() 
            db.session.add(user) 
            db.session.commit()
            print(f"Waktu terakhir bot dijalankan untuk {target_akun} diperbarui di database.")

    except Exception as e: # <--- TANGKAP EXCEPTION DARI BLOK TRY UTAMA
        print(f"ERROR FATAL SELAMA OPERASI BOT UNTUK {target_akun}: {e}")
    finally: # <--- BLOK FINALLY SEKARANG BERPASANGAN DENGAN TRY UTAMA
        if driver:
            driver.quit()
            print(f"Operasi selesai untuk {target_akun}. Browser ditutup.")
        else:
            print(f"Operasi selesai untuk {target_akun}. Driver tidak diinisialisasi atau sudah ditutup.")
