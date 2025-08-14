import os
import re
import yt_dlp
import whisper_timestamped as whisper
import shutil
import time 

# BARU: Import db, User, ProcessedVideo dari backend.models
from backend.models import db, User, ProcessedVideo 
from flask import Flask # Untuk mengakses app_instance dalam konteks
from datetime import datetime # Untuk mencatat processed_at

# PERUBAHAN: Fungsi sekarang menerima user_id dan app_instance
def get_video_transcript(video_url: str, user_id: int, app_instance: Flask) -> str:
    temp_audio_basename = "temp_tiktok_audio"
    transcript = ""
    downloaded_audio_path = None

    # --- PERUBAHAN UTAMA: LOGIKA CACHING TRANSKRIP DARI DATABASE ---
    with app_instance.app_context():
        # Cari video di database untuk user dan URL ini
        processed_video = ProcessedVideo.query.filter_by(
            user_id=user_id, 
            video_url=video_url
        ).first()

        if processed_video and processed_video.transcript:
            transcript = processed_video.transcript
            print(f"   -> Transkrip dimuat dari database untuk video: {video_url}")
            return transcript # Langsung kembalikan jika ditemukan di DB
        elif processed_video and not processed_video.transcript:
            print(f"   -> Video {video_url} sudah tercatat tapi belum ada transkrip. Akan mencoba menranskrip.")
            # Lanjutkan untuk menranskrip dan update entri yang sudah ada
        else:
            print(f"   -> Video {video_url} belum ada di database. Akan menranskrip dan menyimpan.")
            # Lanjutkan untuk menranskrip dan membuat entri baru
    # -----------------------------------------------------------

    try:
        # Konfigurasi yt-dlp untuk mengunduh audio terbaik dalam format wav
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',
                'preferredquality': '192',
            }],
            'outtmpl': temp_audio_basename, 
            'quiet': True, 
            'noplaylist': True, 
            'ffmpeg_location': 'C:/Program Files/ffmpeg/bin/ffmpeg.exe', # PATH ASLI ANDA!
            'ffprobe_location': 'C:/Program Files/ffmpeg/bin/ffprobe.exe' # PATH ASLI ANDA!
        }

        print(f"   -> Mengunduh audio dari video: {video_url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(video_url, download=True)
            downloaded_audio_path = f"{temp_audio_basename}.wav" 
            
            time.sleep(1) 

            if not os.path.exists(downloaded_audio_path):
                print(f"   -> Peringatan: File audio {downloaded_audio_path} tidak ditemukan setelah download, mencari alternatif.")
                found_files = [f for f in os.listdir('.') if f.startswith(temp_audio_basename) and f.endswith('.wav')]
                if found_files:
                    downloaded_audio_path = found_files[0]
                    print(f"   -> Menggunakan file alternatif: {downloaded_audio_path}")
                else:
                    raise FileNotFoundError(f"Tidak dapat menemukan file audio WAV yang diunduh untuk {video_url}")

            print(f"   -> Audio berhasil diunduh ke: {downloaded_audio_path}")

        print("   -> Memuat model Whisper (ini mungkin perlu waktu pertama kali)...")
        model = whisper.load_model("base", device="cpu") 
        print("   -> Model Whisper dimuat. Memulai transkripsi...")
        
        audio = whisper.load_audio(downloaded_audio_path)
        result = model.transcribe(audio, language="id", word_timestamps=False) 
        
        if result and "text" in result:
            transcript = result["text"].strip()
            print("   -> Transkripsi selesai.")

            # PERUBAHAN: Simpan/update transkrip ke database
            with app_instance.app_context():
                if processed_video: # Jika sudah ada entri, update transkrip dan processed_at
                    processed_video.transcript = transcript
                    processed_video.processed_at = datetime.utcnow()
                    db.session.add(processed_video) # Tambahkan ke sesi (walau sudah di query)
                    print(f"   -> Transkrip diperbarui di database untuk video: {video_url}")
                else: # Jika belum ada entri, buat yang baru
                    new_processed_video = ProcessedVideo(
                        user_id=user_id,
                        video_url=video_url,
                        transcript=transcript,
                        processed_at=datetime.utcnow()
                    )
                    db.session.add(new_processed_video)
                    print(f"   -> Transkrip disimpan ke database untuk video baru: {video_url}")
                db.session.commit() # Commit perubahan ke database
        else:
            print("   -> Transkripsi menghasilkan teks kosong.")

    except yt_dlp.utils.DownloadError as de:
        print(f"   -> ERROR DOWNLOAD AUDIO (yt-dlp): {de}")
        transcript = ""
    except FileNotFoundError as fnfe: 
        print(f"   -> ERROR FILE AUDIO TIDAK DITEMUKAN: {fnfe}")
        transcript = ""
    except Exception as e:
        print(f"   -> ERROR TRANSLITERASI: {e}")
        transcript = ""
    finally:
        # Membersihkan file audio sementara setelah digunakan
        if downloaded_audio_path and os.path.exists(downloaded_audio_path): 
            os.remove(downloaded_audio_path)
            print(f"   -> File sementara {downloaded_audio_path} dihapus.")
        for f in os.listdir('.'):
            if f.startswith(temp_audio_basename) and f != os.path.basename(__file__):
                try:
                    os.remove(f)
                    print(f"   -> File terkait yt-dlp {f} dihapus.")
                except OSError:
                    pass
    return transcript