import os
import json
import base64
from datetime import datetime, timedelta

from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, send_from_directory
from flask_login import LoginManager, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash

import sys
from rq import Queue
import redis

from backend.tasks import enqueue_qr_login_task # Import tugas RQ
from backend.forms import RegistrationForm, LoginForm, AiSettingsForm
from PIL import Image # Untuk memproses gambar QR
import io # Untuk memproses gambar QR

# Secara eksplisit tambahkan direktori proyek ke sys.path
# Ini memastikan Python dapat menemukan 'backend' sebagai paket.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if project_root not in sys.path:
    sys.path.append(project_root)
    
from backend.models import db, User, ProcessedVideo, ProcessedComment
from backend.forms import RegistrationForm, LoginForm, AiSettingsForm
from backend.tasks import enqueue_qr_login_task

# HAPUS: run_tiktok_bot_task dan generate_qr_and_wait_for_login tidak lagi dipanggil di Flask app
# from akses_komen.bot import run_tiktok_bot_task 
# from akses_komen.qr_login_service import generate_qr_and_wait_for_login, QR_CODE_TEMP_DIR

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kunci_rahasia_anda_yang_sangat_aman_dan_sulit_ditebak' 

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
db_path = os.path.join(project_root, 'site.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# CORS(app) 

db.init_app(app)

app.jinja_env.globals['datetime'] = datetime

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' 
login_manager.login_message = "Harap masuk untuk mengakses halaman ini."
login_manager.login_message_category = "warning"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# --- Konfigurasi Redis & RQ Queue ---
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
redis_conn = redis.from_url(REDIS_URL)
q = Queue(connection=redis_conn)
print(f"RQ Queue terinisialisasi dengan Redis di: {REDIS_URL}")

# ===============================================
# API Key Authentication untuk Bot Workers
# ===============================================
# API Key sederhana yang akan digunakan oleh bot lokal Anda untuk otentikasi
# Dalam produksi, gunakan metode yang lebih aman (mis. token JWT, manajemen API key yang lebih baik)
API_BOT_KEY = "super_secret_bot_key_123" # GANTI DENGAN KUNCI YANG LEBIH AMAN!

# Direktori untuk menyimpan QR code sementara di VPS
QR_CODE_TEMP_DIR_SERVER = os.path.join(project_root, 'qr_codes_temp_server')
if not os.path.exists(QR_CODE_TEMP_DIR_SERVER):
    os.makedirs(QR_CODE_TEMP_DIR_SERVER)

@app.before_request
def api_key_auth():
    api_key_endpoints = [
        'get_user_settings_api', 
        'update_user_cookies_api',
        'update_user_last_run_api',
        'get_processed_video_by_url_api',
        'save_processed_video_api',
        'upload_qr_image_api', 
        'get_active_users_for_bot',
        'save_processed_comment_api', 
        'api_update_user_qr_status',
        'api_update_user_cookies_status',
        'api_upload_qr_image'
    ]

    if request.endpoint in api_key_endpoints:
        provided_api_key = request.headers.get('X-API-Key')
        if not provided_api_key or provided_api_key != API_BOT_KEY:
            return jsonify({"message": "Unauthorized: Invalid API Key."}), 401

# ===============================================
# ROUTE WEBSITE (UI)
# ===============================================

@app.route('/')
def welcome():
    return render_template('welcome.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard')) # Jika sudah login, redirect ke dashboard

    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data)
        new_user = User(username=form.username.data, email=form.email.data, password_hash=hashed_password, is_admin=False) # Klien default bukan admin
        db.session.add(new_user)
        db.session.commit()
        flash('Akun Anda berhasil didaftarkan! Silakan masuk.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('register.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and check_password_hash(user.password_hash, form.password.data):
            login_user(user, remember=form.remember_me.data)
            flash('Berhasil masuk!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard'))
        else:
            flash('Login gagal. Periksa email dan kata sandi Anda.', 'danger')
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required 
def logout():
    logout_user()
    flash('Anda telah keluar.', 'info')
    return redirect(url_for('welcome'))

@app.route('/dashboard')
@login_required
def dashboard():
    total_videos = ProcessedVideo.query.filter_by(user_id=current_user.id).count()
    total_comments = ProcessedComment.query.filter(ProcessedComment.video.has(user_id=current_user.id)).count()
    return render_template('dashboard.html', total_videos=total_videos, total_comments=total_comments)


