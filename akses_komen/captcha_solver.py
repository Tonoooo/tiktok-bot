import time
import os
import requests
import speech_recognition as sr
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import subprocess

# --- FUNGSI HELPER YANG DIPERBARUI ---
def download_audio(url, user_id):
    """Mengunduh file audio dari URL dengan nama file unik."""
    filename = f"captcha_{user_id}.mp3"
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"Audio berhasil diunduh ke {filename}")
        return filename
    except requests.exceptions.RequestException as e:
        print(f"Error saat mengunduh audio: {e}")
        return None

def solve_audio_captcha(mp3_path, user_id):
    """Mengonversi dan mentranskripsi audio menggunakan nama file unik."""
    wav_path = f"captcha_final_{user_id}.wav"
    try:
        print("Memulai konversi audio dengan subprocess.Popen...")
        command = [
            "/usr/bin/ffmpeg", "-nostdin", "-y", "-i", mp3_path,
            "-af", "adelay=2000|2000", "-loglevel", "error", wav_path
        ]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate(timeout=15)
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, command, output=stdout, stderr=stderr)
        print("Konversi audio ke WAV dengan jeda hening berhasil.")

        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
        
        text = recognizer.recognize_google(audio_data).lower().replace(" ", "")
        print(f"Hasil transkripsi: {text}")
        return text
        
    except Exception as e:
        print(f"Error saat memproses audio: {e}")
        return None
    finally:
        if os.path.exists(mp3_path): os.remove(mp3_path)
        if os.path.exists(wav_path): os.remove(wav_path)

# --- FUNGSI UTAMA YANG DIPERBARUI ---
def solve_captcha(driver, user_id):
    """Mendeteksi dan menyelesaikan captcha, menggunakan user_id untuk file sementara."""
    try:
        print("Mendeteksi modal captcha...")
        captcha_modal = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '.captcha-verify-container'))
        )
        print("Modal captcha terdeteksi.")
        
        try:
            audio_button = captcha_modal.find_element(By.ID, "captcha_switch_button")
            audio_button.click()
            print("Beralih ke mode captcha audio.")
            time.sleep(2)
        except Exception:
            print("Sudah dalam mode audio atau tombol tidak ditemukan.")

        for audio_refresh_attempt in range(6):
            print(f"\n--- Percobaan Audio ke-{audio_refresh_attempt + 1} ---")
            audio_element = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "audio")))
            audio_url = audio_element.get_attribute('src')
            if not audio_url: raise Exception("URL Audio tidak ditemukan.")

            solved_text = None
            for _ in range(3):
                mp3_filename = download_audio(audio_url, user_id)
                if mp3_filename:
                    solved_text = solve_audio_captcha(mp3_filename, user_id)
                    if solved_text and len(solved_text) > 2:
                        break
                time.sleep(1)

            if solved_text:
                print(f"Teks captcha berhasil didapat: {solved_text}")
                input_field = captcha_modal.find_element(By.CSS_SELECTOR, "input[placeholder='Enter what you hear']")
                input_field.clear()
                input_field.send_keys(solved_text)
                time.sleep(1)
                verify_button = captcha_modal.find_element(By.XPATH, "//button[.//div[text()='Verify']]")
                verify_button.click()
                print("Tombol 'Verify' diklik.")
                
                time.sleep(7)
                if not driver.find_elements(By.CSS_SELECTOR, '.captcha-verify-container'):
                    print("✅✅✅ CAPTCHA BERHASIL DISELESAIKAN! ✅✅✅")
                    return True
                else:
                    print("❌ Captcha masih ada. Mencoba audio baru...")
            
            if audio_refresh_attempt < 2:
                captcha_modal.find_element(By.ID, "captcha_refresh_button").click()
                print("Tombol refresh audio diklik.")
                time.sleep(3)
        
        print("Gagal menyelesaikan captcha setelah 3 audio berbeda.")
        return False

    except (TimeoutException, NoSuchElementException):
        print("Tidak ada captcha yang terdeteksi.")
        return True
    except Exception as e:
        print(f"Terjadi error pada alur penyelesaian captcha: {e}")
        return False