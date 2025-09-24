import yt_dlp
import whisper_timestamped as whisper
import os
import re
import time
from typing import Dict, Any

# PERUBAHAN: Import APIClient
from akses_komen.api_client import APIClient

def get_video_transcript(video_url: str, user_id: int, api_client: APIClient) -> str:
    temp_audio_basename = "temp_tiktok_audio"
    transcript = ""
    downloaded_audio_path = None

    # Ekstrak Video ID dari URL untuk identifikasi unik
    video_id_match = re.search(r'/video/(\d+)', video_url)
    video_id = video_id_match.group(1) if video_id_match else None

    if not video_id:
        print(f"   -> Peringatan: Tidak dapat mengekstrak Video ID dari URL: {video_url}. Tidak akan menggunakan cache database.")
        # Lanjutkan tanpa cache jika ID tidak dapat diekstrak

    # PERUBAHAN: Cek cache transkrip di database melalui APIClient
    if video_id:
        try:
            cached_video = api_client.get_processed_video(user_id, video_url)
            if cached_video and cached_video.get('transcript'):
                transcript = cached_video['transcript']
                print(f"   -> Transkrip dimuat dari cache database untuk video ID: {video_id}")
                return transcript
        except Exception as e:
            print(f"   -> Peringatan: Gagal mengambil transkrip dari cache database untuk {video_id}: {e}")

    # Konfigurasi yt-dlp
    # Pastikan ffmpeg dan ffprobe tersedia di PATH atau tentukan lokasinya secara eksplisit
    # Untuk lingkungan VPS Ubuntu, biasanya ffmpeg/ffprobe sudah diinstal global
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': temp_audio_basename + '.%(ext)s',
        'verbose': False,
        'quiet': True,
        'no_warnings': True,
        # 'ffmpeg_location': '/usr/bin/ffmpeg',   # Uncomment dan sesuaikan jika ffmpeg tidak di PATH
        # 'ffprobe_location': '/usr/bin/ffprobe', # Uncomment dan sesuaikan jika ffprobe tidak di PATH
    }

    print(f"   -> Mengunduh audio dari {video_url}...")
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(video_url, download=True)
            downloaded_audio_path = ydl.prepare_filename(info_dict).rsplit('.', 1)[0] + '.mp3'
        print(f"   -> Audio berhasil diunduh ke: {downloaded_audio_path}")
        time.sleep(1) # Beri jeda setelah download
    except yt_dlp.utils.DownloadError as e:
        print(f"   -> ERROR saat mengunduh audio: {e}")
        # Jika gagal download, kita tidak bisa transkripsi, jadi return kosong.
        if downloaded_audio_path and os.path.exists(downloaded_audio_path):
            os.remove(downloaded_audio_path)
            print(f"   -> File audio sementara {downloaded_audio_path} dihapus.")
        return ""
    except Exception as e:
        print(f"   -> ERROR tak terduga saat mengunduh audio: {e}")
        if downloaded_audio_path and os.path.exists(downloaded_audio_path):
            os.remove(downloaded_audio_path)
            print(f"   -> File audio sementara {downloaded_audio_path} dihapus.")
        return ""

    if downloaded_audio_path and os.path.exists(downloaded_audio_path):
        print(f"   -> Mentranskripsi audio {downloaded_audio_path} menggunakan Whisper...")
        try:
            # Memuat model Whisper (pastikan model ini bisa diinstal di VPS Anda)
            # Anda mungkin perlu model yang lebih kecil seperti 'tiny' atau 'base' untuk 2GB RAM
            model = whisper.load_model("tiny") 
            result = whisper.transcribe(model, downloaded_audio_path)
            
            if result and "text" in result:
                transcript = result["text"].strip()
                print("   -> Transkripsi selesai.")
                # PERUBAHAN: Simpan transkrip ke database melalui APIClient (akan melakukan upsert)
                if video_id: # Hanya simpan jika ID video valid
                    try:
                        api_client.save_processed_video(user_id, video_url, transcript)
                        print(f"   -> Transkrip disimpan ke cache database untuk video ID: {video_id}")
                    except Exception as e:
                        print(f"   -> Peringatan: Gagal menyimpan transkrip ke cache database untuk {video_id}: {e}")
            else:
                print("   -> Peringatan: Hasil transkripsi kosong.")
        except Exception as e:
            print(f"   -> ERROR saat transkripsi audio: {e}")
            print("   -> Pastikan model Whisper dapat diunduh dan dijalankan. Coba model yang lebih kecil.")
        finally:
            os.remove(downloaded_audio_path)
            print(f"   -> File audio sementara {downloaded_audio_path} dihapus.")
    else:
        print("   -> File audio tidak ditemukan untuk transkripsi.")

    return transcript