@app.route('/tiktok_connect')
@login_required
def tiktok_connect():
    user = User.query.get(current_user.id)
    if not user:
        flash("User tidak ditemukan.", "danger")
        return redirect(url_for('dashboard'))
    
    cookies_present = bool(user.cookies_json and json.loads(user.cookies_json))
    
    qr_process_active = user.qr_process_active
    qr_generated_at = user.qr_generated_at
    
    
    # URL untuk gambar QR code (akan dilayani oleh serve_qr_code)
    qr_image_url = url_for('serve_qr_code', filename=f'qrcode_{user.id}.png')
    
    return render_template('tiktok_connect.html', 
                            cookies_present=cookies_present, 
                            tiktok_username=user.tiktok_username,
                            qr_image_url=qr_image_url,
                            qr_process_active=qr_process_active, # BARU: Lewatkan ke template
                            qr_generated_at=qr_generated_at.isoformat() if qr_generated_at else None) # BARU: Lewatkan ke template


@app.route('/ai_settings', methods=['GET', 'POST'])
@login_required
def ai_settings():
    form = AiSettingsForm()
    user = User.query.get(current_user.id)

    if not user:
        flash("User tidak ditemukan.", "danger")
        return redirect(url_for('dashboard'))

    if form.validate_on_submit():
        # Proses form submission
        user.tiktok_username = form.tiktok_username.data
        user.creator_character_description = form.creator_character_description.data
        user.is_active = form.is_active.data
        
        try:
            # Validasi daily_run_count
            daily_run_count_int = int(form.daily_run_count.data)
            if daily_run_count_int < 0:
                flash('Jumlah Jalan Per Hari tidak boleh negatif.', 'danger')
                return render_template('ai_settings.html', form=form, user_settings=user)
            user.daily_run_count = daily_run_count_int
        except ValueError:
            flash('Jumlah Jalan Per Hari harus berupa angka.', 'danger')
            return render_template('ai_settings.html', form=form, user_settings=user)
        
        try:
            db.session.add(user)
            db.session.commit()
            flash('Pengaturan AI berhasil diperbarui!', 'success')
            return redirect(url_for('ai_settings'))
        except Exception as e:
            db.session.rollback()
            flash(f'Gagal memperbarui pengaturan AI: {e}', 'danger')

    elif request.method == 'GET':
        # Isi form dengan data user yang sudah ada
        form.tiktok_username.data = user.tiktok_username
        form.creator_character_description.data = user.creator_character_description
        form.is_active.data = user.is_active
        form.daily_run_count.data = str(user.daily_run_count) # Konversi ke string untuk form

    return render_template('ai_settings.html', form=form, user_settings=user)

@app.route('/ai_activity')
@login_required
def ai_activity():
    user_videos = ProcessedVideo.query.filter_by(user_id=current_user.id).order_by(ProcessedVideo.processed_at.desc()).all()
    
    videos_data = []
    for video in user_videos:
        # Hitung jumlah komentar yang dibalas untuk setiap video
        replied_comments_count = ProcessedComment.query.filter_by(processed_video_id=video.id, is_replied=True).count()
        total_comments_count = ProcessedComment.query.filter_by(processed_video_id=video.id).count()

        videos_data.append({
            "id": video.id,
            "video_url": video.url_for_display(), # Akan dibuat fungsi helper url_for_display() di models.py
            "transcript_snippet": (video.transcript[:100] + '...') if video.transcript and len(video.transcript) > 100 else video.transcript,
            "processed_at": video.processed_at.strftime('%Y-%m-%d %H:%M:%S'),
            "replied_comments_count": replied_comments_count,
            "total_comments_count": total_comments_count
        })
    
    return render_template('ai_activity.html', videos=videos_data)

# BARU: Rute untuk halaman "Detail Balasan Komentar" per Video
@app.route('/ai_activity/<int:video_id>/comments')
@login_required
def comment_details(video_id):
    video = ProcessedVideo.query.get_or_404(video_id)
    
    # Pastikan video ini milik user yang sedang login
    if video.user_id != current_user.id:
        flash("Anda tidak memiliki akses ke video ini.", "danger")
        return redirect(url_for('ai_activity'))
    
    comments = ProcessedComment.query.filter_by(processed_video_id=video.id).order_by(ProcessedComment.processed_at.asc()).all()
    
    comments_data = []
    for comment in comments:
        comments_data.append({
            "id": comment.id,
            "comment_text": comment.comment_text,
            "reply_text": comment.reply_text,
            "is_replied": comment.is_replied,
            "processed_at": comment.processed_at.strftime('%Y-%m-%d %H:%M:%S')
        })

    return render_template('comment_details.html', video=video, comments=comments_data)

