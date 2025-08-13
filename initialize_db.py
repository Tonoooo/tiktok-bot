# backend/models.py sudah dibuat sebelumnya, sekarang kita inisialisasi
# di file terpisah untuk setup awal
import os
from flask import Flask
from backend.models import db, User, CreatorSettings

# Konfigurasi Flask app untuk database
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Inisialisasi SQLAlchemy dengan Flask app
db.init_app(app)

with app.app_context():
    # BARU: Pastikan baris ini ada dan tidak dikomentari
    db.create_all() # Ini akan membuat semua tabel yang didefinisikan di models.py

    # Contoh user dan setting (bisa dihapus atau diubah nanti)
    from werkzeug.security import generate_password_hash
    hashed_password = generate_password_hash("password_aman")

    # Cek apakah user sudah ada untuk mencegah duplikasi jika script dijalankan berkali-kali
    if not User.query.filter_by(username='creator_bot_user').first():
        user1 = User(username='creator_bot_user', email='botuser@example.com', password_hash=hashed_password)
        db.session.add(user1)
        db.session.commit() # Commit user dulu untuk mendapatkan ID
        print("User 'creator_bot_user' ditambahkan.")
    else:
        user1 = User.query.filter_by(username='creator_bot_user').first()
        print("User 'creator_bot_user' sudah ada.")

    # Cek apakah creator settings sudah ada
    if not CreatorSettings.query.filter_by(user_id=user1.id).first():
        import json # Pastikan import json ada di initialize_db.py
        settings1 = CreatorSettings(
            user_id=user1.id,
            tiktok_username='nama_akun_tiktok_anda', # Ganti dengan username TikTok Anda
            creator_character_description='pria, usia 20-an, tegas, suka humor, sering menggunakan kata "mantap"',
            gemini_api_key='AIzaSyDtIN6C60dm3-c3D3t2o0sYY293xktxe_U', # Ganti dengan API key asli Anda
            is_active=True,
            daily_run_count=3,
            processed_video_urls_json=json.dumps([])
        )
        db.session.add(settings1)
        db.session.commit()
        print("Pengaturan creator ditambahkan.")
    else:
        print("Pengaturan creator sudah ada.")


    print("Database siap. Anda bisa menambahkan data melalui script atau API.")