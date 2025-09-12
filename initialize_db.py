# Script untuk menginisialisasi database SQLite dan membuat tabel baru
import os
from flask import Flask
# PERUBAHAN: Import model User dan ProcessedVideo yang baru
from backend.models import db, User, ProcessedVideo
from werkzeug.security import generate_password_hash
from datetime import datetime # BARU: Untuk default value created_at dan processed_at
import json # Untuk menyimpan cookies_json dalam format JSON string kosong jika perlu

# Konfigurasi Flask app untuk database
app = Flask(__name__)

# PERBAIKAN: Setel instance_path agar Flask tidak membuat folder 'instance' default.
# Ini akan membuat site.db di lokasi yang sama dengan script ini (root proyek).
project_root = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__, instance_path=project_root)

# Gunakan jalur absolut yang pasti menunjuk ke root proyek
db_path = os.path.join(project_root, 'site.db')

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Inisialisasi SQLAlchemy dengan Flask app
db.init_app(app)

with app.app_context():
    print(f"Menginisialisasi database di: {db_path}") 
    
    db.drop_all() # Hapus semua tabel lama
    db.create_all() # Buat semua tabel baru
    
    # Hapus file database yang sudah ada untuk memastikan tabel dibuat ulang (PENTING!)
    if os.path.exists(db_path):
        print(f"Menghapus database yang sudah ada: {db_path}")
        os.remove(db_path)
    
    db.create_all() # Ini akan membuat semua tabel yang didefinisikan di models.py
    print("db.create_all() dipanggil untuk membuat tabel baru.")

    # Cek apakah tabel User sudah ada (setelah create_all)
    try:
        User.query.limit(1).all()
        print("Tabel 'user' terdeteksi.")
    except Exception as e:
        print(f"ERROR: Tabel 'user' TIDAK ditemukan setelah db.create_all(). Error: {e}")
        raise e 
    
    # Cek apakah tabel ProcessedVideo sudah ada (setelah create_all)
    try:
        ProcessedVideo.query.limit(1).all()
        print("Tabel 'processed_video' terdeteksi.")
    except Exception as e:
        print(f"ERROR: Tabel 'processed_video' TIDAK ditemukan setelah db.create_all(). Error: {e}")
        raise e 

    # --- Contoh user dan pengaturan creator (digabung dalam tabel User) ---
    hashed_password = generate_password_hash("password_aman")

    # Cek apakah user sudah ada untuk mencegah duplikasi jika script dijalankan berkali-kali
    if not User.query.filter_by(username='cozy_kilo').first():
        user1 = User(
            username='cozy_kilo', 
            email='cozy_kilo@gmail.com', 
            password_hash=hashed_password,
            tiktok_username='cozy_kilo', # Digabung dari CreatorSettings
            creator_character_description='pria, usia 20-an, tegas, suka humor, sering menggunakan kata "mantap"', # Digabung
            is_active=True, # Digabung
            daily_run_count=0, # Digabung
            # last_run_at akan diisi oleh bot saat pertama kali jalan
            cookies_json=json.dumps([]) # Default: list kosong untuk cookies
        )
        db.session.add(user1)
        db.session.commit() # Commit user dulu untuk mendapatkan ID
        print("User 'cozy_kilo' (dengan pengaturan creator) ditambahkan.")
    else:
        user1 = User.query.filter_by(username='cozy_kilo').first()
        print("User 'cozy_kilo' sudah ada.")

    # --- Contoh data ProcessedVideo (Opsional, untuk testing) ---
    # Jika Anda ingin menambahkan contoh video yang sudah diproses secara manual
    # Uncomment blok di bawah ini dan sesuaikan
    # if not ProcessedVideo.query.filter_by(video_url='https://www.tiktok.com/@cozy_kilo/video/12345').first():
    #     sample_video = ProcessedVideo(
    #         user_id=user1.id,
    #         video_url='https://www.tiktok.com/@cozy_kilo/video/12345',
    #         transcript='Ini adalah contoh transkrip video.',
    #         processed_at=datetime.utcnow()
    #     )
    #     db.session.add(sample_video)
    #     db.session.commit()
    #     print("Contoh ProcessedVideo ditambahkan.")
    # else:
    #     print("Contoh ProcessedVideo sudah ada.")
    
    print("Database siap. Anda bisa menambahkan data melalui script atau API.")