# --- API ENDPOINT BARU UNTUK KLIEN (FLASK-LOGIN AUTHENTICATION) ---
# Ini berbeda dengan API Bot Worker yang menggunakan API Key

# Endpoint untuk mengambil daftar video yang diproses untuk user (melalui UI, otentikasi Flask-Login)
# Ini sudah ada di bawah, tapi kita bisa pakai rute /ai_activity
# @app.route('/api/processed_videos/<int:user_id>', methods=['GET'])
# @login_required
# def get_processed_videos_for_ui(user_id):
#     if current_user.id != user_id:
#         return jsonify({"message": "Unauthorized access."}), 403
#     # ... (logic sama seperti di bawah, tapi bisa diganti dengan rute ai_activity)

# Endpoint untuk mendapatkan detail komentar untuk video tertentu (melalui UI, otentikasi Flask-Login)
# Ini juga bisa diganti dengan rute comment_details
# @app.route('/api/processed_videos/<int:video_id>/comments_for_ui', methods=['GET'])
# @login_required
# def get_comments_for_video_ui(video_id):
#     video = ProcessedVideo.query.get_or_404(video_id)
#     if video.user_id != current_user.id:
#         return jsonify({"message": "Unauthorized access."}), 403
    
#     comments = ProcessedComment.query.filter_by(processed_video_id=video_id).order_by(ProcessedComment.processed_at.asc()).all()
    
#     comments_data = []
#     for comment in comments:
#         comments_data.append({
#             "id": comment.id,
#             "comment_text": comment.comment_text,
#             "reply_text": comment.reply_text,
#             "is_replied": comment.is_replied,
#             "processed_at": comment.processed_at.isoformat()
#         })
#     return jsonify({"comments": comments_data, "video_url": video.video_url}), 200

@app.route('/payment')
@login_required
def payment():
    # Di masa depan, logika ini akan memeriksa status langganan user
    # Untuk sekarang, ini adalah placeholder sederhana
    is_subscribed = False # Contoh: diasumsikan belum berlangganan
    subscription_end_date = None # Contoh: tanggal berakhir langganan
    
    # Contoh riwayat transaksi (dummy data)
    transaction_history = [
        {"id": 1, "date": "2025-08-01", "amount": "Rp 50.000", "status": "Sukses"},
        {"id": 2, "date": "2025-07-01", "amount": "Rp 50.000", "status": "Sukses"}
    ]

    return render_template('payment.html', 
                            is_subscribed=is_subscribed, 
                            subscription_end_date=subscription_end_date,
                            transaction_history=transaction_history)
    
