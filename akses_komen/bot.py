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
from selenium.common.exceptions import WebDriverException

import math
# PERUBAHAN: Import APIClient dan get_video_transcript, generate_ai_reply
from akses_komen.api_client import APIClient
from akses_komen.transcription_service import get_video_transcript
from akses_komen.llm_service import generate_ai_reply

# BARU: Import db dan model User, ProcessedVideo
# from backend.models import db, User, ProcessedVideo 
# from flask import Flask 


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
        # options.add_argument('--headless') # Jalankan browser tanpa GUI
        # options.add_argument('--disable-gpu') # Diperlukan untuk headless di beberapa sistem
        # options.add_argument('--no-sandbox') # Diperlukan untuk headless di Linux server
        # options.add_argument('--disable-dev-shm-usage') # Mengatasi masalah resource di Docker/VPS

        driver = uc.Chrome(options=options)
        print("WebDriver berhasil diinisialisasi.")

        # Sembunyikan navigator.webdriver = undefined
        # driver.execute_cdp_cmd(
        #     "Page.addScriptToEvaluateOnNewDocument",
        #     {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}
        # )
        # try:
        #     driver.execute_cdp_cmd("Network.enable", {})
        # except Exception:
        #     pass

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
        profile_scrollable_element = driver.find_element(By.TAG_NAME, 'body') 
        last_profile_height = driver.execute_script("return arguments[0].scrollHeight", profile_scrollable_element)
        scroll_attempts = 0
        max_scroll_attempts = 10 # Batasi scroll untuk mencegah loop tak terbatas
        
        while scroll_attempts < max_scroll_attempts:
            driver.execute_script("arguments[0].scrollTo(0, arguments[0].scrollHeight);", profile_scrollable_element)
            time.sleep(3) # Tingkatkan jeda sedikit
            new_profile_height = driver.execute_script("return arguments[0].scrollHeight", profile_scrollable_element)
            if new_profile_height == last_profile_height:
                print(f"Tidak ada video baru yang dimuat setelah {scroll_attempts+1} scroll profil. Berhenti.")
                break
            last_profile_height = new_profile_height
            scroll_attempts += 1
            print(f"Profil discroll {scroll_attempts} kali. Tinggi baru: {new_profile_height}")
        print("Selesai menggulir halaman profil.")
        
        # --- Kumpulkan semua URL video unik yang memenuhi kriteria setelah menggulir profil ---
        all_video_elements_after_scroll = []
        try:
            # Coba selector yang lebih umum untuk item video di profil
            all_video_elements_after_scroll = WebDriverWait(driver, 15).until(
                EC.presence_of_all_elements_located((By.XPATH, "//div[starts-with(@data-e2e, 'user-post-item') and .//a[contains(@href, '/video/')]]"))
            )
            print(f"Ditemukan total {len(all_video_elements_after_scroll)} elemen video di DOM setelah scrolling.")
        except TimeoutException:
            print("Tidak ada elemen video yang valid dengan tautan video ditemukan dalam waktu yang ditentukan setelah scrolling. Mengakhiri proses.")
            all_video_elements_after_scroll = []
        
        recent_unpinned_video_urls = []
        max_videos_to_process_per_run = 15 # Didefinisikan di sini
        
        for video_item_element in all_video_elements_after_scroll:
            try:
                video_link_element = video_item_element.find_element(By.CSS_SELECTOR, 'a[href*="/video/"]')
                video_url = video_link_element.get_attribute('href')
                
                is_pinned = False
                try:
                    # Mencari badge pinned dengan teks "Pinned" atau "Disematkan"
                    pinned_badge = video_item_element.find_element(By.XPATH, ".//div[contains(@data-e2e, 'video-card-badge') and (text()='Pinned' or text()='Disematkan')]")
                    is_pinned = True
                    print(f"   -> Video disematkan/Pinned ditemukan, melewati (URL: {video_url}).")
                except NoSuchElementException:
                    pass # Bukan video pinned
                    
                if not is_pinned: 
                    if video_url not in recent_unpinned_video_urls: # Hanya tambahkan URL unik
                        recent_unpinned_video_urls.append(video_url)
                        print(f"   -> Video non-disematkan ditambahkan ke antrean: {video_url}")
                
            except NoSuchElementException:
                print("   -> Peringatan: Tautan video tidak ditemukan dalam item video. Melewati.")
                continue
            except StaleElementReferenceException:
                print("   -> StaleElementReferenceException saat mencari tautan video di pengumpulan awal. Melewati.")
                continue

        # Karena kita sudah mengumpulkan URL unik di loop di atas, kita tidak perlu seen_urls lagi di sini.
        # Tinggal ambil 15 terbaru.
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
                        # NAVIGASI LANGSUNG KE VIDEO UNTUK STABILITAS
                        driver.get(video_url_to_process) 
                        print(f"Langsung menavigasi ke URL video: {video_url_to_process}")
                        time.sleep(5) # Beri waktu untuk video dimuat

                        # CEK VIDEO TIKTOK SHOP
                        tiktok_shop_toast_selector = (By.XPATH, "//div[contains(@class, 'TUXTopToast-content') and (text()='View TikTok Shop videos in the TikTok app' or text()='Lihat video TikTok Shop di aplikasi TikTok')]")
                        is_tiktok_shop_video = False
                        try:
                            print("   -> Mencoba mendeteksi toast 'Lihat video TikTok Shop'...")
                            WebDriverWait(driver, 5).until( # Tingkatkan timeout untuk deteksi toast
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

                        # --- Dapatkan Transkrip Video ---
                        # PERBAIKAN: Ganti user.id dan app_instance dengan user_id dan api_client
                        print(f"Mencoba mendapatkan transkrip untuk video: {video_url_to_process}")
                        video_transcript = get_video_transcript(video_url_to_process, user_id, api_client) 
                        
                        if not video_transcript: 
                            print("   -> Transkrip video kosong atau gagal didapatkan. Melewatkan video ini.")
                            video_process_successful = True 
                            continue 
                        else:
                            print(f"Transkrip berhasil didapatkan (potongan): {video_transcript[:100]}...")

                        # --- PROSES KOMENTAR ---
                        print("Video terbuka. Menunggu komentar untuk dimuat dan memprosesnya...")
                        
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
                                        # Selector yang lebih umum untuk teks komentar
                                        comment_text_element = comment_element.find_element(By.CSS_SELECTOR, 'div[data-e2e^="comment-content-"]')
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
                                    photo_indicators = ['[写真]', '[foto]', '[image]', '[photo]', '[gambar]'] # Tambahkan bahasa Indonesia
                                    if any(indicator in comment_text.lower() for indicator in photo_indicators):
                                        print("   -> Komentar berisi indikator foto/gambar. Melewati.")
                                        continue

                                    # Filter 3: Cek apakah komentar dibuat oleh Creator (Filter yang sudah ada)
                                    is_creator_comment = False
                                    try:
                                        # Perbaiki selector untuk badge creator
                                        creator_badge = comment_element.find_element(By.XPATH, ".//span[contains(@data-e2e, 'comment-creator-badge') or contains(@class, 'DivCreatorBadge')]")
                                        is_creator_comment = True
                                    except NoSuchElementException:
                                        pass
                                    
                                    if is_creator_comment:
                                        print("   -> Ini adalah komentar dari Creator. Melewati.")
                                        continue

                                    # Filter 4: Cek apakah komentar sudah dibalas oleh Creator (Filter yang sudah ada)
                                    has_creator_replied = False
                                    try:
                                        # Selector untuk memverifikasi balasan dari creator
                                        # Mencari div balasan yang berisi elemen yang menunjukkan itu adalah balasan creator
                                        reply_content = comment_element.find_element(By.XPATH, ".//div[contains(@class, 'DivReplyContainer')]//div[contains(@class, 'DivCommentContentContainer')]")
                                        # Dalam DivCommentContentContainer, cari teks "Anda" atau badge creator
                                        reply_content.find_element(By.XPATH, ".//span[text()='Anda' or contains(@data-e2e, 'comment-creator-badge')]")
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
                                        
                                        # Perbaiki selector tombol reply
                                        answer_comment_button = comment_element.find_element(By.XPATH, ".//button[contains(@data-e2e, 'comment-action-reply')]")
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
                                                # Tutup modal balasan jika AI menginstruksikan tidak membalas
                                                try:
                                                    cancel_button = WebDriverWait(driver, 5).until(
                                                        EC.element_to_be_clickable((By.XPATH, "//div[@role=\'button\' and @aria-label=\'Cancel\']"))
                                                    )
                                                    cancel_button.click()
                                                    print("   -> Tombol \'Cancel\' balasan diklik.")
                                                    WebDriverWait(driver, 5).until(EC.invisibility_of_element_located(text_box)) # Tunggu textbox hilang
                                                    print("   -> Modal balasan ditutup.")
                                                except TimeoutException:
                                                    print("   -> Peringatan: Tombol \'Cancel\' atau modal balasan tidak dapat ditutup.")
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
                                        # Tutup modal balasan jika timeout terjadi di tengah proses balasan
                                        try:
                                            cancel_button_in_modal = WebDriverWait(driver, 2).until(
                                                EC.element_to_be_clickable((By.XPATH, "//div[@role=\'button\' and @aria-label=\'Cancel\']"))
                                            )
                                            cancel_button_in_modal.click()
                                            print("   -> Tombol \'Cancel\' di modal balasan diklik setelah timeout.")
                                            WebDriverWait(driver, 5).until(EC.invisibility_of_element_located(text_box)) # Tunggu textbox hilang
                                        except:
                                            pass # Abaikan jika gagal menutup
                                    except ElementClickInterceptedException as e:
                                        print(f"   -> Tombol/text box terhalang: {e}. Melewati balasan ini.")
                                        # Tutup modal balasan jika terhalang
                                        try:
                                            cancel_button_in_modal = WebDriverWait(driver, 2).until(
                                                EC.element_to_be_clickable((By.XPATH, "//div[@role=\'button\' and @aria-label=\'Cancel\']"))
                                            )
                                            cancel_button_in_modal.click()
                                            print("   -> Tombol \'Cancel\' di modal balasan diklik setelah terhalang.")
                                            WebDriverWait(driver, 5).until(EC.invisibility_of_element_located(text_box)) # Tunggu textbox hilang
                                        except:
                                            pass # Abaikan jika gagal menutup
                                    except Exception as e:
                                        print(f"   -> Terjadi error tak terduga saat membalas komentar: {e}. Melewati balasan ini.")
                                        # Tutup modal balasan jika ada error tak terduga
                                        try:
                                            cancel_button_in_modal = WebDriverWait(driver, 2).until(
                                                EC.element_to_be_clickable((By.XPATH, "//div[@role=\'button\' and @aria-label=\'Cancel\']"))
                                            )
                                            cancel_button_in_modal.click()
                                            print("   -> Tombol \'Cancel\' di modal balasan diklik setelah error tak terduga.")
                                            WebDriverWait(driver, 5).until(EC.invisibility_of_element_located(text_box)) # Tunggu textbox hilang
                                        except:
                                            pass # Abaikan jika gagal menutup
                                    comments_processed_count_in_video += 1
                                        
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
                            WebDriverWait(driver, 10).until(EC.url_to_be(f"https://www.tiktok.com/@{tiktok_username}")) # Gunakan tiktok_username
                            print("Berhasil kembali ke halaman profil.")
                        except TimeoutException as e:
                            print(f"Gagal menemukan atau mengklik tombol 'Close' video: {e}. Mungkin sudah di halaman profil atau ada masalah lain.")
                            driver.get(f"https://www.tiktok.com/@{tiktok_username}") # Navigasi paksa ke profil
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
                                driver.get(f"https://www.tiktok.com/@{tiktok_username}") # Refresh ke profil
                                time.sleep(5)
                            except WebDriverException as nav_e:
                                print(f"ERROR: Gagal menavigasi kembali ke profil setelah error: {nav_e}. Driver mungkin perlu diinisialisasi ulang.")
                                if driver: driver.quit()
                                driver = None 
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
                                # # Sembunyikan navigator.webdriver = undefined
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
                                break 
                        time.sleep(5) 
                    except Exception as e:
                        print(f"ERROR TAK TERDUGA SAAT MEMPROSES VIDEO {video_url_to_process} (Upaya {video_retry_count}/{MAX_VIDEO_RETRIES}): {e}")
                        break 

                videos_processed_count += 1 

            if not video_process_successful:
                print(f"Video {video_url_to_process} gagal diproses setelah {MAX_VIDEO_RETRIES} upaya. Melewatkan.")

        print(f"Selesai memproses {videos_processed_count} video untuk {tiktok_username}.") # Ganti target_akun dengan tiktok_username

        # BARU: Update last_run_at di database - Ganti dengan panggilan APIClient yang benar
        # user.last_run_at = datetime.now() 
        # db.session.add(user) 
        # db.session.commit()
        api_client.update_user_last_run_api(user_id) # Panggil metode APIClient yang benar
        print(f"Waktu terakhir bot dijalankan untuk user ID: {user_id} diperbarui melalui API.") # Perbarui pesan log

    except Exception as e: # <--- TANGKAP EXCEPTION DARI BLOK TRY UTAMA
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERROR fatal saat menjalankan bot untuk user ID: {user_id}. Error: {e}") # Ganti target_akun
    finally: # <--- BLOK FINALLY SEKARANG BERPASANGAN DENGAN TRY UTAMA
        if driver:
            driver.quit()
            print(f"Operasi selesai untuk user ID: {user_id}. Browser ditutup.") # Ganti target_akun
        else:
            print(f"Operasi selesai untuk user ID: {user_id}. Driver tidak diinisialisasi atau sudah ditutup.") # Ganti target_akun





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
