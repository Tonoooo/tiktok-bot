import undetected_chromedriver as uc
import time
import math # Import modul math untuk math.ceil
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, NoSuchElementException, StaleElementReferenceException
import pickle
import os

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

# --- SETUP BARU ---
# Menggunakan undetected_chromedriver
options = uc.ChromeOptions()
# Biarkan kosong untuk saat ini, kita bisa menambahkan proxy nanti
driver = uc.Chrome(options=options)
# ---------------------

print("MEMULAI OPERASI 'TEMBUS PERISAI'...")

target_akun = "cozy_kilo" # username target
target_url = f"https://www.tiktok.com/@{target_akun}" # Definisikan URL target
cookies_file = f"{target_akun}_cookies.pkl" # Nama file cookies

login_successful = False # Flag untuk melacak status login

try:
    # --- Coba muat cookies yang sudah ada ---
    if os.path.exists(cookies_file):
        print(f"File cookies ditemukan: {cookies_file}. Mencoba memuat cookies...")
        try:
            with open(cookies_file, 'rb') as f:
                cookies = pickle.load(f)

            driver.get("https://www.tiktok.com/") # Harus membuka domain sebelum menambahkan cookies
            for cookie in cookies:
                if 'expiry' in cookie and isinstance(cookie['expiry'], float):
                    cookie['expiry'] = int(cookie['expiry'])
                driver.add_cookie(cookie)
            
            driver.get(target_url) # Navigasi ke URL target dengan cookies
            print("Cookies berhasil dimuat dan browser diarahkan ke profil.")
            login_successful = True
            time.sleep(10) # Beri waktu halaman termuat
        except Exception as e:
            print(f"Gagal memuat atau menggunakan cookies: {e}. Melanjutkan dengan alur login QR code.")
            driver.quit()
            driver = uc.Chrome(options=options) # Inisialisasi ulang driver
            time.sleep(5) # Beri waktu untuk driver baru

    # --- Jika login belum berhasil (baik karena tidak ada cookies atau cookies gagal) ---
    if not login_successful:
        print("File cookies tidak ditemukan atau gagal dimuat. Memulai alur login QR code...")
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
            print(f"Gagal login via modal 'chose your interest' atau scan QR. Mencoba alur alternatif. Error: {e}")
        except Exception as e:
            print(f"Terjadi error tak terduga dalam alur login 'chose your interest': {e}")


        if not login_successful:
            try:
                print("Login belum berhasil, mencoba alur login melalui tombol 'Ikuti'...")
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
                print(f"Gagal login via tombol 'Ikuti' atau scan QR. Error: {e}")
                print("Login gagal setelah semua upaya. Periksa halaman secara manual.")
            except Exception as e:
                print(f"Terjadi error tak terduga dalam alur login 'Ikuti': {e}")
                print("Login gagal setelah semua upaya. Periksa halaman secara manual.")

        if login_successful:
            print(f"Login berhasil melalui QR code. Menyimpan cookies ke {cookies_file}...")
            with open(cookies_file, 'wb') as f:
                pickle.dump(driver.get_cookies(), f)
            print("Cookies berhasil disimpan.")
    
    if login_successful:
        print("Login berhasil terdeteksi dan halaman profil dimuat.")
        print(f"Berhasil menavigasi ke profil: {target_akun}")
        print("PERISAI BERHASIL DITEMBUS. Deteksi dasar berhasil dilewati.")

        time.sleep(5) # Beri waktu tambahan setelah login berhasil sebelum berinteraksi lebih lanjut

        # Set untuk menyimpan URL video yang sudah diproses agar tidak mengulang
        processed_video_urls = set()
        max_videos_to_process = 10 # Batasi jumlah video yang akan diproses per sesi

        # --- LANGKAH BARU: GULIR HALAMAN PROFIL UNTUK MEMUAT SEMUA VIDEO ---
        print("Mulai menggulir halaman profil untuk memuat semua video...")
        # Asumsi body adalah elemen scrollable utama. Jika ini tidak berfungsi, coba elemen kontainer lain.
        profile_scrollable_element = driver.find_element(By.TAG_NAME, 'body') 
        last_profile_height = driver.execute_script("return arguments[0].scrollHeight", profile_scrollable_element)
        profile_scroll_attempts = 0
        max_profile_scroll_attempts = 5 # Batas scroll profil, sesuaikan jika Anda memiliki ribuan video

        while profile_scroll_attempts < max_profile_scroll_attempts:
            driver.execute_script("arguments[0].scrollTo(0, arguments[0].scrollHeight);", profile_scrollable_element)
            time.sleep(2) # Beri waktu untuk video baru dimuat
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
            # Menggunakan XPath yang lebih spesifik untuk hanya mendapatkan video item yang memiliki link video
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
                    pass # Not pinned

                # Tambahkan ke antrian hanya jika tidak disematkan dan belum diproses
                if not is_pinned and video_url not in processed_video_urls:
                    unique_unprocessed_video_urls.append(video_url)
                    # Langsung tambahkan ke processed_video_urls di sini untuk mencegah duplikasi dalam antrian ini
                    processed_video_urls.add(video_url) 
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
            # Loop melalui URL video yang telah dikumpulkan dan difilter
            for video_url_to_process in unique_unprocessed_video_urls:
                if videos_processed_count >= max_videos_to_process:
                    print(f"Batasan {max_videos_to_process} video tercapai. Berhenti memproses video.")
                    break # Keluar dari loop for jika batas tercapai

                print(f"\n--- Memproses video: {video_url_to_process} ---")
                try:
                    driver.get(target_url) # Kembali ke profil untuk menemukan elemen video yang baru
                    print("Kembali ke halaman profil untuk re-fresh elemen.")
                    time.sleep(5) # Beri waktu untuk halaman profil memuat

                    # Cari kembali elemen video yang spesifik di halaman profil
                    # Kali ini, kita akan mencari berdasarkan URL-nya untuk mendapatkan elemen yang "segar"
                    video_item_element_on_profile = WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.XPATH, f"//div[@data-e2e='user-post-item']//a[@href='{video_url_to_process}']//ancestor::div[@data-e2e='user-post-item']"))
                    )
                    
                    print(f"Mencoba mengklik video: {video_url_to_process}")
                    WebDriverWait(driver, 15).until(
                        EC.element_to_be_clickable(video_item_element_on_profile)
                    )
                    video_item_element_on_profile.click()
                    print("Video terbaru berhasil diklik.")
                    time.sleep(10) # Beri waktu video untuk memuat dan komentar di sidebar muncul

                    # --- PROSES KOMENTAR (Logika yang sudah ada, ini tetap sama karena UI komentar konsisten) ---
                    print("Video terbuka. Menunggu komentar untuk dimuat dan memprosesnya...")
                    
                    # 1. Cek jumlah komentar dari elemen "Comments (X)"
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

                    # Lanjutkan dengan pemrosesan komentar hanya jika num_comments > 0 atau tidak bisa ditentukan
                    if num_comments > 0 or (num_comments == 0 and "Gagal mengurai" in locals().get('e', '')):
                        try:
                            # Pastikan setidaknya satu komentar dimuat sebelum mencoba scroll atau iterasi
                            WebDriverWait(driver, 10).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, '[data-e2e="comment-level-1"]'))
                            )
                            print("Setidaknya satu komentar awal dimuat.")

                            # --- SCROLLING KOMENTAR UNTUK MEMUAT LEBIH BANYAK ---
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

                                # Filter 1: Cek apakah komentar dibuat oleh Creator
                                is_creator_comment = False
                                try:
                                    creator_badge = comment_element.find_element(By.XPATH, ".//span[contains(@data-e2e, 'comment-creator-') and (text()='Creator' or text()='Pembuat')]")
                                    is_creator_comment = True
                                except NoSuchElementException:
                                    pass

                                if is_creator_comment:
                                    print("   -> Ini adalah komentar dari Creator. Melewati.")
                                    continue

                                # Filter 2: Cek apakah komentar sudah dibalas oleh Creator
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
                                    # Tambahkan wait untuk memastikan elemen pengganggu tidak ada
                                    try:
                                        WebDriverWait(driver, 2).until(
                                            EC.invisibility_of_element_located((By.CSS_SELECTOR, '.css-3yeu18-DivTabMenuContainer.e1aa9wve0'))
                                        )
                                        print("   -> Elemen tab menu pengganggu tidak terlihat.")
                                    except TimeoutException:
                                        print("   -> Elemen tab menu pengganggu tidak menjadi tidak terlihat dalam waktu yang ditentukan, melanjutkan.")
                                    # SyntaxError fix: Hapus baris 'except Exception as e:' yang menyebabkan SyntaxError di sini.
                                    # Outer try akan menangani error yang lebih umum.

                                    answer_comment_button = comment_element.find_element(By.CSS_SELECTOR, '[data-e2e^="comment-reply-"]')
                                    WebDriverWait(driver, 5).until(EC.element_to_be_clickable(answer_comment_button))
                                    answer_comment_button.click()
                                    print("   -> Tombol 'Jawab' berhasil diklik.")
                                    time.sleep(1)
                                    
                                    text_box = WebDriverWait(driver, 10).until(
                                        EC.presence_of_element_located((By.XPATH, "//div[@role='textbox' and @contenteditable='true']"))
                                    )
                                    text_box.send_keys(comment_text + " - " + "balasan otomatis dari Tono")
                                    print("   -> Mengetik balasan...")
                                    time.sleep(1)
                                    
                                    post_button_selector = (By.XPATH, "//div[@role='button' and @aria-label='Post']") 

                                    WebDriverWait(driver, 10).until(
                                        element_attribute_is(post_button_selector, "aria-disabled", "false")
                                    )
                                    print("   -> Tombol 'Post' terdeteksi aktif secara logis (aria-disabled='false').")

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
                    try:
                        close_button_selector = (By.XPATH, "//button[@role='button' and @aria-label='Close']")
                        close_button = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable(close_button_selector)
                        )
                        close_button.click()
                        print("Tombol 'Close' video berhasil diklik.")
                        time.sleep(5) # Beri waktu untuk kembali ke halaman profil
                        WebDriverWait(driver, 10).until(EC.url_to_be(target_url))
                        print("Berhasil kembali ke halaman profil.")
                        videos_processed_count += 1 # Tambah hitungan video yang berhasil diproses
                    except TimeoutException as e:
                        print(f"Gagal menemukan atau mengklik tombol 'Close' video: {e}. Mungkin sudah di halaman profil atau ada masalah lain.")
                        driver.get(target_url)
                        print("Melakukan navigasi paksa kembali ke halaman profil.")
                        time.sleep(5)
                        videos_processed_count += 1 # Tetap tambah hitungan meskipun ada error kecil, agar tidak terjebak
                    except Exception as e:
                        print(f"Terjadi error tak terduga saat menutup video: {e}.")
                        videos_processed_count += 1 # Tetap tambah hitungan
                
                except Exception as e: # Ini adalah except untuk try yang mengklik video (di baris ~238)
                    print(f"Terjadi error saat mencoba klik atau memproses video dari profil: {e}. Melanjutkan ke video berikutnya jika ada.")
                    # Jika ada error parah saat memproses video, pastikan kembali ke profil
                    driver.get(target_url) 
                    print("Melakukan navigasi paksa kembali ke halaman profil setelah error video.")
                    time.sleep(5)
                    videos_processed_count += 1 # Tambah hitungan agar loop bisa maju ke video berikutnya
                    continue # Lanjutkan ke iterasi berikutnya di loop for

            print(f"Selesai memproses {videos_processed_count} video.")

        print("Browser akan tetap terbuka selama 60 detik untuk observasi (setelah semua video diproses)...")
        time.sleep(60)

    else:
        print("Login gagal, tidak bisa melanjutkan operasi video dan komentar.")


finally:
    driver.quit()
    print("Operasi selesai.")