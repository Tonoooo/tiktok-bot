from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime, timedelta
import threading 
import os 
import json 

import sys
# Secara eksplisit tambahkan direktori proyek ke sys.path
# Ini memastikan Python dapat menemukan 'backend' sebagai paket.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if project_root not in sys.path:
    sys.path.append(project_root)
    
from backend.models import db, User, ProcessedVideo

# HAPUS: run_tiktok_bot_task dan generate_qr_and_wait_for_login tidak lagi dipanggil di Flask app
# from akses_komen.bot import run_tiktok_bot_task 
# from akses_komen.qr_login_service import generate_qr_and_wait_for_login, QR_CODE_TEMP_DIR

from flask_login import LoginManager, login_user, logout_user, login_required, current_user 
from werkzeug.security import generate_password_hash, check_password_hash 

app = Flask(__name__)

# Konfigurasi Flask app untuk database
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
db_path = os.path.join(project_root, 'site.db')

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_secret_key' 

CORS(app) 

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' 

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ===============================================
# API Key Authentication untuk Bot Workers
# ===============================================
# API Key sederhana yang akan digunakan oleh bot lokal Anda untuk otentikasi
# Dalam produksi, gunakan metode yang lebih aman (mis. token JWT, manajemen API key yang lebih baik)
API_BOT_KEY = "botyangdijalankanlokal30082025" # GANTI DENGAN KUNCI YANG LEBIH AMAN!

@app.before_request
def api_key_auth():
    # List endpoint yang membutuhkan API Key
    # NOTE: user_id di endpoint ini adalah user_id dari User tabel, bukan creator_id.
    api_key_endpoints = [
        'get_user_settings_api', 
        'update_user_cookies_api',
        'update_user_last_run_api',
        'get_processed_video_by_url_api',
        'save_processed_video_api',
        # Tambahkan endpoint bot lainnya di sini
    ]

    if request.endpoint in api_key_endpoints:
        provided_api_key = request.headers.get('X-API-Key')
        if not provided_api_key or provided_api_key != API_BOT_KEY:
            return jsonify({"message": "Unauthorized: Invalid API Key."}), 401

# ===============================================
# WEB UI Endpoints (Membutuhkan Flask-Login)
# ===============================================

@app.route('/')
def index():
    return jsonify({"message": "TikTok Auto-Responder Backend API is running!"})

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.get_json()
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        
        if not username or not email or not password:
            return jsonify({"message": "Username, email, and password are required."}), 400

        hashed_password = generate_password_hash(password)

        with app.app_context():
            existing_user = User.query.filter((User.username == username) | (User.email == email)).first()
            if existing_user:
                return jsonify({"message": "Username or email already exists."}), 409

            new_user = User(
                username=username, 
                email=email, 
                password_hash=hashed_password,
                tiktok_username=None, 
                creator_character_description=None,
                is_active=True,
                daily_run_count=0,
                last_run_at=None,
                cookies_json=json.dumps([])
            )
            db.session.add(new_user)
            db.session.commit()
            print(f"User baru terdaftar: {username}")
            return jsonify({"message": "User registered successfully!", "user_id": new_user.id}), 201
    
    return jsonify({"message": "Send POST request to register."}), 405

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return jsonify({"message": "Username and password are required."}), 400
        
        with app.app_context():
            user = User.query.filter_by(username=username).first()
            
            if user and check_password_hash(user.password_hash, password):
                login_user(user) 
                print(f"User {username} berhasil login.")
                return jsonify({"message": "Login successful!", "user_id": user.id, "username": user.username}), 200
            else:
                return jsonify({"message": "Invalid username or password."}), 401
    
    return jsonify({"message": "Send POST request to login."}), 405

@app.route('/logout')
@login_required 
def logout():
    logout_user()
    print(f"User {current_user.username if current_user.is_authenticated else 'unknown'} telah logout.")
    return jsonify({"message": "Logged out successfully."}), 200

@app.route('/dashboard')
@login_required
def dashboard():
    return jsonify({"message": f"Welcome to the dashboard, {current_user.username}!", "user_id": current_user.id}), 200

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

# Endpoint untuk bot lokal mengupload gambar QR ke VPS
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

if __name__ == '__main__':
    print(f"Aplikasi Flask akan menggunakan database di: {db_path}") 
    app.run(debug=True, host='0.0.0.0', port=5000)