# api untuk mengosongkan cookies tiktok
@app.route('/api/disconnect_tiktok', methods=['POST'])
@login_required
def api_disconnect_tiktok():
    user = User.query.get(current_user.id)
    if not user:
        return jsonify({"message": "User tidak ditemukan."}), 404
    
    try:
        user.cookies_json = json.dumps([]) # Set cookies menjadi JSON string kosong
        db.session.add(user)
        db.session.commit()
        return jsonify({"message": "Koneksi TikTok berhasil diputuskan."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": f"Gagal memutuskan koneksi TikTok: {e}"}), 500

# BARU: API Endpoint untuk memicu bot lokal agar memulai proses QR login baru
@app.route('/api/trigger_qr_login', methods=['POST'])
@login_required
def api_trigger_qr_login():
    user = User.query.get(current_user.id)
    if not user:
        return jsonify({"message": "User tidak ditemukan."}), 404
    
    try:
        # BARU: Atur status QR process menjadi aktif di database
        user.qr_process_active = True
        user.qr_generated_at = datetime.utcnow()
        user.cookies_json = json.dumps([]) # Pastikan cookies dikosongkan untuk pemicuan login baru

        db.session.add(user)
        db.session.commit()

        # Enqueue tugas QR login ke RQ
        enqueue_qr_login_task(user.id) # Panggil fungsi dari tasks.py

        # Juga hapus QR code image yang ada di VPS agar UI tidak menampilkan yang lama
        qr_image_path = os.path.join(QR_CODE_TEMP_DIR_SERVER, f'qrcode_{user.id}.png')
        if os.path.exists(qr_image_path):
            os.remove(qr_image_path)
            print(f"QR code lama untuk user {user.id} dihapus dari VPS.")
        
        return jsonify({"message": "Proses QR login akan dimulai. Mohon tunggu beberapa saat untuk QR code baru muncul."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": f"Gagal memicu proses QR login: {e}"}), 500

# BARU: API Endpoint untuk UI mengambil pengaturan user, termasuk status cookies
@app.route('/api/user_settings_for_ui', methods=['GET'])
@login_required
def api_get_user_settings_for_ui():
    user = User.query.get(current_user.id)
    if not user:
        return jsonify({"message": "User tidak ditemukan."}), 404
    
    return jsonify({
        "user_id": user.id,
        "username": user.username,
        "tiktok_username": user.tiktok_username,
        "cookies_json": user.cookies_json, # Kirim cookies_json untuk cek status di frontend
        "qr_process_active": user.qr_process_active, # Kirim status QR
        "qr_generated_at": user.qr_generated_at.isoformat() if user.qr_generated_at else None # Kirim timestamp QR
    }), 200
    
# BARU: Endpoint API untuk bot worker memperbarui status QR process
@app.route('/api/users/<int:user_id>/update_qr_status', methods=['POST'])
def api_update_user_qr_status(user_id):
    data = request.get_json()
    qr_process_active = data.get('qr_process_active')
    qr_generated_at_str = data.get('qr_generated_at')

    if qr_process_active is None: # Cukup cek qr_process_active
        return jsonify({"message": "Status aktif QR diperlukan."}), 400
    
    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "User tidak ditemukan."}), 404
    
    try:
        user.qr_process_active = bool(qr_process_active)
        if qr_generated_at_str:
            user.qr_generated_at = datetime.fromisoformat(qr_generated_at_str)
        else:
            user.qr_generated_at = None # Reset jika tidak ada timestamp

        db.session.commit()
        print(f"[{datetime.now()}] API: Status QR untuk user {user_id} diperbarui menjadi aktif={qr_process_active}, generated_at={qr_generated_at_str}")
        return jsonify({"message": "Status QR process user berhasil diperbarui."}), 200
    except Exception as e:
        db.session.rollback()
        print(f"[{datetime.now()}] API ERROR: Gagal memperbarui status QR untuk user {user_id}: {e}")
        return jsonify({"message": f"Error memperbarui status QR process: {e}"}), 500


@app.route('/api/users/<int:user_id>/update_cookies_status', methods=['POST'])
def api_update_user_cookies_status(user_id):
    data = request.get_json()
    cookies_json = data.get('cookies_json')
    

    if cookies_json is None: # PERBAIKAN: Cukup cek cookies_json is None
        return jsonify({"message": "cookies_json diperlukan."}), 400
    
    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "User tidak ditemukan."}), 404    
    
    try:
        user.cookies_json = cookies_json
        user.qr_process_active = False # Pastikan status QR dinonaktifkan
        user.qr_generated_at = None # Reset timestamp
        db.session.commit()

        # Hapus file QR code di server jika ada
        qr_image_path = os.path.join(QR_CODE_TEMP_DIR_SERVER, f'qrcode_{user_id}.png')
        if os.path.exists(qr_image_path):
            os.remove(qr_image_path)
            print(f"[{datetime.now()}] API: QR code lama untuk user {user_id} dihapus dari VPS.")

        print(f"[{datetime.now()}] API: Cookies user dan status QR berhasil diperbarui.")
        return jsonify({"message": "Cookies user dan status QR berhasil diperbarui."}), 200
    except Exception as e:
        db.session.rollback()
        print(f"[{datetime.now()}] API ERROR: Gagal memperbarui cookies dan status QR untuk user {user_id}: {e}")
        return jsonify({"message": f"Error memperbarui cookies dan status QR: {e}"}), 500


# Endpoint untuk pengaturan creator (melalui UI, otentikasi Flask-Login)
@app.route('/api/creator_settings/<int:user_id>', methods=['GET', 'POST'])
@login_required 
def handle_creator_settings(user_id):
    if current_user.id != user_id:
        return jsonify({"message": "Unauthorized access."}), 403

    user = User.query.get(user_id) 
    if not user:
        return jsonify({"message": "User not found."}), 404

    if request.method == 'POST':
        data = request.get_json()
        
        tiktok_username = data.get('tiktok_username')
        creator_character_description = data.get('creator_character_description')
        is_active = data.get('is_active') 
        daily_run_count = data.get('daily_run_count') 

        if tiktok_username is not None:
            user.tiktok_username = tiktok_username
        if creator_character_description is not None:
            user.creator_character_description = creator_character_description
        if is_active is not None:
            user.is_active = bool(is_active) 
        if daily_run_count is not None:
            user.daily_run_count = int(daily_run_count) 
        
        try:
            db.session.add(user)
            db.session.commit()
            return jsonify({"message": "Creator settings updated successfully!", 
                            "tiktok_username": user.tiktok_username,
                            "creator_character_description": user.creator_character_description,
                            "is_active": user.is_active,
                            "daily_run_count": user.daily_run_count
                            }), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({"message": f"Error updating settings: {e}"}), 500
    else: 
        return jsonify({
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "tiktok_username": user.tiktok_username,
            "creator_character_description": user.creator_character_description,
            "is_active": user.is_active,
            "daily_run_count": user.daily_run_count,
            "last_run_at": user.last_run_at.isoformat() if user.last_run_at else None,
            "cookies_present": bool(user.cookies_json) 
        }), 200

