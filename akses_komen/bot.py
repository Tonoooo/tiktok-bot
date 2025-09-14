import undetected_chromedriver as uc
import time
import math # Tambahkan math import
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, NoSuchElementException, StaleElementReferenceException, WebDriverException # Tambahkan WebDriverException
import pickle # Dipertahankan untuk sementara jika ada logika yang masih menggunakannya
import os
import re
import json
from datetime import datetime

# PERUBAHAN: Import APIClient dan get_video_transcript, generate_ai_reply
from akses_komen.api_client import APIClient
from akses_komen.transcription_service import get_video_transcript
from akses_komen.llm_service import generate_ai_reply

# BARU: Import db dan model User, ProcessedVideo - DIHAPUS KARENA TIDAK DIGUNAKAN LAGI
# from backend.models import db, User, ProcessedVideo 
# from flask import Flask 


# Custom Expected Condition untuk memeriksa atribut 'aria-disabled'
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

# PERUBAHAN: Fungsi utama bot sekarang menerima user_id dan api_client
def run_tiktok_bot_task(user_id: int, api_client: APIClient):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Memulai tugas bot untuk user ID: {user_id}")
    driver = None
    
    try:
        # --------------- Mengambil user settings dari APIClient ---------------
        user_settings = api_client.get_user_settings(user_id)
        if not user_settings:
            print(f"ERROR: User {user_id} tidak ditemukan di API atau gagal mengambil pengaturan.")
            return

        tiktok_username = user_settings.get('tiktok_username')
        creator_character_description = user_settings.get('creator_character_description', "")
        
        # ------------- Memuat cookies dari user_settings yang didapat dari API -------------
        cookies_json = user_settings.get('cookies_json')
        if cookies_json:
            cookies = json.loads(cookies_json)
        else:
            cookies = []
            print(f"Peringatan: Tidak ada cookies yang ditemukan untuk user {user_id}. Login mungkin diperlukan lagi.")

        if not tiktok_username:
            print(f"ERROR: tiktok_username tidak ditemukan untuk user {user_id}. Bot tidak dapat berjalan tanpa ini.")
            return

        # =========================
        # STEALTH HEADLESS OPTIONS
        # =========================
        options = uc.ChromeOptions()
        options.add_argument('--headless') 
        options.add_argument('--disable-gpu') # Penting untuk kinerja dan rendering di beberapa sistem
        options.add_argument('--no-sandbox') # Penting untuk Linux/Docker
        options.add_argument('--disable-dev-shm-usage') # Mengatasi masalah resource
        options.add_argument('--window-size=1280,800') # Tetapkan ukuran jendela yang realistis
        options.add_argument('--disable-blink-features=AutomationControlled') # Anti-deteksi
        # options.add_argument(
        #     '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        #     'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
        # ) # User-Agent yang umum
        options.add_argument('--disable-setuid-sandbox')
        options.add_argument('--lang=en-US,en;q=0.9') # Mengatur bahasa browser ke Inggris AS
        driver = uc.Chrome(options=options)
        print("WebDriver berhasil diinisialisasi.")

        # Buka TikTok
        target_url = f"https://www.tiktok.com/@{tiktok_username}"
        driver.get(target_url)
        print(f"Navigasi ke: {target_url}")
        time.sleep(5)

        # Muat cookies jika ada
        if cookies:
            for cookie in cookies:
                # Menghilangkan atribut 'domain' yang bisa menyebabkan error jika tidak match
                if 'domain' in cookie:
                    del cookie['domain']
                driver.add_cookie(cookie)
            driver.refresh()
            print("Cookies dimuat dan halaman direfresh.")
            time.sleep(5)

            videos_area_loaded_ok = False
            for attempt in range(3): # Coba maksimal 3 kali untuk memuat area video
                print(f"Memeriksa status area video di halaman profil (Percobaan {attempt + 1})...")
                try:
                    # Coba temukan error container 'Something Went Wrong' di area video
                    error_container = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'div.css-1w7vxma-5e6d46e3--DivErrorContainer'))
                    )
                    # Jika error container ditemukan, coba klik tombol Refresh di dalamnya
                    refresh_button = error_container.find_element(By.CSS_SELECTOR, 'button.ebef5j00')
                    
                    print("Deteksi 'Something went wrong' di area video. Mengklik tombol Refresh.")
                    driver.execute_script("arguments[0].click();", refresh_button) # Gunakan JS click untuk keandalan
                    time.sleep(10) # Beri waktu untuk refresh dan memuat ulang area video
                    # Loop akan mencoba lagi di iterasi berikutnya setelah refresh

                except TimeoutException:
                    # Jika error container tidak muncul dalam 5 detik, anggap area video sudah dimuat dengan baik
                    print("Area video tampaknya dimuat dengan baik (tidak ada 'Something Went Wrong').")
                    videos_area_loaded_ok = True
                    break # Keluar dari loop jika tidak ada error
                except NoSuchElementException:
                    # Jika error container tidak ditemukan (misal, selector salah atau belum muncul),
                    # anggap area video dimuat dengan baik
                    print("Tidak ada elemen error 'Something Went Wrong' yang terdeteksi di area video. Menganggap area video dimuat.")
                    videos_area_loaded_ok = True
                    break
                except Exception as ex:
                    print(f"ERROR saat mencoba menangani 'Something Went Wrong' di area video: {ex}. Mencoba refresh manual.")
                    driver.refresh() # Sebagai fallback jika ada error lain
                    time.sleep(10) # Beri waktu setelah refresh
            
            if not videos_area_loaded_ok:
                print("Gagal memuat area video setelah beberapa kali percobaan. Mengakhiri tugas bot.")
                return # Bot berhenti di sini jika area video tidak dimuat dengan benar

            # Memverifikasi apakah login berhasil setelah memuat cookies
            # Pemeriksaan ini tetap penting untuk memastikan bot berada di halaman profil yang benar secara keseluruhan.
            current_url_base = driver.current_url.split('?')[0]
            target_url_base = target_url.split('?')[0]
            if not (current_url_base == target_url_base or current_url_base.startswith(f"https://www.tiktok.com/@{tiktok_username}")):
                print(f"Peringatan: Tidak berhasil mencapai halaman profil setelah loading cookies. URL saat ini: {driver.current_url}. Akan mencoba refresh lagi.")
                driver.get(target_url) # Coba refresh lagi
                time.sleep(5)
                current_url_base = driver.current_url.split('?')[0]
                if not (current_url_base == target_url_base or current_url_base.startswith(f"https://www.tiktok.com/@{tiktok_username}")):
                    print("Gagal mencapai halaman profil setelah refresh kedua. Mungkin perlu login ulang. Mengakhiri tugas bot.")
                    return # Jika tidak di halaman profil, bot tidak bisa melanjutkan
        else:
            print("Tidak ada cookies untuk dimuat. Pastikan user sudah login via QR code sebelumnya di worker.")
            return
        print(f"Berhasil masuk ke halaman profil {tiktok_username}.")

        max_videos_to_process_per_run = 15 # Didefinisikan di sini

        # --- LANGKAH: GULIR HALAMAN PROFIL UNTUK MEMUAT SEMUA VIDEO ---
        print(f"Mulai menggulir halaman profil {tiktok_username} untuk memuat semua video...")
        # Elemen yang dapat digulir di halaman profil TikTok kemungkinan adalah body atau elemen konten utama
        profile_scrollable_element = driver.find_element(By.TAG_NAME, 'body') 
        last_profile_height = driver.execute_script("return arguments[0].scrollHeight", profile_scrollable_element)
        profile_scroll_attempts = 0
        max_profile_scroll_attempts = 5 # Batasi scroll untuk mencegah loop tak terbatas

        while profile_scroll_attempts < max_profile_scroll_attempts:
            driver.execute_script("arguments[0].scrollTo(0, arguments[0].scrollHeight);", profile_scrollable_element)
            time.sleep(3) # Beri waktu untuk memuat konten baru
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
            # Selector yang lebih spesifik dan teruji dari bot-sebelum-dipisahkan.py
            # PERBAIKAN: Tunggu hingga setidaknya satu item video muncul untuk memastikan rendering
            all_video_elements_after_scroll = WebDriverWait(driver, 20).until( # Tingkatkan timeout
                EC.presence_of_all_elements_located((By.XPATH, "//div[@data-e2e='user-post-item' and .//a[contains(@href, '/video/')]]"))
            )
            print(f"Ditemukan total {len(all_video_elements_after_scroll)} elemen video di DOM setelah scrolling.")
        except TimeoutException:
            print("Tidak ada elemen video yang valid dengan tautan video ditemukan dalam waktu yang ditentukan setelah scrolling. Mengakhiri proses.")
            # PERBAIKAN: Jangan update last_run_at jika tidak ada video yang ditemukan
            return # Keluar dari fungsi jika tidak ada video yang ditemukan
        except Exception as e: # Tangani error lain saat menemukan video
            print(f"ERROR: Terjadi kesalahan saat mengumpulkan elemen video: {e}. Mengakhiri proses.")
            return # Keluar dari fungsi

        recent_unpinned_video_urls = []
        seen_urls = set() # Digunakan untuk memastikan URL unik
        
        for video_item_element in all_video_elements_after_scroll:
            try:
                video_link_element = video_item_element.find_element(By.CSS_SELECTOR, 'a[href*="/video/"]')
                video_url = video_link_element.get_attribute('href')
                
                if not video_url or video_url in seen_urls:
                    continue

                is_pinned = False
                try:
                    # PERBAIKAN: Selector untuk pinned badge yang lebih robust dan presisi
                    # Jika teks 'Pinned' atau 'Disematkan' langsung ada di dalam div badge
                    pinned_badge_element = video_item_element.find_element(By.XPATH, ".//div[@data-e2e='video-card-badge' and (contains(text(), 'Pinned') or contains(text(), 'Disematkan'))]")
                    is_pinned = True
                    print(f"   -> Video disematkan/Pinned ditemukan, melewati (URL: {video_url}).") 
                except NoSuchElementException:
                    # Jika teks tidak langsung di div, coba cari di dalam child element (misal span di dalam div)
                    try:
                        pinned_badge_element = video_item_element.find_element(By.XPATH, ".//div[@data-e2e='video-card-badge']//*[contains(text(), 'Pinned') or contains(text(), 'Disematkan')]")
                        is_pinned = True
                        print(f"   -> Video disematkan/Pinned ditemukan (fallback selector), melewati (URL: {video_url}).")
                    except NoSuchElementException:
                        pass # Bukan video pinned

                if not is_pinned: # Hanya tambahkan jika BUKAN pinned
                    recent_unpinned_video_urls.append(video_url)
                    seen_urls.add(video_url) # Tambahkan ke set URL yang sudah dilihat
                    print(f"   -> Video non-disematkan ditambahkan ke antrean: {video_url}")

            except NoSuchElementException:
                print("   -> Peringatan: Tautan video tidak ditemukan dalam item video. Melewati.")
                continue
            except StaleElementReferenceException:
                print("   -> StaleElementReferenceException saat mencari tautan video di pengumpulan awal. Melewati.")
                continue

        videos_to_process_this_run = recent_unpinned_video_urls[:max_videos_to_process_per_run]

        if not videos_to_process_this_run:
            print("Tidak ada video terbaru (tidak disematkan/Pinned) yang ditemukan untuk diproses. Mengakhiri proses.")
            return # Tidak ada video untuk diproses, keluar
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
                        # PERUBAHAN KRUSIAL: Kembali ke halaman profil dan klik video
                        driver.get(target_url) 
                        print("Kembali ke halaman profil untuk re-fresh elemen dan klik video.")
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

                        # CEK VIDEO TIKTOK SHOP (dengan teks multi-bahasa)
                        tiktok_shop_toast_selector = (By.XPATH, "//div[contains(@class, 'TUXTopToast-content') and (contains(text(), 'View TikTok Shop videos') or contains(text(), 'Lihat video TikTok Shop'))]")
                        is_tiktok_shop_video = False
                        try:
                            print("   -> Mencoba mendeteksi toast 'Lihat video TikTok Shop'...")
                            WebDriverWait(driver, 5).until( 
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

                        # --- Dapatkan Transkrip Video (dengan user_id dan api_client) ---
                        print(f"Mencoba mendapatkan transkrip untuk video: {video_url_to_process}")
                        # PERBAIKAN: Gunakan user_id dan api_client
                        video_transcript = get_video_transcript(video_url_to_process, user_id, api_client) 
                        
                        if not video_transcript: 
                            print("   -> Transkrip video kosong atau gagal didapatkan. Melewatkan video ini.")
                            video_process_successful = True 
                            continue 
                        else:
                            print(f"Transkrip berhasil didapatkan (potongan): {video_transcript[:100]}...")

                        # --- PROSES KOMENTAR ---
                        print("Video terbuka. Menunggu komentar untuk dimuat dan memprosesnya...")
                        
                        # Selector jumlah komentar (mendukung multi-bahasa)
                        comment_count_element_selector = (By.XPATH, "//div[contains(@class, 'DivTabItem') and (starts-with(text(), 'Comments (') or starts-with(text(), 'Komentar ('))]")
                        num_comments = 0
                        try: 
                            comment_count_element = WebDriverWait(driver, 15).until(
                                EC.presence_of_element_located(comment_count_element_selector)
                            )
                            comment_count_text = comment_count_element.text
                            # Tangani format "Comments (1,234)" atau "Komentar (1.234)"
                            num_comments_str = comment_count_text.split('(')[1].split(')')[0].replace('.', '').replace(',', '')
                            num_comments = int(num_comments_str)
                            print(f"Total komentar terdeteksi: {num_comments}")

                            if num_comments == 0:
                                print("Tidak ada komentar pada video ini (jumlah = 0). Melewatkan balasan komentar.")
                                raise StopIteration # Keluar dari try ini untuk melewatkan video
                            else:
                                print("Komentar ditemukan, melanjutkan pemrosesan.")
                        except TimeoutException:
                            print("Tidak dapat menemukan elemen jumlah komentar dalam waktu yang ditentukan. Asumsi ada komentar dan melanjutkan.")
                        except ValueError:
                            print(f"Gagal mengurai jumlah komentar dari teks: '{comment_count_text}'. Melanjutkan tanpa jumlah pasti.")
                        except StopIteration: # Tangkap StopIteration untuk melewatkan pemrosesan komentar
                            video_process_successful = True
                            continue # Lanjutkan ke video berikutnya
                        except Exception as e:
                            print(f"Error tak terduga saat membaca jumlah komentar: {e}. Melanjutkan tanpa jumlah pasti.")

                        if num_comments > 0 or (num_comments == 0 and "Gagal mengurai" in locals().get('comment_count_text', '')): # Jika ada komentar atau gagal parse
                            try: 
                                WebDriverWait(driver, 10).until(
                                    EC.presence_of_element_located((By.CSS_SELECTOR, '[data-e2e="comment-level-1"]'))
                                )
                                print("Setidaknya satu komentar awal dimuat.")

                                # Selector untuk panel komentar yang bisa digulir
                                scrollable_comment_panel_selector = (By.CSS_SELECTOR, 'div[class*="DivCommentListContainer"]')
                                
                                try: 
                                    scrollable_element = WebDriverWait(driver, 10).until( # Tingkatkan timeout
                                        EC.presence_of_element_located(scrollable_comment_panel_selector)
                                    )
                                    print("Elemen scrollable komentar ditemukan (menggunakan class DivCommentListContainer).")
                                except TimeoutException: # Ganti except umum dengan TimeoutException
                                    print("Elemen scrollable komentar TIDAK ditemukan (menggunakan class DivCommentListContainer). Mencoba fallback ke body.")
                                    scrollable_element = driver.find_element(By.TAG_NAME, 'body') # Fallback terakhir ke body
                                last_height = driver.execute_script("return arguments[0].scrollHeight", scrollable_element)
                                scroll_attempts = 0
                                
                                initial_comments_on_load = 20 # Estimasi komentar yang dimuat saat awal
                                comments_per_scroll_load = 20 # Estimasi komentar yang dimuat per scroll

                                if num_comments > initial_comments_on_load:
                                    estimated_scrolls_needed = math.ceil((num_comments - initial_comments_on_load) / comments_per_scroll_load)
                                    max_scroll_attempts_comments = min(estimated_scrolls_needed, 50) # Batasi maksimal 50 scroll
                                else:
                                    max_scroll_attempts_comments = 0

                                scroll_pause_time = 2

                                print(f"Mulai menggulir komentar (diperkirakan {max_scroll_attempts_comments} upaya)...")
                                while scroll_attempts < max_scroll_attempts_comments:
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
                                
                                # Mengambil semua elemen komentar setelah scrolling
                                # Mencoba selector berdasarkan data-e2e atau struktur umum
                                all_comments_elements = driver.find_elements(By.XPATH, "//div[@data-e2e='comment-item-container' or contains(@class, 'DivCommentItemContainer')]")
                                print(f"Total {len(all_comments_elements)} komentar ditemukan untuk diproses setelah scrolling.")
                                
                                comment_replied_in_video = False
                                comments_processed_count_in_video = 0 
                                max_comments_to_process_per_video = 50 # Batasi komentar per video

                                for comment_element in all_comments_elements:
                                    if comments_processed_count_in_video >= max_comments_to_process_per_video:
                                        print(f"Batasan {max_comments_to_process_per_video} komentar tercapai. Berhenti memproses komentar di video ini.")
                                        break

                                    comment_text = ""
                                    try:
                                        # Selector teks komentar dari bot-sebelum-dipisahkan.py
                                        comment_text_element = comment_element.find_element(By.XPATH, ".//div[contains(@data-e2e, 'comment-content-') or contains(@class, 'DivCommentContent')]")
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
                                        comments_processed_count_in_video += 1
                                        continue

                                    # Filter 2: Cek apakah komentar berisi indikator foto/gambar (mendukung multi-bahasa)
                                    photo_indicators = ['[写真]', '[foto]', '[image]', '[photo]', '[gambar]'] 
                                    if any(indicator in comment_text.lower() for indicator in photo_indicators):
                                        print("   -> Komentar berisi indikator foto/gambar. Melewati.")
                                        comments_processed_count_in_video += 1
                                        continue

                                    # Filter 3: Cek apakah komentar dibuat oleh Creator
                                    is_creator_comment = False
                                    try:
                                        # Selector dari bot-sebelum-dipisahkan.py
                                        creator_badge = comment_element.find_element(By.XPATH, ".//span[contains(@data-e2e, 'comment-creator-') and (text()='Creator' or text()='Pembuat')]")
                                        is_creator_comment = True
                                    except NoSuchElementException:
                                        pass
                                    
                                    if is_creator_comment:
                                        print("   -> Ini adalah komentar dari Creator. Melewati.")
                                        comments_processed_count_in_video += 1
                                        continue

                                    # Filter 4: Cek apakah komentar sudah dibalas oleh Creator
                                    has_creator_replied = False
                                    try:
                                        # Selector dari bot-sebelum-dipisahkan.py
                                        reply_container = comment_element.find_element(By.CSS_SELECTOR, ".css-zn6r1p-DivReplyContainer") # Perbaiki class name
                                        creator_reply = reply_container.find_element(By.XPATH, ".//div[contains(@class, 'DivCommentContentContainer')]//span[contains(@data-e2e, 'comment-creator-') or text()='Anda']") # Tambahkan 'Anda'
                                        has_creator_replied = True
                                    except NoSuchElementException:
                                        pass

                                    if has_creator_replied:
                                        print("   -> Komentar ini sudah dibalas oleh Creator. Melewati.")
                                        comments_processed_count_in_video += 1
                                        continue
                                    
                                    print(f"   -> Lolos filter. Mencoba membalas komentar: '{comment_text}'")
                                    try: 
                                        # Pastikan tidak ada elemen pengganggu sebelum klik tombol reply
                                        try: 
                                            WebDriverWait(driver, 2).until(
                                                EC.invisibility_of_element_located((By.CSS_SELECTOR, '.css-3yeu18-DivTabMenuContainer.e1aa9wve0'))
                                            )
                                            print("   -> Elemen tab menu pengganggu tidak terlihat.")
                                        except TimeoutException:
                                            print("   -> Elemen tab menu pengganggu tidak menjadi tidak terlihat dalam waktu yang ditentukan, melanjutkan.")
                                        
                                        # Perbaiki selector tombol reply dari bot-sebelum-dipisahkan.py
                                        answer_comment_button = comment_element.find_element(By.CSS_SELECTOR, '[data-e2e^="comment-reply-"]')
                                        WebDriverWait(driver, 5).until(EC.element_to_be_clickable(answer_comment_button))
                                        answer_comment_button.click()
                                        print("   -> Tombol 'Jawab' berhasil diklik.")
                                        time.sleep(1)
                                        
                                        # Bersihkan komentar untuk AI
                                        cleaned_comment_for_reply = re.sub(r'[^\U00000000-\U0000FFFF]', '', comment_text)

                                        # Textbox balasan
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
                                                # Tutup balasan jika AI menginstruksikan tidak membalas
                                                try:
                                                    # Menggunakan selector baru berdasarkan inspect element
                                                    close_button_selector = (By.CSS_SELECTOR, 'div[class*="DivCloseBtn"]')
                                                    cancel_button = WebDriverWait(driver, 3).until( # Kurangi timeout
                                                        EC.element_to_be_clickable(close_button_selector) # Gunakan selector baru
                                                    )
                                                    cancel_button.click()
                                                    print("   -> Tombol 'Close' balasan diklik.")
                                                    WebDriverWait(driver, 5).until(EC.invisibility_of_element_located(text_box)) 
                                                    print("   -> balasan ditutup setelah klik 'Close'.")
                                                except TimeoutException:
                                                    print("   -> Peringatan: Tombol 'Close' tidak ditemukan atau tidak dapat diklik dalam waktu yang ditentukan.")
                                                except Exception as e_cancel:
                                                    print(f"   -> Peringatan: Error tak terduga saat mencoba menutup modal balasan: {e_cancel}")
                                                
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
                                        # Handle kemungkinan elemen pengganggu sebelum klik Post
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
                                        # Coba tutup modal jika timeout terjadi di tengah proses balasan
                                        try:
                                            # Menggunakan selector baru berdasarkan inspect element
                                            close_button_selector_timeout = (By.CSS_SELECTOR, 'div[class*="DivCloseBtn"]')
                                            cancel_button_in_modal = WebDriverWait(driver, 2).until(
                                                EC.element_to_be_clickable(close_button_selector_timeout)
                                            )
                                            cancel_button_in_modal.click()
                                            print("   -> Tombol 'Close' di modal balasan diklik setelah timeout.")
                                            WebDriverWait(driver, 5).until(EC.invisibility_of_element_located(text_box)) 
                                        except TimeoutException:
                                            print("   -> Peringatan: Tombol 'Close' atau modal balasan tidak dapat ditutup setelah timeout.")
                                        except Exception as e_cancel_timeout:
                                            print(f"   -> Peringatan: Error tak terduga saat mencoba menutup modal balasan setelah timeout: {e_cancel_timeout}")
                                    except ElementClickInterceptedException as e:
                                        print(f"   -> Tombol/text box terhalang: {e}. Melewati balasan ini.")
                                        try:
                                            # Menggunakan selector baru berdasarkan inspect element
                                            close_button_selector_intercepted = (By.CSS_SELECTOR, 'div[class*="DivCloseBtn"]')
                                            cancel_button_in_modal = WebDriverWait(driver, 2).until(
                                                EC.element_to_be_clickable(close_button_selector_intercepted)
                                            )
                                            cancel_button_in_modal.click()
                                            print("   -> Tombol 'Close' di modal balasan diklik setelah terhalang.")
                                            WebDriverWait(driver, 5).until(EC.invisibility_of_element_located(text_box)) 
                                        except TimeoutException:
                                            print("   -> Peringatan: Tombol 'Close' atau modal balasan tidak dapat ditutup setelah terhalang.")
                                        except Exception as e_cancel_intercepted:
                                            print(f"   -> Peringatan: Error tak terduga saat mencoba menutup modal balasan setelah terhalang: {e_cancel_intercepted}")
                                    
                                    except Exception as e:
                                        print(f"   -> Terjadi error tak terduga saat membalas komentar: {e}. Melewati balasan ini.")
                                        # PERBAIKAN: Lebih robust dalam menutup modal jika ada error tak terduga
                                        try:
                                            # Menggunakan selector baru berdasarkan inspect element
                                            close_button_selector_generic = (By.CSS_SELECTOR, 'div[class*="DivCloseBtn"]')
                                            cancel_button_in_modal = WebDriverWait(driver, 2).until(
                                                EC.element_to_be_clickable(close_button_selector_generic)
                                            )
                                            cancel_button_in_modal.click()
                                            print("   -> Tombol 'Close' di modal balasan diklik setelah error tak terduga.")
                                            WebDriverWait(driver, 5).until(EC.invisibility_of_element_located(text_box)) 
                                        except TimeoutException:
                                            print("   -> Peringatan: Tombol 'Close' atau modal balasan tidak dapat ditutup setelah error tak terduga.")
                                        except Exception as e_cancel_generic:
                                            print(f"   -> Peringatan: Error tak terduga saat mencoba menutup modal balasan setelah error generik: {e_cancel_generic}")
                                
                                reply_decision = generate_ai_reply(comment_text, creator_character_description)
                                final_reply = reply_decision.get('reply')
                                llm_raw_decision = reply_decision.get('raw_decision') # Simpan keputusan mentah LLM

                                if final_reply and final_reply != "[TIDAK_MEMBALAS]":
                                    try:
                                        # ... (kode yang sudah ada untuk mengetik dan memposting komentar) ...
                                        print(f"    -> AI membalas komentar '{comment_text[:50]}...' dengan: '{final_reply[:50]}...'")
                                        comment_replied_count += 1
                                        is_replied_status = True
                                        flash_message_category = 'success'
                                        flash_message_text = 'Komentar berhasil dibalas.'
                                    except Exception as e:
                                        print(f"    -> ERROR saat membalas komentar: {e}")
                                        is_replied_status = False
                                        flash_message_category = 'danger'
                                        flash_message_text = f'Gagal membalas komentar: {e}'
                                else:
                                    print(f"    -> AI memutuskan TIDAK MEMBALAS komentar: '{comment_text[:50]}...'")
                                    is_replied_status = False
                                    flash_message_category = 'info'
                                    flash_message_text = 'AI memutuskan untuk tidak membalas komentar.'
                                    try:
                                        # Coba menutup modal jika AI memutuskan tidak membalas
                                        close_button_selector = (By.CSS_SELECTOR, '.css-1k30cuv-5e6d46e3--DivCloseBtn') 
                                        close_button = WebDriverWait(driver, 3).until(EC.element_to_be_clickable(close_button_selector))
                                        driver.execute_script("arguments[0].click();", close_button)
                                        print("Modal balasan komentar ditutup setelah AI tidak membalas.")
                                    except TimeoutException:
                                        print("Peringatan: Tombol 'Cancel' atau modal balasan tidak dapat ditutup.")
                                    except Exception as close_ex:
                                        print(f"Peringatan: Error saat mencoba menutup modal balasan: {close_ex}")
   
                                try:
                                    api_client.save_processed_comment(
                                        processed_video_id=video_id,
                                        tiktok_comment_id=None, # Tidak menggunakan ID komentar dari TikTok
                                        comment_text=comment_text,
                                        reply_text=final_reply,
                                        is_replied=is_replied_status,
                                        llm_raw_decision=llm_raw_decision
                                    )
                                    print(f"    -> Detail komentar disimpan ke database.")
                                except Exception as e:
                                    print(f"    -> ERROR: Gagal menyimpan detail komentar ke database: {e}")

                                    
                                if not comment_replied_in_video:
                                    print("Tidak ada komentar yang memenuhi kriteria filter untuk dibalas di video ini.")

                            except TimeoutException:
                                print("Tidak ada komentar yang terlihat (initial load) pada video ini dalam waktu yang ditentukan. Melewatkan balasan komentar.")
                            except Exception as e:
                                print(f"Terjadi error tak terduga saat memproses komentar (di luar loop balasan): {e}. Melewatkan balasan komentar.")
                        print("Selesai memproses komentar di video ini. Mencoba menutup video untuk kembali ke profil.")
                        try: 
                            # Selector tombol close video (mendukung multi-bahasa)
                            close_button_selector = (By.XPATH, "//button[@role='button' and (@aria-label='Close' or @aria-label='Tutup')]")
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
                            driver.get(target_url) # Navigasi paksa ke profil
                            print("Melakukan navigasi paksa kembali ke halaman profil.")
                            time.sleep(5)
                        except Exception as e:
                            print(f"Terjadi error tak terduga saat menutup video: {e}.")
                        
                        video_process_successful = True # Setel ini menjadi True jika pemrosesan video berhasil
                    
                    except (WebDriverException, TimeoutException, ElementClickInterceptedException, StaleElementReferenceException) as e:
                        print(f"ERROR SAAT MEMPROSES VIDEO {video_url_to_process} (Upaya {video_retry_count}/{MAX_VIDEO_RETRIES}): {e}")
                        print("Mencoba me-refresh halaman profil dan menunggu sebelum mencoba lagi video yang sama...")
                        if driver:
                            try:
                                driver.get(target_url) # Refresh ke profil
                                time.sleep(5)
                            except WebDriverException as nav_e:
                                print(f"ERROR: Gagal menavigasi kembali ke profil setelah error: {nav_e}. Driver mungkin perlu diinisialisasi ulang.")
                                if driver: driver.quit()
                                driver = None # Set driver ke None untuk memicu inisialisasi ulang
                                time.sleep(5) 
                        else: 
                            print("Driver tidak aktif. Mencoba inisialisasi ulang.")
                            options = uc.ChromeOptions()
                            # options.add_argument('--headless=new') # DIKOMENTARI
                            # options.add_argument('--disable-gpu')
                            # options.add_argument('--no-sandbox')
                            # options.add_argument('--disable-dev-shm-usage')
                            # options.add_argument('--window-size=1280,800')
                            # options.add_argument('--disable-blink-features=AutomationControlled')
                            # options.add_argument(
                            #     '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                            #     'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
                            # )
                            # options.add_argument('--disable-setuid-sandbox')
                            # options.add_argument('--lang=en-US,en;q=0.9')

                            try:
                                driver = uc.Chrome(options=options)
                                # Sembunyikan navigator.webdriver = undefined (opsional, sudah dilakukan di inisialisasi utama)
                                # driver.execute_cdp_cmd(
                                #     "Page.addScriptToEvaluateOnNewDocument",
                                #     {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}
                                # )
                                # try:
                                #     driver.execute_cdp_cmd("Network.enable", {})
                                # except Exception:
                                #     pass
                                time.sleep(5)
                            except Exception as init_e:
                                print(f"ERROR: Gagal inisialisasi driver pada retry video: {init_e}. Mengakhiri retry untuk video ini.")
                                break # Keluar dari loop retry video
                        time.sleep(5) 
                    except Exception as e:
                        print(f"ERROR TAK TERDUGA SAAT MEMPROSES VIDEO {video_url_to_process} (Upaya {video_retry_count}/{MAX_VIDEO_RETRIES}): {e}")
                        break # Keluar dari loop retry video

                videos_processed_count += 1 

                if not video_process_successful: # Jika setelah semua retry gagal
                    print(f"Video {video_url_to_process} gagal diproses setelah {MAX_VIDEO_RETRIES} upaya. Melewatkan.")

        print(f"Selesai memproses {videos_processed_count} video untuk {tiktok_username}.") 

        # PERBAIKAN: Pindahkan pembaruan last_run_at ke sini
        # Hanya update jika setidaknya 1 video berhasil diproses atau jika proses mencapai titik ini tanpa error fatal.
        # Ini mencegah update jika gagal mengumpulkan daftar video di awal.
        if videos_processed_count > 0 or len(videos_to_process_this_run) > 0:
            api_client.update_user_last_run_api(user_id) 
            print(f"Waktu terakhir bot dijalankan untuk user ID: {user_id} diperbarui melalui API.") 
        else:
            print(f"Tidak ada video yang diproses untuk user ID: {user_id}. last_run_at TIDAK diperbarui.")

    except Exception as e: 
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERROR fatal saat menjalankan bot untuk user ID: {user_id}. Error: {e}") 
    finally: 
        if driver:
            driver.quit()
            print(f"Operasi selesai untuk user ID: {user_id}. Browser ditutup.") 
        else:
            print(f"Operasi selesai untuk user ID: {user_id}. Driver tidak diinisialisasi atau sudah ditutup.")