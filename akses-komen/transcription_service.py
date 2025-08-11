import os
import re
import yt_dlp
import whisper_timestamped as whisper
import shutil
import time # Jangan lupa import time jika digunakan di get_video_transcript

def get_video_transcript(video_url: str) -> str:
    # Nama file sementara untuk audio (TANPA EKSTENSI di sini)
    temp_audio_basename = "temp_tiktok_audio"
    transcript = ""
    downloaded_audio_path = None # Inisialisasi variabel ini

    # --- BARU: LOGIKA CACHING TRANSKRIP ---
    cache_dir = "transcripts_cache"
    os.makedirs(cache_dir, exist_ok=True) # Pastikan folder cache ada

    video_id_match = re.search(r'/video/(\d+)', video_url)
    video_id = video_id_match.group(1) if video_id_match else None

    if video_id:
        cache_file_path = os.path.join(cache_dir, f"{video_id}.txt")
        if os.path.exists(cache_file_path):
            with open(cache_file_path, 'r', encoding='utf-8') as f:
                transcript = f.read()
            print(f"   -> Transkrip dimuat dari cache: {cache_file_path}")
            return transcript # Langsung kembalikan jika ditemukan di cache
    else:
        print(f"   -> Peringatan: Tidak dapat mengekstrak Video ID dari URL: {video_url}. Tidak akan menggunakan cache.")
    # ------------------------------------

    try:
        # Konfigurasi yt-dlp untuk mengunduh audio terbaik dalam format wav
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',
                'preferredquality': '192',
            }],
            'outtmpl': temp_audio_basename, # Nama file output (tanpa ekstensi)
            'quiet': True, # Supress output yt-dlp ke konsol
            'noplaylist': True, # Pastikan hanya satu video yang diunduh
            'ffmpeg_location': 'C:/Program Files/ffmpeg/bin/ffmpeg.exe', # PATH ASLI ANDA!
            'ffprobe_location': 'C:/Program Files/ffmpeg/bin/ffprobe.exe' # PATH ASLI ANDA!
        }

        print(f"   -> Mengunduh audio dari video: {video_url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(video_url, download=True)
            # Dapatkan nama file yang sebenarnya setelah post-processing (harusnya .wav)
            # yt-dlp secara otomatis menambahkan ekstensi dari preferredcodec
            downloaded_audio_path = f"{temp_audio_basename}.wav" # Asumsi yt-dlp akan membuatnya .wav
            
            time.sleep(1) # Tambahkan jeda singkat untuk memastikan file siap

            if not os.path.exists(downloaded_audio_path):
                print(f"   -> Peringatan: File audio {downloaded_audio_path} tidak ditemukan setelah download, mencari alternatif.")
                # Fallback: cari file .wav apapun yang mungkin dibuat yt-dlp dengan nama dasar yang sama
                found_files = [f for f in os.listdir('.') if f.startswith(temp_audio_basename) and f.endswith('.wav')]
                if found_files:
                    downloaded_audio_path = found_files[0]
                    print(f"   -> Menggunakan file alternatif: {downloaded_audio_path}")
                else:
                    raise FileNotFoundError(f"Tidak dapat menemukan file audio WAV yang diunduh untuk {video_url}")

            print(f"   -> Audio berhasil diunduh ke: {downloaded_audio_path}")

        # Memuat model Whisper (akan diunduh pertama kali)
        # Gunakan model "base" untuk keseimbangan kecepatan dan akurasi.
        # "cpu" untuk menjalankan di CPU, ganti "cuda" jika memiliki GPU NVIDIA
        print("   -> Memuat model Whisper (ini mungkin perlu waktu pertama kali)...")
        model = whisper.load_model("base", device="cpu") # Ganti "cpu" dengan "cuda" jika Anda punya GPU NVIDIA
        print("   -> Model Whisper dimuat. Memulai transkripsi...")
        
        # Transkripsi audio, tentukan bahasa Indonesia
        audio = whisper.load_audio(downloaded_audio_path)
        result = model.transcribe(audio, language="id", word_timestamps=False) # word_timestamps=False untuk transkrip keseluruhan
        
        if result and "text" in result:
            transcript = result["text"].strip()
            print("   -> Transkripsi selesai.")

            # BARU: Simpan transkrip ke cache setelah berhasil
            if video_id: # Pastikan kita punya video_id untuk menyimpan
                with open(cache_file_path, 'w', encoding='utf-8') as f:
                    f.write(transcript)
                print(f"   -> Transkrip disimpan ke cache: {cache_file_path}")
        else:
            print("   -> Transkripsi menghasilkan teks kosong.")

    except yt_dlp.utils.DownloadError as de:
        print(f"   -> ERROR DOWNLOAD AUDIO (yt-dlp): {de}")
        transcript = ""
    except FileNotFoundError as fnfe: # Tangani error jika file audio tidak ditemukan
        print(f"   -> ERROR FILE AUDIO TIDAK DITEMUKAN: {fnfe}")
        transcript = ""
    except Exception as e:
        print(f"   -> ERROR TRANSLITERASI: {e}")
        transcript = ""
    finally:
        # Membersihkan file audio sementara setelah digunakan
        if downloaded_audio_path and os.path.exists(downloaded_audio_path): # Cek apakah sudah diinisialisasi dan ada
            os.remove(downloaded_audio_path)
            print(f"   -> File sementara {downloaded_audio_path} dihapus.")
        # Hapus juga file-file lain yang mungkin dibuat yt-dlp (misal .webp, .json)
        for f in os.listdir('.'):
            # Pastikan hanya menghapus file yang dimulai dengan nama temp_audio_basename dan bukan nama file skrip itu sendiri
            if f.startswith(temp_audio_basename) and f != os.path.basename(__file__):
                try:
                    os.remove(f)
                    print(f"   -> File terkait yt-dlp {f} dihapus.")
                except OSError:
                    pass
    return transcript