# Endpoint untuk daftar video yang diproses (melalui UI, otentikasi Flask-Login)
@app.route('/api/processed_videos/<int:user_id>', methods=['GET'])
@login_required
def get_processed_videos(user_id):
    if current_user.id != user_id:
        return jsonify({"message": "Unauthorized access."}), 403

    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "User not found."}), 404

    try:
        videos = ProcessedVideo.query.filter_by(user_id=user_id).order_by(ProcessedVideo.processed_at.desc()).all()
        
        videos_data = []
        for video in videos:
            videos_data.append({
                "id": video.id,
                "video_url": video.video_url,
                "transcript": video.transcript,
                "processed_at": video.processed_at.isoformat() 
            })
        
        return jsonify({"videos": videos_data}), 200
    except Exception as e:
        return jsonify({"message": f"Error fetching processed videos: {e}"}), 500


# Endpoint untuk memicu bot (melalui UI, otentikasi Flask-Login)
# Bot worker lokal akan mengambil tugas ini, bukan Flask langsung menjalankannya
# Dihapus karena bot tidak lagi dipicu langsung dari UI Flask ini
# @app.route('/api/run_bot/<int:user_id>', methods=['POST'])
# @login_required 
# def trigger_bot_run(user_id):
#     if current_user.id != user_id:
#         return jsonify({"message": "Unauthorized: You can only trigger the bot for your own user ID."}), 403

#     user = User.query.get(user_id) 
#     if not user: 
#         return jsonify({"message": f"User with ID {user_id} not found."}), 404

#     if user.cookies_json and json.loads(user.cookies_json):
#         print(f"Memicu bot untuk user ID: {user_id} di thread terpisah (menggunakan cookies yang ada).")
#         bot_thread = threading.Thread(target=run_tiktok_bot_task, args=(user_id, app,)) 
#         bot_thread.start()
#         return jsonify({"message": f"Bot task started for user ID {user_id} using existing cookies. Check console for progress."}), 202
#     else:
#         return jsonify({"message": f"User {user_id} needs to login to TikTok first. Use /api/start_tiktok_qr_login."}), 400


# Dihapus karena QR login akan dijalankan oleh bot worker lokal, bukan Flask app ini
# qr_login_tasks = {}
# @app.route('/api/start_tiktok_qr_login/<int:user_id>', methods=['POST'])
# @login_required
# def start_tiktok_qr_login(user_id):
#     if current_user.id != user_id:
#         return jsonify({"message": "Unauthorized access."}), 403

#     user = User.query.get(user_id)
#     if not user:
#         return jsonify({"message": "User not found."}), 404

#     if user.cookies_json and json.loads(user.cookies_json):
#         return jsonify({"message": "User already has TikTok cookies. No QR login needed.", "status": "logged_in"}), 200

#     if user_id in qr_login_tasks and qr_login_tasks[user_id].is_alive():
#         return jsonify({"message": "QR login process already in progress for this user.", "status": "in_progress"}), 202

#     print(f"Memulai proses QR login untuk user ID: {user_id} di thread terpisah.")
#     task_thread = threading.Thread(target=generate_qr_and_wait_for_login, args=(user_id, app,))
#     task_thread.start()
#     qr_login_tasks[user_id] = task_thread

#     return jsonify({"message": "QR login process started. Check /api/get_tiktok_qr_status for updates.", "status": "started"}), 202

# Dihapus karena QR login akan dijalankan oleh bot worker lokal, bukan Flask app ini
# @app.route('/api/get_tiktok_qr_status/<int:user_id>', methods=['GET'])
# @login_required
# def get_tiktok_qr_status(user_id):
#     if current_user.id != user_id:
#         return jsonify({"message": "Unauthorized access."}), 403

#     user = User.query.get(user_id)
#     if not user:
#         return jsonify({"message": "User not found."}), 404
    
