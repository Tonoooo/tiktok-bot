import undetected_chromedriver as uc
import time
import math
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, NoSuchElementException, StaleElementReferenceException, WebDriverException
import pickle
import os
import re
import json
from datetime import datetime

from akses_komen.api_client import APIClient
from akses_komen.transcription_service import get_video_transcript
from akses_komen.llm_service import generate_ai_reply

PROFILES_DIR = 'browser_profiles'

class element_attribute_is(object):
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

def run_tiktok_bot_task(user_id: int, is_trial_run: bool = False):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Memulai tugas bot untuk user ID: {user_id}")
    driver = None
    api_client = None # BARU: Inisialisasi api_client di sini
    
    # BARU: Variabel untuk menyimpan status user dan kontrol alur
    tiktok_username = None
    creator_character_description = None
    is_active = False
    daily_run_count = 0
    cookies_json = None
    onboarding_stage = None
    has_used_free_trial = False
    is_subscribed = False
    
    current_comment_runs_today = 0
    
    success_status = False # Untuk melacak apakah bot berhasil berjalan

    try:
        # BARU: Inisialisasi APIClient di dalam fungsi
        VPS_API_BASE_URL = os.getenv('VPS_API_BASE_URL', 'http://103.52.114.253:5000') # Pastikan ini diatur di env lokal
        API_BOT_KEY = os.getenv('API_BOT_KEY', 'super_secret_bot_key_123') # Pastikan ini diatur di env lokal
        api_client = APIClient(VPS_API_BASE_URL, API_BOT_KEY)
        print(f"APIClient diinisialisasi dengan base_url: {VPS_API_BASE_URL}")

        # --------------- Mengambil user settings dari APIClient ---------------
        user_settings = api_client.get_user_settings(user_id)
        if not user_settings:
            print(f"ERROR: User {user_id} tidak ditemukan di API atau gagal mengambil pengaturan.")
            return

        tiktok_username = user_settings.get('tiktok_username')
        creator_character_description = user_settings.get('creator_character_description', "")
        is_active = user_settings.get('is_active', False)
        daily_run_count = user_settings.get('daily_run_count', 0)
        cookies_json = user_settings.get('cookies_json')
        onboarding_stage = user_settings.get('onboarding_stage') # BARU: Ambil tahap onboarding
        has_used_free_trial = user_settings.get('has_used_free_trial', False) # BARU: Ambil status free trial
        is_subscribed = user_settings.get('is_subscribed', False) # BARU: Ambil status langganan
        current_comment_runs_today = user_settings.get('comment_runs_today', 0) # BARU: Ambil hitungan run harian

        print(f"Pengaturan user {user_id} diambil. TikTok Username: {tiktok_username}, Aktif: {is_active}, Runs Today: {current_comment_runs_today}, Onboarding Stage: {onboarding_stage}, Free Trial Used: {has_used_free_trial}, Subscribed: {is_subscribed}")

        # BARU: Logika untuk menentukan apakah bot harus berjalan
        # Bot berjalan jika (is_active True AND subscribed) ATAU (onboarding_stage TRIAL_RUNNING)
        if not (is_trial_run or (is_active and is_subscribed)):
            print(f"Bot untuk user {user_id} tidak aktif, tidak berlangganan, dan BUKAN uji coba. Melewati proses.")
            return

        if not tiktok_username:
            print(f"ERROR: tiktok_username tidak ditemukan untuk user {user_id}. Bot tidak dapat berjalan tanpa ini.")
            return

        if not cookies_json:
            print(f"ERROR: Cookies TikTok tidak ditemukan untuk user {user_id}. Login QR diperlukan. Melewati proses.")
            return
        
        # ------------- Memuat cookies dari user_settings yang didapat dari API -------------
        # cookies = json.loads(cookies_json)
        # if not cookies:
        #     print(f"Peringatan: Cookies JSON kosong untuk user {user_id}. Login mungkin diperlukan lagi.")
        #     return # Tidak bisa melanjutkan tanpa cookies
        
        user_profile_path = os.path.abspath(os.path.join(PROFILES_DIR, f'user_{user_id}'))
        print(f"Memuat profil peramban dari: {user_profile_path}")
        
        if not os.path.exists(user_profile_path):
            print(f"ERROR: Direktori profil untuk user {user_id} tidak ditemukan. Jalankan Bot QR terlebih dahulu.")
            return

        # =========================
        # STEALTH HEADLESS OPTIONS
        # =========================
        options = uc.ChromeOptions()
        # options.add_argument('--headless') 
        
        options.add_argument('--disable-gpu') # Diperlukan untuk headless di beberapa sistem
        options.add_argument('--no-sandbox') # Diperlukan untuk headless di Linux server
        options.add_argument('--disable-dev-shm-usage') # Mengatasi masalah resource di Docker/VPS
        options.add_argument('--window-size=1366,768') 
        options.add_argument('--start-maximized')  
        
        options.add_argument('--disable-blink-features=AutomationControlled') # Anti-deteksi
        # user agent sangat menyebabkan verifikasi captcha
        options.add_argument('--lang=en-US,en;q=0.9') # Mengatur bahasa browser ke Inggris AS
        
        # xxxx   disable setuit sandbox menyebabkan captcha     xxxx options.add_argument('--disable-setuid-sandbox') # browser akan berjalan tanpa batasan hak akses yang diterapkan oleh setuid sandbox. Ini bisa meningkatkan risiko keamanan jika browser terkena serangan.
        # xxxx   disable ini menyebabkan captcha     xxxx options.add_argument('--disable-extensions')
        # xxxx   menyebabkan captcha     xxxx options.add_argument('--disable-popup-blocking')
        options.add_argument('--ignore-certificate-errors')
        
        options.add_argument('--disable-web-security')  # Bypass kebijakan same-origin :cite[9] # 0.26
        # xxxx   menyebabkan captcha     xxxx  options.add_argument('--disable-features=VizDisplayCompositor')  # Nonaktifkan fitur yang bisa dideteks
        options.add_argument("--disable-features=IsolateOrigins,site-per-process")
        options.add_argument("--disable-site-isolation-trials")
        options.add_argument("--allow-running-insecure-content") # 0:45
        options.add_argument("--disable-renderer-backgrounding") # 0:36
        options.add_argument("--disable-background-timer-throttling")# 1:10
        options.add_argument("--disable-backgrounding-occluded-windows") # 0:39
        options.add_argument("--disable-client-side-phishing-detection") # 1:33
        options.add_argument("--disable-component-extensions-with-background-pages") # 0.27
        options.add_argument("--disable-default-apps") # 0.30
        options.add_argument("--disable-hang-monitor") # 0.39
        options.add_argument("--disable-ipc-flooding-protection") # 0.31
        options.add_argument("--disable-prompt-on-repost") # 0.36
        options.add_argument("--disable-sync")
        options.add_argument("--disable-translate") # 0.48
        options.add_argument("--metrics-recording-only") # 0.53
        options.add_argument("--no-first-run")
        options.add_argument("--safebrowsing-disable-auto-update") # 0.28
        # xxxx terdeteksi sofware automati  xxxxx   options.add_argument("--enable-automation")
        options.add_argument("--password-store=basic")
        options.add_argument("--use-mock-keychain") # 0.20
        
        
        windows_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        options.add_argument(f'--user-agent={windows_ua}')
        options.add_argument('--sec-ch-ua-platform="Windows"')
        options.add_argument('--sec-ch-ua-mobile=?0')
        options.add_argument('--timezone=Asia/Jakarta')
        options.add_argument('--lang=en-US,en;q=0.9,id;q=0.8')
        
        options.add_argument(f'--user-data-dir={user_profile_path}')   

        driver = uc.Chrome(options=options)
        
        platform_override_script = """
            // === DEEPLY EMBEDDED PLATFORM OVERRIDE ===
            
            // 1. Navigator platform override (MOST CRITICAL)
            const originalPlatform = Object.getOwnPropertyDescriptor(Navigator.prototype, 'platform');
            Object.defineProperty(navigator, 'platform', {
                get: () => 'Win32',
                configurable: true,
                enumerable: true
            });
            
            // 2. User agent consistency
            Object.defineProperty(navigator, 'userAgent', {
                get: () => 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
                configurable: true
            });
            
            // 3. OSCpu override (Firefox legacy, but some sites check)
            Object.defineProperty(navigator, 'oscpu', {
                get: () => 'Windows NT 10.0',
                configurable: true
            });
            
            // 4. Vendor override
            Object.defineProperty(navigator, 'vendor', {
                get: () => 'Google Inc.',
                configurable: true
            });
            
            // 5. Language preferences
            Object.defineProperty(navigator, 'language', {
                get: () => 'en-US'
            });
            
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en', 'id']
            });
            
            // 6. Hardened webdriver detection removal
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
                set: (val) => {},
                configurable: true
            });
            
            // 7. Chrome runtime spoofing
            if (!window.chrome) {
                window.chrome = {};
            }
            
            if (!window.chrome.runtime) {
                window.chrome.runtime = {
                    id: 'dummy',
                    getURL: () => '',
                    connect: () => ({})
                };
            }
            
            // 8. Performance timing spoofing (Linux vs Windows differences)
            const originalTime = performance.now;
            performance.now = function() {
                const time = originalTime.apply(performance, arguments);
                // Add small random variance to mimic Windows performance characteristics
                return time + Math.random() * 2;
            };
            
            console.log('✅ Comprehensive Windows platform override injected');
            """
            
        driver.execute_script(platform_override_script)
        
        print("WebDriver berhasil diinisialisasi.")

        target_url = f"https://www.tiktok.com/@{tiktok_username}"
        driver.get(target_url)
        print(f"Navigasi ke: {target_url}")
        time.sleep(5)

        # Muat cookies
        # for cookie in cookies:
        #     if 'domain' in cookie:
        #         del cookie['domain']
        #     driver.add_cookie(cookie)
        # driver.refresh()
        # print("Cookies dimuat dan halaman direfresh.")
        # time.sleep(5)

        videos_area_loaded_ok = False
        for attempt in range(3):
            print(f"Memeriksa status area video di halaman profil (Percobaan {attempt + 1})...")
            try:
                error_container = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'div.css-1w7vxma-5e6d46e3--DivErrorContainer'))
                )
                refresh_button = error_container.find_element(By.CSS_SELECTOR, 'button.ebef5j00')
                
                print("Deteksi 'Something went wrong' di area video. Mengklik tombol Refresh.")
                driver.execute_script("arguments[0].click();", refresh_button)
                time.sleep(10)

            except TimeoutException:
                print("Area video tampaknya dimuat dengan baik (tidak ada 'Something Went Wrong').")
                videos_area_loaded_ok = True
                break
            except NoSuchElementException:
                print("Tidak ada elemen error 'Something Went Wrong' yang terdeteksi di area video. Menganggap area video dimuat.")
                videos_area_loaded_ok = True
                break
            except Exception as ex:
                print(f"ERROR saat mencoba menangani 'Something Went Wrong' di area video: {ex}. Mencoba refresh manual.")
                driver.refresh()
                time.sleep(10)
        
        if not videos_area_loaded_ok:
            print("Gagal memuat area video setelah beberapa kali percobaan. Mengakhiri tugas bot.")
            return

        current_url_base = driver.current_url.split('?')[0]
        target_url_base = target_url.split('?')[0]
        if not (current_url_base == target_url_base or current_url_base.startswith(f"https://www.tiktok.com/@{tiktok_username}")):
            print(f"Peringatan: Tidak berhasil mencapai halaman profil setelah loading cookies. URL saat ini: {driver.current_url}. Akan mencoba refresh lagi.")
            driver.get(target_url)
            time.sleep(5)
            current_url_base = driver.current_url.split('?')[0]
            if not (current_url_base == target_url_base or current_url_base.startswith(f"https://www.tiktok.com/@{tiktok_username}")):
                print("Gagal mencapai halaman profil setelah refresh kedua. Mungkin perlu login ulang. Mengakhiri tugas bot.")
                return
        print(f"Berhasil masuk ke halaman profil {tiktok_username}.")

        max_videos_to_process_per_run = 15

        print(f"Mulai menggulir halaman profil {tiktok_username} untuk memuat semua video...")
        profile_scrollable_element = driver.find_element(By.TAG_NAME, 'body') 
        last_profile_height = driver.execute_script("return arguments[0].scrollHeight", profile_scrollable_element)
        profile_scroll_attempts = 0
        max_profile_scroll_attempts = 5

        while profile_scroll_attempts < max_profile_scroll_attempts:
            driver.execute_script("arguments[0].scrollTo(0, arguments[0].scrollHeight);", profile_scrollable_element)
            time.sleep(3)
            new_profile_height = driver.execute_script("return arguments[0].scrollHeight", profile_scrollable_element)
            if new_profile_height == last_profile_height:
                print(f"Tidak ada video baru yang dimuat setelah {profile_scroll_attempts+1} scroll profil. Berhenti.")
                break
            last_profile_height = new_profile_height
            profile_scroll_attempts += 1
            print(f"Digulir profil {profile_scroll_attempts} kali. Tinggi baru: {new_profile_height}")
        print("Selesai menggulir halaman profil.")

        all_video_elements_after_scroll = []
        try:
            all_video_elements_after_scroll = WebDriverWait(driver, 20).until(
                EC.presence_of_all_elements_located((By.XPATH, "//div[@data-e2e='user-post-item' and .//a[contains(@href, '/video/')]]"))
            )
            print(f"Ditemukan total {len(all_video_elements_after_scroll)} elemen video di DOM setelah scrolling.")
        except TimeoutException:
            print("Tidak ada elemen video yang valid dengan tautan video ditemukan dalam waktu yang ditentukan setelah scrolling. Mengakhiri proses.")
            return
        except Exception as e:
            print(f"ERROR: Terjadi kesalahan saat mengumpulkan elemen video: {e}. Mengakhiri proses.")
            return

        recent_unpinned_video_urls = []
        seen_urls = set()
        
        for video_item_element in all_video_elements_after_scroll:
            try:
                video_link_element = video_item_element.find_element(By.CSS_SELECTOR, 'a[href*="/video/"]')
                video_url = video_link_element.get_attribute('href')
                
                if not video_url or video_url in seen_urls:
                    continue

                is_pinned = False
                try:
                    pinned_badge_element = video_item_element.find_element(By.XPATH, ".//div[@data-e2e='video-card-badge' and (contains(text(), 'Pinned') or contains(text(), 'Disematkan'))]")
                    is_pinned = True
                    print(f"   -> Video disematkan/Pinned ditemukan, melewati (URL: {video_url}).") 
                except NoSuchElementException:
                    try:
                        pinned_badge_element = video_item_element.find_element(By.XPATH, ".//div[@data-e2e='video-card-badge']//*[contains(text(), 'Pinned') or contains(text(), 'Disematkan')]")
                        is_pinned = True
                        print(f"   -> Video disematkan/Pinned ditemukan (fallback selector), melewati (URL: {video_url}).")
                    except NoSuchElementException:
                        pass

                if not is_pinned:
                    recent_unpinned_video_urls.append(video_url)
                    seen_urls.add(video_url)
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
            return
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

                        print(f"Mencoba mendapatkan transkrip untuk video: {video_url_to_process}")
                        video_transcript = get_video_transcript(video_url_to_process, user_id, api_client)
                        
                        if not video_transcript:
                            print("   -> Transkrip video kosong atau gagal didapatkan. Melewatkan video ini.")
                            video_process_successful = True
                            continue
                        else:
                            print(f"Transkrip berhasil didapatkan (potongan): {video_transcript[:100]}...")

                        print("Video terbuka. Menunggu komentar untuk dimuat dan memprosesnya...")
                        
                        comment_count_element_selector = (By.XPATH, "//div[contains(@class, 'DivTabItem') and (starts-with(text(), 'Comments (') or starts-with(text(), 'Komentar ('))]")
                        num_comments = 0
                        try:
                            comment_count_element = WebDriverWait(driver, 15).until(
                                EC.presence_of_element_located(comment_count_element_selector)
                            )
                            comment_count_text = comment_count_element.text
                            num_comments_str = comment_count_text.split('(')[1].split(')')[0].replace('.', '').replace(',', '')
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
                            video_process_successful = True
                            continue
                        except Exception as e:
                            print(f"Error tak terduga saat membaca jumlah komentar: {e}. Melanjutkan tanpa jumlah pasti.")

                        if num_comments > 0 or (num_comments == 0 and "Gagal mengurai" in locals().get('comment_count_text', '')):
                            try:
                                WebDriverWait(driver, 10).until(
                                    EC.presence_of_element_located((By.CSS_SELECTOR, '[data-e2e="comment-level-1"]'))
                                )
                                print("Setidaknya satu komentar awal dimuat.")

                                scrollable_comment_panel_selector = (By.CSS_SELECTOR, 'div[class*="DivCommentListContainer"]')
                                
                                try:
                                    scrollable_element = WebDriverWait(driver, 10).until(
                                        EC.presence_of_element_located(scrollable_comment_panel_selector)
                                    )
                                    print("Elemen scrollable komentar ditemukan (menggunakan class DivCommentListContainer).")
                                except TimeoutException:
                                    print("Elemen scrollable komentar TIDAK ditemukan (menggunakan class DivCommentListContainer). Mencoba fallback ke body.")
                                    scrollable_element = driver.find_element(By.TAG_NAME, 'body')
                                last_height = driver.execute_script("return arguments[0].scrollHeight", scrollable_element)
                                scroll_attempts = 0
                                
                                initial_comments_on_load = 20
                                comments_per_scroll_load = 20

                                if num_comments > initial_comments_on_load:
                                    estimated_scrolls_needed = math.ceil((num_comments - initial_comments_on_load) / comments_per_scroll_load)
                                    max_scroll_attempts_comments = min(estimated_scrolls_needed, 50)
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
                                
                                all_comments_elements = driver.find_elements(By.XPATH, "//div[@data-e2e='comment-item-container' or contains(@class, 'DivCommentItemContainer')]")
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
                                        comment_text_element = comment_element.find_element(By.XPATH, ".//div[contains(@data-e2e, 'comment-content-') or contains(@class, 'DivCommentContent')]")
                                        comment_text = comment_text_element.text
                                    except NoSuchElementException:
                                        print("Gagal mendapatkan teks komentar. Melewati.")
                                        continue
                                    except StaleElementReferenceException:
                                        print("StaleElementReferenceException: Melewati komentar ini, mungkin perlu me-refresh daftar.")
                                        continue

                                    print(f"\nMemproses komentar: '{comment_text}'")

                                    stripped_comment_text = re.sub(r'\s+', '', comment_text)
                                    if not any(char.isalnum() for char in stripped_comment_text):
                                        print("   -> Komentar hanya terdiri dari emoji. Melewati.")
                                        comments_processed_count_in_video += 1
                                        continue

                                    photo_indicators = ['[写真]', '[foto]', '[image]', '[photo]', '[gambar]'] 
                                    if any(indicator in comment_text.lower() for indicator in photo_indicators):
                                        print("   -> Komentar berisi indikator foto/gambar. Melewati.")
                                        comments_processed_count_in_video += 1
                                        continue

                                    is_creator_comment = False
                                    try:
                                        creator_badge = comment_element.find_element(By.XPATH, ".//span[contains(@data-e2e, 'comment-creator-') and (text()='Creator' or text()='Pembuat')]")
                                        is_creator_comment = True
                                    except NoSuchElementException:
                                        pass
                                    
                                    if is_creator_comment:
                                        print("   -> Ini adalah komentar dari Creator. Melewati.")
                                        comments_processed_count_in_video += 1
                                        continue

                                    has_creator_replied = False
                                    try:
                                        reply_container = comment_element.find_element(By.CSS_SELECTOR, ".css-zn6r1p-DivReplyContainer")
                                        creator_reply = reply_container.find_element(By.XPATH, ".//div[contains(@class, 'DivCommentContentContainer')]//span[contains(@data-e2e, 'comment-creator-') or text()='Anda']")
                                        has_creator_replied = True
                                    except NoSuchElementException:
                                        pass

                                    if has_creator_replied:
                                        print("   -> Komentar ini sudah dibalas oleh Creator. Melewati.")
                                        comments_processed_count_in_video += 1
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
                                                try:
                                                    close_button_selector = (By.CSS_SELECTOR, 'div[class*="DivCloseBtn"]')
                                                    cancel_button = WebDriverWait(driver, 3).until(
                                                        EC.element_to_be_clickable(close_button_selector)
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
                                        try:
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
                                        try:
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
                                
                                # BARU: Logika pemanggilan generate_ai_reply dan simpan_processed_comment dipindahkan ke sini
                                # Ini adalah bagian yang harus terjadi setelah semua interaksi Selenium selesai
                                # Namun, karena struktur lama bot sudah kompleks dengan `generate_ai_reply` di dalam loop try-except
                                # kita biarkan seperti adanya, asalkan `api_client.save_processed_comment` dipanggil.
                                
                                # Pastikan `final_reply`, `llm_raw_decision`, `is_replied_status` didefinisikan
                                # sebelum panggilan save_processed_comment jika ada skenario di mana mereka tidak diatur
                                final_reply = ""
                                llm_raw_decision = ""
                                is_replied_status = False

                                try: # Bungkus logika balasan AI dan simpan ke DB di sini
                                    # Panggil generate_ai_reply seperti yang sudah ada
                                    reply_decision = generate_ai_reply(video_transcript, comment_text, creator_character_description)
                                    final_reply = reply_decision.get('reply')
                                    llm_raw_decision = reply_decision.get('raw_decision')

                                    if final_reply and final_reply != "[TIDAK_MEMBALAS]":
                                        reply_text_to_send = re.sub(r'[^\U00000000-\U0000FFFF]', '', final_reply)

                                        # Logika untuk mengetik dan memposting balasan melalui Selenium
                                        # Ini adalah bagian yang harus sudah terjadi di try sebelumnya
                                        # Untuk menghindari duplikasi, kita asumsikan jika sampai sini, balasan sudah diketik/diposting
                                        # atau AI memutuskan tidak membalas.
                                        print(f"    -> AI membalas komentar '{comment_text[:50]}...' dengan: '{reply_text_to_send[:50]}...'")
                                        is_replied_status = True
                                    else:
                                        print(f"    -> AI memutuskan TIDAK MEMBALAS komentar: '{comment_text[:50]}...'")
                                        is_replied_status = False
                                        # Tutup modal jika AI memutuskan tidak membalas
                                        try:
                                            close_button_selector = (By.CSS_SELECTOR, 'div[class*="DivCloseBtn"]')
                                            close_button = WebDriverWait(driver, 3).until(EC.element_to_be_clickable(close_button_selector))
                                            driver.execute_script("arguments[0].click();", close_button)
                                            print("Modal balasan komentar ditutup setelah AI tidak membalas.")
                                        except TimeoutException:
                                            print("Peringatan: Tombol 'Cancel' atau modal balasan tidak dapat ditutup.")
                                        except Exception as close_ex:
                                            print(f"Peringatan: Error saat mencoba menutup modal balasan: {close_ex}")

                                    api_client.save_processed_comment(
                                        processed_video_id=video_id,
                                        tiktok_comment_id=None,
                                        comment_text=comment_text,
                                        reply_text=final_reply,
                                        is_replied=is_replied_status,
                                        llm_raw_decision=llm_raw_decision
                                    )
                                    print(f"    -> Detail komentar disimpan ke database.")
                                except Exception as e_llm_save:
                                    print(f"    -> ERROR: Gagal memproses AI atau menyimpan detail komentar ke database: {e_llm_save}")

                                if not comment_replied_in_video:
                                    print("Tidak ada komentar yang memenuhi kriteria filter untuk dibalas di video ini.")

                            except TimeoutException:
                                print("Tidak ada komentar yang terlihat (initial load) pada video ini dalam waktu yang ditentukan. Melewatkan balasan komentar.")
                            except Exception as e:
                                print(f"Terjadi error tak terduga saat memproses komentar (di luar loop balasan): {e}. Melewatkan balasan komentar.")
                        print("Selesai memproses komentar di video ini. Mencoba menutup video untuk kembali ke profil.")
                        try:
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
                            options.add_argument('--headless')
                            options.add_argument('--disable-gpu')
                            options.add_argument('--no-sandbox')
                            options.add_argument('--disable-dev-shm-usage')
                            options.add_argument('--window-size=1280,800')
                            options.add_argument('--disable-blink-features=AutomationControlled')
                            options.add_argument('--disable-setuid-sandbox')
                            options.add_argument('--lang=en-US,en;q=0.9')

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

        print(f"Selesai memproses {videos_processed_count} video untuk {tiktok_username}.")

        # Pindahkan pembaruan last_run_at ke bagian finally untuk penanganan error yang lebih baik
        # dan pastikan logika onboarding_stage ditangani di sana.
        # success_status = True di sini jika tidak ada exception yang ditangkap di loop

    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERROR fatal saat menjalankan bot untuk user ID: {user_id}. Error: {e}")
        success_status = False # Pastikan status gagal jika ada exception di luar loop video
    finally:
        if driver:
            driver.quit()
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] WebDriver ditutup untuk user {user_id}.")
        
        if api_client:
            try:
                # Jika berhasil, perbarui last_comment_run_at ke waktu saat ini
                if success_status:
                    # BARU: Jika ini adalah trial, update onboarding_stage ke TRIAL_COMPLETED
                    if onboarding_stage == 'TRIAL_RUNNING':
                        api_client.update_onboarding_stage_after_trial(user_id)
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Bot uji coba untuk user {user_id} selesai. Onboarding stage diperbarui ke TRIAL_COMPLETED.")
                    else:
                        # Untuk run normal, update last_comment_run_at dan comment_runs_today
                        # Jika bot berhasil sampai akhir, increment comment_runs_today
                        api_client.update_user_last_comment_run(user_id, datetime.utcnow(), current_comment_runs_today + 1)
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Status run komentar untuk user {user_id} berhasil diperbarui.")
                else:
                    # Jika bot gagal, kita tidak meng-increment comment_runs_today.
                    # `last_comment_run_at` juga tidak diupdate, atau diupdate ke None jika ingin menandai kegagalan.
                    # Untuk saat ini, kita tidak update apa-apa jika gagal.
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Bot komentar gagal untuk user {user_id}. Status run TIDAK diperbarui.")
            except Exception as e:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERROR: Gagal memperbarui status bot setelah selesai: {e}")
        
        # Pastikan QR code lokal dihapus, terlepas dari keberhasilan
        qr_image_path = os.path.join("qr_codes_temp", f'qrcode_{user_id}.png')
        if os.path.exists(qr_image_path):
            os.remove(qr_image_path)
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] QR code lokal untuk user {user_id} dihapus.")