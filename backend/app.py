import os
import json
import base64
from datetime import datetime, timedelta

from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, send_from_directory
from flask_login import LoginManager, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash

import sys
# Secara eksplisit tambahkan direktori proyek ke sys.path
# Ini memastikan Python dapat menemukan 'backend' sebagai paket.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if project_root not in sys.path:
    sys.path.append(project_root)
    
from backend.models import db, User, ProcessedVideo, ProcessedComment
from backend.forms import RegistrationForm, LoginForm

# HAPUS: run_tiktok_bot_task dan generate_qr_and_wait_for_login tidak lagi dipanggil di Flask app
# from akses_komen.bot import run_tiktok_bot_task 
# from akses_komen.qr_login_service import generate_qr_and_wait_for_login, QR_CODE_TEMP_DIR

from flask_login import LoginManager, login_user, logout_user, login_required, current_user 
from werkzeug.security import generate_password_hash, check_password_hash 

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kunci_rahasia_anda_yang_sangat_aman_dan_sulit_ditebak' 

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
db_path = os.path.join(project_root, 'site.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
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
        return redirect(url_for('login'))
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
        "cookies_json": user.cookies_json # Mengembalikan cookies sebagai JSON string
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
        db.session.add(user)
        db.session.commit()
        return jsonify({"message": "Cookies updated successfully!"}), 200
    except Exception as e:
        db.session.rollback()
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
    if 'file' not in request.files:
        return jsonify({"message": "No file part in the request"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"message": "No selected file"}), 400
    
    if file:
        filename = f"qrcode_{user_id}.png"
        file_path = os.path.join(QR_CODE_TEMP_DIR_SERVER, filename)
        file.save(file_path)
        return jsonify({"message": "QR image uploaded successfully", "filename": filename}), 200
    return jsonify({"message": "Failed to upload QR image"}), 500

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