#     if user.cookies_json and json.loads(user.cookies_json):
#         qr_image_file = f'qrcode_{user_id}.png'
#         qr_image_path = os.path.join(QR_CODE_TEMP_DIR, qr_image_file)
#         if os.path.exists(qr_image_path):
#             os.remove(qr_image_path)
#             print(f"QR code dihapus dari temp dir untuk user {user_id} karena sudah login.")
#         return jsonify({"status": "logged_in", "message": "User already logged in to TikTok."}), 200

#     if user_id in qr_login_tasks and qr_login_tasks[user_id].is_alive():
#         qr_image_file = f'qrcode_{user_id}.png'
#         qr_image_path = os.path.join(QR_CODE_TEMP_DIR, qr_image_file)
        
#         if os.path.exists(qr_image_path):
#             qr_image_url = f'/static/qr_codes/{qr_image_file}' 
#             return jsonify({"status": "qr_available", "qr_image_url": qr_image_url, "message": "Scan QR code to login."}), 200
#         else:
#             return jsonify({"status": "in_progress", "message": "Generating QR code..."}), 200
    
#     return jsonify({"status": "not_started", "message": "QR login process not started or failed previously."}), 200


# Endpoint untuk melayani file statis QR code (TETAP ADA untuk UI yang menampilkan gambar QR dari bot lokal)
# Kita hanya perlu memastikan folder QR_CODE_TEMP_DIR terkonfigurasi dengan benar di server.
QR_CODE_TEMP_DIR_SERVER = os.path.join(project_root, 'qr_codes_temp_server') # Folder sementara di VPS
os.makedirs(QR_CODE_TEMP_DIR_SERVER, exist_ok=True) # Buat jika belum ada

@app.route('/static/qr_codes/<filename>')
def serve_qr_code(filename):
    # Melayani gambar QR dari folder sementara di VPS
    return send_from_directory(QR_CODE_TEMP_DIR_SERVER, filename)


# ===============================================
# BOT WORKER Endpoints (Membutuhkan API Key)
# ===============================================

@app.route('/api/users/<int:user_id>', methods=['GET'])
def get_user_settings_api(user_id):
    """
    Mengambil pengaturan user untuk bot worker.
    Membutuhkan API Key.
    """
    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "User not found."}), 404
    
    return jsonify({
        "user_id": user.id,
        "username": user.username,
        "tiktok_username": user.tiktok_username,
        "creator_character_description": user.creator_character_description,
        "is_active": user.is_active,
        "daily_run_count": user.daily_run_count,
        "last_run_at": user.last_run_at.isoformat() if user.last_run_at else None,
        "cookies_json": user.cookies_json, # Mengembalikan cookies sebagai JSON string
        "qr_process_active": user.qr_process_active, # BARU: Tambahkan status QR
        "qr_generated_at": user.qr_generated_at.isoformat() if user.qr_generated_at else None # BARU: Tambahkan timestamp QR
    }), 200

@app.route('/api/users/<int:user_id>/cookies', methods=['POST'])
def update_user_cookies_api(user_id):
    """
    Memperbarui cookies TikTok untuk user tertentu.
    Membutuhkan API Key.
    """
    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "User not found."}), 404
    
    data = request.get_json()
    cookies_json = data.get('cookies_json')

    if not cookies_json:
        return jsonify({"message": "cookies_json is required."}), 400
    
    try:
        user.cookies_json = cookies_json # Simpan langsung sebagai JSON string
        # BARU: Reset status QR setelah cookies berhasil disimpan
        user.qr_process_active = False
        user.qr_generated_at = None

        # Hapus file QR code di server jika ada (karena login sudah berhasil)
        qr_image_path = os.path.join(QR_CODE_TEMP_DIR_SERVER, f'qrcode_{user_id}.png')
        if os.path.exists(qr_image_path):
            os.remove(qr_image_path)
            print(f"[{datetime.now()}] API: QR code lama untuk user {user_id} dihapus dari VPS (setelah cookies diterima).")

        db.session.add(user)
        db.session.commit()
        print(f"[{datetime.now()}] API: Cookies dan status QR untuk user {user_id} berhasil diperbarui.")
        return jsonify({"message": "Cookies updated successfully!"}), 200
    except Exception as e:
        db.session.rollback()
        print(f"[{datetime.now()}] API ERROR: Gagal memperbarui cookies dan status QR untuk user {user_id}: {e}")
        return jsonify({"message": f"Error updating cookies: {e}"}), 500
 
 
