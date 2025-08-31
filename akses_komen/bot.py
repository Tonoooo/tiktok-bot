import undetected_chromedriver as uc
import time
import pickle
import os
import re
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, NoSuchElementException, StaleElementReferenceException
from datetime import datetime

# PERUBAHAN: Import APIClient dan get_video_transcript, generate_ai_reply
from akses_komen.api_client import APIClient
from akses_komen.transcription_service import get_video_transcript
from akses_komen.llm_service import generate_ai_reply

# Custom Expected Condition untuk memeriksa atribut 'aria-disabled'
class element_attribute_is(object):
    def __init__(self, locator, attribute, value):
        self.locator = locator
        self.attribute = attribute
        self.value = value

    def __call__(self, driver):
        try:
            element = driver.find_element(*self.locator)
            return element.get_attribute(self.attribute) == self.value
        except StaleElementReferenceException:
            return False

# PERUBAHAN: Fungsi utama bot sekarang menerima user_id dan api_client
def run_tiktok_bot_task(user_id: int, api_client: APIClient):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Memulai tugas bot untuk user ID: {user_id}")
    driver = None
    
    try:
        # PERUBAHAN: Mengambil user settings dari APIClient
        user_settings = api_client.get_user_settings(user_id)
        if not user_settings:
            print(f"ERROR: User {user_id} tidak ditemukan di API atau gagal mengambil pengaturan.")
            return

        tiktok_username = user_settings.get('tiktok_username')
        creator_character_description = user_settings.get('creator_character_description', "")
        
        # PERUBAHAN: Memuat cookies dari user_settings yang didapat dari API
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
        options.add_argument('--headless=new')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--window-size=1280,800')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument(
            '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
        )
        options.add_argument('--disable-setuid-sandbox')
        options.add_argument('--lang=en-US,en;q=0.9')

        driver = uc.Chrome(options=options)
        print("WebDriver berhasil diinisialisasi.")

        # Sembunyikan navigator.webdriver = undefined
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}
        )
        try:
            driver.execute_cdp_cmd("Network.enable", {})
        except Exception:
            pass

        target_url = f"https://www.tiktok.com/@{tiktok_username}"
        driver.get(target_url)
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
        else:
            print("Tidak ada cookies untuk dimuat. Pastikan user sudah login via QR code sebelumnya.")
            # return # Jika tidak ada cookies, bot tidak bisa lanjut. Logika ini akan ditangani di Worker.

        # Memastikan berada di halaman profil
        current_url_base = driver.current_url.split('?')[0]
        target_url_base = target_url.split('?')[0]

        if not (current_url_base == target_url_base or current_url_base.startswith(f"https://www.tiktok.com/@{tiktok_username}")):
            print(f"Peringatan: Tidak berhasil mencapai halaman profil setelah loading cookies. URL saat ini: {driver.current_url}")
            # return # Jika tidak di halaman profil, bot tidak bisa melanjutkan

        print(f"Berhasil masuk ke halaman profil {tiktok_username}.")

        # Scroll ke bawah untuk memuat semua video (hingga batas tertentu)
        print("Mulai scroll profil untuk memuat video...")
        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_attempts = 0
        max_scroll_attempts = 5 # Batasi scroll untuk mencegah loop tak terbatas
        
        while scroll_attempts < max_scroll_attempts:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3) # Tunggu halaman memuat konten baru
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                print("Tidak ada konten baru yang dimuat setelah scroll.")
                break
            last_height = new_height
            scroll_attempts += 1
            print(f"Profil discroll {scroll_attempts} kali.")
        print("Selesai scroll profil.")

        # Ambil daftar semua video (non-pinned)
        # Mencari video items, mengabaikan yang memiliki atribut data-e2e="video-card-pinned"
        video_items = driver.find_elements(By.CSS_SELECTOR, 'div[data-e2e="user-post-item"]:not([data-e2e="video-card-pinned"])')
        
        if not video_items:
            print(f"Tidak ada video non-pinned yang ditemukan di profil {tiktok_username}.")
            return

        print(f"Ditemukan {len(video_items)} video non-pinned.")
        
        processed_video_urls_in_this_run = []
        
        for index, video_item in enumerate(video_items[:15]): # Hanya proses hingga 15 video terbaru
            if index >= 15:
                print("Mencapai batas 15 video yang diproses per sesi.")
                break

            video_url = None
            try:
                video_link = video_item.find_element(By.TAG_NAME, 'a')
                video_url = video_link.get_attribute('href')
                print(f"\nMemproses video {index + 1}: {video_url}")
            except NoSuchElementException:
                print(f"Peringatan: Tidak dapat menemukan link video untuk item {index + 1}. Melewati.")
                continue

            if not video_url:
                print(f"Peringatan: URL video kosong untuk item {index + 1}. Melewati.")
                continue

            # PERUBAHAN: Cek apakah video sudah diproses sebelumnya dan ada transkripnya di API
            # Jika ada dan transkripnya tidak kosong, kita bisa melewatkan transkripsi lagi.
            # Tapi tetap masuk ke video untuk cek komentar baru.
            processed_video_data = api_client.get_processed_video(user_id, video_url)
            video_transcript_from_db = ""
            if processed_video_data and processed_video_data.get('transcript'):
                video_transcript_from_db = processed_video_data['transcript']
                print(f"   -> Transkrip video dimuat dari database untuk {video_url}.")
            else:
                print(f"   -> Transkrip video belum ada di database untuk {video_url} atau kosong.")

            # Simpan URL video yang saat ini diproses
            current_video_url = driver.current_url # Simpan URL profil
            driver.get(video_url)
            time.sleep(5)

            # Cek apakah ini video TikTok Shop (dengan 'View TikTok Shop videos' toast)
            try:
                shop_toast_message = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, "//div[contains(text(), 'View TikTok Shop videos in the TikTok app')]"))
                )
                if shop_toast_message.is_displayed():
                    print("   -> Video ini adalah video TikTok Shop. Melanjutkan proses komentar.")
                    is_tiktok_shop_video = True
            except TimeoutException:
                print("   -> Video ini bukan video TikTok Shop. Melewati video ini.")
                is_tiktok_shop_video = False
                driver.get(current_video_url) # Kembali ke profil
                time.sleep(3)
                continue # Lanjutkan ke video berikutnya jika bukan TikTok Shop

            # Jika ini video TikTok Shop, dapatkan transkrip
            video_transcript = ""
            if video_transcript_from_db:
                video_transcript = video_transcript_from_db
            else:
                # PERUBAHAN: Panggil get_video_transcript dengan api_client
                video_transcript = get_video_transcript(video_url, user_id, api_client)
                if not video_transcript:
                    print("   -> Peringatan: Transkrip video kosong atau tidak dapat diperoleh. Melewati komentar untuk video ini.")
                    driver.get(current_video_url) # Kembali ke profil
                    time.sleep(3)
                    continue # Lanjutkan ke video berikutnya

            # Simpan transkrip ke database jika belum ada atau kosong (api_client akan handle upsert)
            if not video_transcript_from_db and video_transcript:
                try:
                    api_client.save_processed_video(user_id, video_url, video_transcript)
                    print(f"   -> Transkrip video baru disimpan ke database untuk {video_url}.")
                except Exception as e:
                    print(f"   -> ERROR: Gagal menyimpan transkrip ke API untuk {video_url}: {e}")

            # Deteksi jumlah komentar
            comments_count_element_locator = (By.CSS_SELECTOR, 'strong[data-e2e="comment-count"]')
            try:
                comments_count_element = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(comments_count_element_locator)
                )
                comments_text = comments_count_element.text
                print(f"   -> Teks jumlah komentar: {comments_text}")
                
                # Ekstrak angka dari teks seperti "123.4K Comments" atau "10 Comments"
                match = re.search(r'([\d.]+)([KM]?) Comments', comments_text)
                total_comments = 0
                if match:
                    num_str = match.group(1)
                    if 'K' in match.group(2):
                        total_comments = int(float(num_str) * 1000)
                    elif 'M' in match.group(2):
                        total_comments = int(float(num_str) * 1000000)
                    else:
                        total_comments = int(num_str)
                else:
                    # Fallback jika format tidak standar, coba parse langsung
                    try:
                        total_comments = int(re.search(r'(\d+)\s+Comments', comments_text).group(1))
                    except AttributeError:
                        print("Peringatan: Gagal mengekstrak jumlah komentar secara akurat.")

                print(f"   -> Total komentar yang terdeteksi: {total_comments}")

                if total_comments == 0:
                    print("   -> Tidak ada komentar untuk video ini. Melewati.")
                    driver.get(current_video_url)
                    time.sleep(3)
                    continue
            except TimeoutException:
                print("   -> Tidak dapat menemukan elemen jumlah komentar atau tidak ada komentar.")
                driver.get(current_video_url)
                time.sleep(3)
                continue
            except Exception as e:
                print(f"   -> ERROR saat mencoba mendapatkan jumlah komentar: {e}. Melewati video.")
                driver.get(current_video_url)
                time.sleep(3)
                continue

            # Scroll komentar jika jumlahnya banyak
            comments_list_container_locator = (By.CSS_SELECTOR, '.css-1qp5gj2-DivCommentListContainer.ekjxngi3')
            comments_loaded = 0
            # Kita tidak tahu persis berapa yang dimuat per scroll, jadi scroll beberapa kali
            max_comment_scrolls = (total_comments // 20) + 1 # Estimasi 20 komentar per scroll
            if max_comment_scrolls > 100: # Batasi agar tidak terlalu banyak scroll
                max_comment_scrolls = 100
            
            print(f"   -> Akan mencoba scroll komentar maksimal {max_comment_scrolls} kali.")

            for _ in range(max_comment_scrolls):
                try:
                    comments_container = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located(comments_list_container_locator)
                    )
                    driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", comments_container)
                    time.sleep(2) # Tunggu komentar baru dimuat
                    print(f"   -> Komentar discroll. Total komentar di DOM saat ini: {len(driver.find_elements(By.CSS_SELECTOR, '.css-1i7ohvi-DivCommentItemContainer.eo72wou0'))}")
                except TimeoutException:
                    print("   -> Peringatan: Kontainer komentar tidak ditemukan atau tidak dapat discroll.")
                    break
                except Exception as e:
                    print(f"   -> ERROR saat scrolling komentar: {e}")
                    break

            # Proses komentar
            print("   -> Memulai proses filter dan balasan komentar...")
            all_comments = driver.find_elements(By.CSS_SELECTOR, '.css-1i7ohvi-DivCommentItemContainer.eo72wou0')
            print(f"   -> Total komentar yang ditemukan di DOM: {len(all_comments)}")

            comments_processed_count_in_video = 0
            comment_replied_in_video = False

            for comment_element in all_comments:
                if comments_processed_count_in_video >= 20: # Batasi hingga 20 komentar per video untuk efisiensi
                    print("   -> Batas 20 komentar per video tercapai. Melanjutkan ke video berikutnya.")
                    break
                
                try:
                    comment_text_element = comment_element.find_element(By.CSS_SELECTOR, '.css-h225x3-DivCommentContent.e1g2mq2g2')
                    original_comment = comment_text_element.text.strip()
                    
                    # Filter 1: Jangan balas komentar dari creator (ada data-e2e="comment-creator-badge")
                    try:
                        comment_element.find_element(By.CSS_SELECTOR, '[data-e2e="comment-creator-badge"]')
                        print(f"   -> Komentar oleh creator: \"{original_comment}\". Melewati.")
                        comments_processed_count_in_video += 1
                        time.sleep(1)
                        continue
                    except NoSuchElementException:
                        pass # Bukan komentar creator, lanjutkan

                    # Filter 2: Jangan balas komentar yang sudah dibalas oleh creator
                    try:
                        comment_element.find_element(By.XPATH, ".//div[@data-e2e='comment-item-container']//a[contains(@href, '/@')]/div[text()='Anda']")
                        print(f"   -> Komentar sudah dibalas oleh Anda (creator): \"{original_comment}\". Melewati.")
                        comments_processed_count_in_video += 1
                        time.sleep(1)
                        continue
                    except NoSuchElementException:
                        pass # Belum dibalas oleh creator, lanjutkan

                    # Filter 3: Jangan balas komentar full emoji atau komentar foto
                    cleaned_comment_for_reply = re.sub(r'[^\w\s.,?!]', '', original_comment).strip()
                    if not cleaned_comment_for_reply:
                        print(f"   -> Komentar hanya berisi emoji atau kosong: \"{original_comment}\". Melewati.")
                        comments_processed_count_in_video += 1
                        time.sleep(1)
                        continue
                    
                    # Deteksi komentar dengan indikator foto/gambar
                    photo_indicators = ['[写真]', '[Foto]', '[Image]', '[Photo]', '[gambar]', '[foto]']
                    if any(indicator in original_comment for indicator in photo_indicators):
                        print(f"   -> Komentar berisi indikator foto/gambar: \"{original_comment}\". Melewati.")
                        comments_processed_count_in_video += 1
                        time.sleep(1)
                        continue

                    # Jika lolos semua filter, coba balas
                    print(f"   -> Komentar lolos filter: \"{original_comment}\"")

                    reply_button = comment_element.find_element(By.CSS_SELECTOR, 'button[data-e2e="comment-action-reply"]')
                    reply_button.click()
                    print("   -> Tombol 'Reply' diklik.")
                    time.sleep(2)

                    text_box_selector = (By.XPATH, "//div[@role='textbox' and @contenteditable='true']")
                    text_box = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable(text_box_selector)
                    )
                    print("   -> Text box balasan terdeteksi.")

                    ai_generated_reply = generate_ai_reply(
                        video_transcript, 
                        cleaned_comment_for_reply, 
                        creator_character_description
                    )
                    
                    # Bersihkan balasan AI dari emoji non-BMP sebelum dikirim
                    ai_generated_reply_cleaned = re.sub(r'[^\U00000000-\U0000FFFF]', '', ai_generated_reply)
                    
                    if ai_generated_reply_cleaned == "[TIDAK_MEMBALAS]":
                        print("   -> AI menginstruksikan untuk TIDAK MEMBALAS komentar ini karena tidak relevan/valid.")
                        print("   -> Melewati balasan karena instruksi AI.")
                        # Tutup modal balasan jika AI menginstruksikan tidak membalas
                        try:
                            cancel_button = WebDriverWait(driver, 5).until(
                                EC.element_to_be_clickable((By.XPATH, "//div[@role='button' and @aria-label='Cancel']"))
                            )
                            cancel_button.click()
                            print("   -> Tombol 'Cancel' balasan diklik.")
                            WebDriverWait(driver, 5).until(EC.invisibility_of_element_located(text_box_selector))
                            print("   -> Modal balasan ditutup.")
                        except TimeoutException:
                            print("   -> Peringatan: Tombol 'Cancel' atau modal balasan tidak dapat ditutup.")
                        comments_processed_count_in_video += 1
                        time.sleep(1)
                        continue

                    reply_text_to_send = ai_generated_reply_cleaned
                    
                    # Kirim balasan
                    text_box.send_keys(reply_text_to_send)
                    print(f"   -> Mengetik balasan AI: \"{reply_text_to_send}\"")
                    time.sleep(1)
                    
                    post_button_selector = (By.XPATH, "//div[@role='button' and @aria-label='Post']") 

                    WebDriverWait(driver, 10).until(
                        element_attribute_is(post_button_selector, "aria-disabled", "false")
                    )
                    print("   -> Tombol 'Post' terdeteksi aktif secara logis (aria-disabled='false').")

                    # Handle kemungkinan elemen pengganggu
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
                    
                    # Tutup balasan dengan mengklik tombol "X" jika masih ada (opsional, untuk memastikan bersih)
                    try:
                        close_reply_modal_button = WebDriverWait(driver, 3).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, 'div[data-e2e="comment-modal-close-button"]'))
                        )
                        close_reply_modal_button.click()
                        print("   -> Tombol close modal reply diklik.")
                        time.sleep(1)
                    except TimeoutException:
                        print("   -> Peringatan: Tombol close modal reply tidak ditemukan atau tidak perlu diklik.")

                except TimeoutException as e:
                    print(f"   -> Timeout saat memproses komentar: {original_comment[:50]}... Error: {e}. Melanjutkan ke komentar berikutnya.")
                    # Coba tutup modal jika timeout terjadi di tengah proses balasan
                    try:
                        cancel_button_in_modal = WebDriverWait(driver, 2).until(
                            EC.element_to_be_clickable((By.XPATH, "//div[@role='button' and @aria-label='Cancel']"))
                        )
                        cancel_button_in_modal.click()
                        print("   -> Tombol 'Cancel' di modal balasan diklik setelah timeout.")
                    except:
                        pass # Abaikan jika gagal menutup
                    comments_processed_count_in_video += 1
                except NoSuchElementException as e:
                    print(f"   -> Elemen tidak ditemukan saat memproses komentar: {original_comment[:50]}... Error: {e}. Melanjutkan ke komentar berikutnya.")
                    comments_processed_count_in_video += 1
                except StaleElementReferenceException as e:
                    print(f"   -> Stale element saat memproses komentar: {original_comment[:50]}... Error: {e}. Mengabaikan komentar ini.")
                    comments_processed_count_in_video += 1
                except Exception as e:
                    print(f"   -> ERROR tak terduga saat memproses komentar: {original_comment[:50]}... Error: {e}. Melanjutkan ke komentar berikutnya.")
                    comments_processed_count_in_video += 1

            print(f"Selesai memproses komentar untuk video: {video_url}")
            driver.get(current_video_url) # Kembali ke halaman profil
            time.sleep(3)

        # PERUBAHAN: Setelah semua video diproses, update last_run_at melalui APIClient
        api_client.update_user_settings(user_id, {"last_run_at": datetime.now().isoformat()})
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Tugas bot selesai untuk user ID: {user_id}. last_run_at diperbarui.")

    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERROR fatal saat menjalankan bot untuk user ID: {user_id}. Error: {e}")
    finally:
        if driver:
            driver.quit()
            print(f"WebDriver ditutup untuk user {user_id}.")

# PERUBAHAN: Hapus bagian ini karena bot akan dipanggil oleh worker
# if __name__ == '__main__':
#     # Ini hanya contoh bagaimana bot akan dipanggil secara lokal
#     # di lingkungan pengembangan. Dalam produksi, ini akan dipanggil oleh worker.
#     # user_id = 1
#     # api_base_url = "http://localhost:5000" # Ganti dengan URL VPS Anda
#     # api_key = "bot_secret_key" # Ganti dengan API Key yang sesuai

#     # local_api_client = APIClient(api_base_url, api_key)
#     # run_tiktok_bot_task(user_id, local_api_client)
#     print("Script bot.py tidak berjalan secara langsung. Ini akan dipanggil oleh Worker.")
