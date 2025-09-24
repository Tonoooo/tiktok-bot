import undetected_chromedriver as uc
import time
import os
import requests
from pydub import AudioSegment
import speech_recognition as sr
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- Variabel Global & Konfigurasi ---
PROFILES_DIR = 'browser_profiles_test' # Gunakan folder profil terpisah untuk tes
os.makedirs(PROFILES_DIR, exist_ok=True)

# --- Fungsi Helper ---

def download_audio(url, filename="captcha.mp3"):
    """Mengunduh file audio dari URL."""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"Audio berhasil diunduh ke {filename}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error saat mengunduh audio: {e}")
        return False

def solve_audio_captcha(mp3_path="captcha.mp3"):
    """Mengonversi, menambahkan hening, dan mentranskripsi audio."""
    try:
        # Konversi mp3 ke wav dan tambahkan 2 detik hening di awal
        wav_path = "captcha.wav"
        silence = AudioSegment.silent(duration=2000) # 2000 milidetik = 2 detik
        audio = AudioSegment.from_mp3(mp3_path)
        final_audio = silence + audio
        final_audio.export(wav_path, format="wav")
        print("Audio dikonversi ke WAV dan diberi jeda hening.")

        # Transkripsi audio
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
        
        # Gunakan Google Web Speech API (tidak perlu API key untuk ini)
        text = recognizer.recognize_google(audio_data).lower().replace(" ", "")
        print(f"Hasil transkripsi: {text}")
        return text
    except Exception as e:
        print(f"Error saat memproses audio: {e}")
        return None
    finally:
        # Hapus file sementara
        if os.path.exists(mp3_path): os.remove(mp3_path)
        if os.path.exists(wav_path): os.remove(wav_path)

# --- FUNGSI UTAMA TES ---

def run_captcha_test():
    driver = None
    try:
        # Inisialisasi driver seperti yang sudah terbukti berhasil
        profile_path = os.path.abspath(os.path.join(PROFILES_DIR, 'user_3'))
        options = uc.ChromeOptions()
        options.add_argument('--no-sandbox')
        options.add_argument('--window-size=1366,768')
        driver = uc.Chrome(options=options, user_data_dir=profile_path, headless=False)
        print("WebDriver diinisialisasi.")

        # Buka halaman yang pasti memicu captcha
        driver.get("https://www.tiktok.com/@cozy_kilo") # Ganti dengan URL yang relevan jika perlu
        
        # Tunggu hingga modal captcha muncul
        print("Menunggu modal captcha muncul (maks 30 detik)...")
        captcha_modal = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '.captcha-verify-container'))
        )
        print("Modal captcha terdeteksi.")
        
        # Beralih ke captcha audio
        try:
            audio_button = captcha_modal.find_element(By.ID, "captcha_switch_button")
            audio_button.click()
            print("Beralih ke mode captcha audio.")
            time.sleep(2)
        except Exception as e:
            print(f"Gagal menemukan tombol audio, mungkin sudah di mode audio: {e}")

        # Loop utama untuk menyelesaikan captcha (maks 3 kali refresh audio)
        for audio_refresh_attempt in range(3):
            print(f"\n--- Percobaan Audio ke-{audio_refresh_attempt + 1} ---")
            
            # Dapatkan URL audio
            audio_element = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "audio"))
            )
            audio_url = audio_element.get_attribute('src')
            
            if not audio_url:
                print("Gagal mendapatkan URL audio.")
                raise Exception("Audio URL not found.")

            # Loop untuk mencoba transkripsi (maks 3 kali per audio)
            solved_text = None
            for transcript_attempt in range(3):
                print(f"  > Percobaan transkripsi ke-{transcript_attempt + 1}")
                if download_audio(audio_url):
                    solved_text = solve_audio_captcha()
                    if solved_text and len(solved_text) > 2: # Asumsi captcha setidaknya 3 karakter
                        break # Jika berhasil, keluar dari loop transkripsi
                time.sleep(1)

            # Jika berhasil, ketik dan verifikasi
            if solved_text:
                print(f"Teks captcha berhasil didapat: {solved_text}")
                input_field = captcha_modal.find_element(By.CSS_SELECTOR, "input[placeholder='Enter what you hear']")
                input_field.send_keys(solved_text)
                time.sleep(1)

                verify_button = captcha_modal.find_element(By.XPATH, "//button[.//div[text()='Verify']]")
                verify_button.click()
                print("Tombol 'Verify' diklik.")
                
                # Beri waktu untuk verifikasi, lalu cek apakah modal captcha sudah hilang
                time.sleep(5)
                try:
                    WebDriverWait(driver, 5).until(
                        EC.invisibility_of_element_located((By.CSS_SELECTOR, '.captcha-verify-container'))
                    )
                    print("✅✅✅ CAPTCHA BERHASIL DISELESAIKAN! ✅✅✅")
                    return # Keluar dari fungsi utama jika berhasil
                except TimeoutException:
                    print("❌ Captcha masih ada. Mencoba audio baru...")
            
            # Jika setelah 3 kali transkripsi masih gagal, klik refresh
            if audio_refresh_attempt < 2: # Jangan klik refresh di percobaan terakhir
                try:
                    refresh_button = captcha_modal.find_element(By.ID, "captcha_refresh_button")
                    refresh_button.click()
                    print("Tombol refresh audio diklik. Menunggu audio baru...")
                    time.sleep(3)
                except Exception as e:
                    print(f"Gagal menekan tombol refresh: {e}")
                    break # Keluar jika tidak bisa refresh
            else:
                print("Gagal menyelesaikan captcha setelah 3 audio berbeda.")

    except Exception as e:
        print(f"Terjadi error pada alur utama: {e}")
    finally:
        print("Tes selesai. Browser akan tetap terbuka selama 60 detik untuk inspeksi.")
        time.sleep(60)
        if driver:
            driver.quit()

if __name__ == "__main__":
    run_captcha_test()