@app.route('/api/users/<int:user_id>/last_run', methods=['POST'])
def update_user_last_run_api(user_id):
    """
    Memperbarui timestamp last_run_at untuk user.
    Membutuhkan API Key.
    """
    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "User not found."}), 404
    
    try:
        user.last_run_at = datetime.now()
        db.session.add(user)
        db.session.commit()
        return jsonify({"message": "last_run_at updated successfully!"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": f"Error updating last_run_at: {e}"}), 500

@app.route('/api/processed_videos/by_url', methods=['GET'])
def get_processed_video_by_url_api():
    """
    Mengambil transkrip video berdasarkan user_id dan video_url.
    Membutuhkan API Key.
    """
    user_id = request.args.get('user_id', type=int)
    video_url = request.args.get('video_url')

    if not user_id or not video_url:
        return jsonify({"message": "user_id and video_url are required query parameters."}), 400

    video = ProcessedVideo.query.filter_by(user_id=user_id, video_url=video_url).first()
    if not video:
        return jsonify({"message": "Video transcript not found."}), 404
    
    return jsonify({
        "id": video.id,
        "user_id": video.user_id,
        "video_url": video.video_url,
        "transcript": video.transcript,
        "processed_at": video.processed_at.isoformat()
    }), 200

@app.route('/api/processed_videos', methods=['POST'])
def save_processed_video_api():
    """
    Menyimpan atau memperbarui transkrip video.
    Membutuhkan API Key.
    """
    data = request.get_json()
    user_id = data.get('user_id')
    video_url = data.get('video_url')
    transcript = data.get('transcript')

    if not user_id or not video_url or not transcript:
        return jsonify({"message": "user_id, video_url, and transcript are required."}), 400
    
    try:
        video = ProcessedVideo.query.filter_by(user_id=user_id, video_url=video_url).first()
        if video:
            video.transcript = transcript
            video.processed_at = datetime.now()
            db.session.add(video)
            db.session.commit()
            return jsonify({"message": "Video transcript updated successfully!", "id": video.id}), 200
        else:
            new_video = ProcessedVideo(
                user_id=user_id,
                video_url=video_url,
                transcript=transcript,
                processed_at=datetime.now()
            )
            db.session.add(new_video)
            db.session.commit()
            return jsonify({"message": "Video transcript saved successfully!", "id": new_video.id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": f"Error saving/updating video transcript: {e}"}), 500


@app.route('/api/processed_videos/<int:video_id>/comments', methods=['POST']) # BARU: Endpoint untuk menyimpan komentar
def save_processed_comment_api(video_id):
    """
    Menerima data komentar yang sudah diproses dari bot lokal dan menyimpannya ke database.
    Membutuhkan API Key.
    """
    data = request.get_json()
    if not data:
        return jsonify({"message": "Data komentar tidak ditemukan."}), 400

    # Pastikan video ada dan dimiliki oleh user yang terkait (ini mungkin perlu cek user_id juga dari bot)
    processed_video = ProcessedVideo.query.get(video_id)
    if not processed_video:
        return jsonify({"message": "Video yang diproses tidak ditemukan."}), 404

    # Ambil data komentar dari payload
    tiktok_comment_id = data.get('tiktok_comment_id')
    comment_text = data.get('comment_text')
    reply_text = data.get('reply_text')
    is_replied = data.get('is_replied', False)
    llm_raw_decision = data.get('llm_raw_decision')

    # Buat atau update ProcessedComment
    # Jika ada tiktok_comment_id, kita bisa mencoba mencari apakah komentar ini sudah ada untuk video ini
    existing_comment = None
    if tiktok_comment_id:
        existing_comment = ProcessedComment.query.filter_by(
            processed_video_id=video_id, 
            tiktok_comment_id=tiktok_comment_id
        ).first()

    if existing_comment:
        existing_comment.comment_text = comment_text
        existing_comment.reply_text = reply_text
        existing_comment.is_replied = is_replied
        existing_comment.llm_raw_decision = llm_raw_decision
        existing_comment.processed_at = datetime.utcnow() # Update timestamp
        db.session.commit()
        return jsonify({"message": "Komentar yang diproses berhasil diperbarui.", "comment_id": existing_comment.id}), 200
    else:
        new_comment = ProcessedComment(
            processed_video_id=video_id,
            tiktok_comment_id=tiktok_comment_id,
            comment_text=comment_text,
            reply_text=reply_text,
            is_replied=is_replied,
            llm_raw_decision=llm_raw_decision,
            processed_at=datetime.utcnow()
        )
        db.session.add(new_comment)
        db.session.commit()
        return jsonify({"message": "Komentar yang diproses berhasil disimpan.", "comment_id": new_comment.id}), 201

@app.route('/api/upload_qr_image/<int:user_id>', methods=['POST'])
def upload_qr_image_api(user_id):
    """
    Menerima gambar QR code dari bot lokal dan menyimpannya di direktori sementara VPS.
    Membutuhkan API Key.
    """
    if 'qr_image' not in request.files: # PERUBAHAN: Cek 'qr_image' sebagai key
        return jsonify({"message": "File gambar QR tidak ditemukan."}), 400    

    file = request.files['qr_image'] # PERBAIKAN: Mengambil file dari 'qr_image'
    if file.filename == '':
        return jsonify({"message": "Nama file kosong."}), 400
    
    if file:
        try:
            filename = f'qrcode_{user_id}.png'
            filepath = os.path.join(QR_CODE_TEMP_DIR_SERVER, filename)
            
            # Baca gambar menggunakan PIL untuk memastikan ukurannya minimal 250x250
            img = Image.open(io.BytesIO(file.read()))
            
            # Pastikan ukuran gambar minimal 250x250, jika lebih kecil, resize
            if img.width < 250 or img.height < 250:
                print(f"[{datetime.now()}] Peringatan: Gambar QR code untuk user {user_id} terlalu kecil ({img.width}x{img.height}). Mengubah ukurannya menjadi minimal 250x250.")
                # Resize dengan mempertahankan aspek rasio, dan pastikan tidak memperkecil jika sudah lebih besar
                ratio = min(250/img.width, 250/img.height) # Cari rasio terkecil
                new_width = int(img.width * ratio) if img.width < 250 else img.width
                new_height = int(img.height * ratio) if img.height < 250 else img.height
                img = img.resize((new_width, new_height), Image.LANCZOS)
                # Jika setelah resize masih ada sisi yang kurang dari 250 (misal dari rasio berbeda), pangkas atau tambahkan padding
                # Untuk saat ini, kita hanya memastikan ukuran minimal.
            
            img.save(filepath)

            print(f"[{datetime.now()}] API: QR code untuk user {user_id} berhasil diupload dan disimpan di {filepath}")
            return jsonify({"message": "QR code berhasil diupload."}), 200
        except Exception as e:
            print(f"[{datetime.now()}] API ERROR: Gagal memproses atau menyimpan QR code yang diupload: {e}")
            return jsonify({"message": f"Gagal memproses atau menyimpan QR code: {e}"}), 500

# BARU: Endpoint untuk bot worker mengambil daftar user aktif yang perlu diproses
@app.route('/api/active_users_for_bot', methods=['GET'])
def get_active_users_for_bot():
    """
    Mengembalikan daftar user ID yang aktif dan perlu diproses oleh bot worker.
    Membutuhkan API Key.
    """
    try:
        current_time = datetime.now()
        # Ambil semua user yang aktif
        active_users = User.query.filter_by(is_active=True).all()
        
        users_to_process = []
        for user in active_users:
            # Perhitungan sederhana untuk menentukan apakah user perlu diproses:
            # 1. Jika belum pernah jalan (last_run_at is None)
            # 2. Jika daily_run_count > 0 DAN sudah melewati interval yang ditentukan
            
            should_process = False
            
            if not user.last_run_at:
                should_process = True
            elif user.daily_run_count > 0:
                # Hitung interval per jalankan
                # Contoh: jika daily_run_count=3, berarti setiap 8 jam
                interval_hours = 24 / user.daily_run_count
                next_run_time = user.last_run_at + timedelta(hours=interval_hours)
                
                if current_time >= next_run_time:
                    should_process = True
            
            if should_process:
                # Hanya tambahkan jika tiktok_username ada, karena bot tidak bisa jalan tanpa ini
                if user.tiktok_username:
                    users_to_process.append({
                        "user_id": user.id,
                        "tiktok_username": user.tiktok_username,
                        "last_run_at": user.last_run_at.isoformat() if user.last_run_at else None,
                        "next_run_estimate": (user.last_run_at + timedelta(hours=24 / user.daily_run_count)).isoformat() if user.last_run_at and user.daily_run_count > 0 else "N/A"
                    })
                else:
                    print(f"Peringatan: User {user.id} aktif tetapi tidak memiliki tiktok_username. Melewati.")

        return jsonify({"users": users_to_process}), 200
    except Exception as e:
        print(f"ERROR: Gagal mengambil daftar user aktif untuk bot: {e}")
        return jsonify({"message": f"Error fetching active users for bot: {e}"}), 500

if __name__ == '__main__':
    print(f"Aplikasi Flask akan menggunakan database di: {db_path}") 
    app.run(debug=True, host='0.0.0.0', port=5000)