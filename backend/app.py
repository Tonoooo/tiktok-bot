import os
import json
import base64
from datetime import datetime, timedelta

from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, send_from_directory
from flask_login import LoginManager, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from flask import session
from werkzeug.middleware.proxy_fix import ProxyFix

import sys
from rq import Queue
import redis

from backend.tasks import enqueue_qr_login_task,  enqueue_comment_processing_task # Import tugas RQ
from backend.forms import RegistrationForm, LoginForm, AiSettingsForm
from PIL import Image # Untuk memproses gambar QR
import io # Untuk memproses gambar QR

# Secara eksplisit tambahkan direktori proyek ke sys.path
# Ini memastikan Python dapat menemukan 'backend' sebagai paket.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if project_root not in sys.path:
    sys.path.append(project_root)
    
from backend.models import db, User, ProcessedVideo, ProcessedComment

# HAPUS: run_tiktok_bot_task dan generate_qr_and_wait_for_login tidak lagi dipanggil di Flask app
# from akses_komen.bot import run_tiktok_bot_task 
# from akses_komen.qr_login_service import generate_qr_and_wait_for_login, QR_CODE_TEMP_DIR

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kunci_rahasia_anda_yang_sangat_aman_dan_sulit_ditebak' 

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
db_path = os.path.join(project_root, 'site.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True # Untuk keamanan, cookie hanya bisa diakses via HTTP
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax' # Pengaturan SameSite yang umum dan aman

# app.config['SERVER_NAME'] = 'sitono.online'

# app.config['SESSION_COOKIE_DOMAIN'] = '.sitono.online'

app.config['PREFERRED_URL_SCHEME'] = 'https' 

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1) # Terapkan ProxyFix

db.init_app(app)

app.jinja_env.globals['datetime'] = datetime

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' 
login_manager.login_message = "Harap masuk untuk mengakses halaman ini."
login_manager.login_message_category = "warning"

@login_manager.user_loader
def load_user(user_id):
    # print(f"[{datetime.now()}] DEBUG: load_user dipanggil dengan user_id: {user_id}")
    user = User.query.get(int(user_id))
    # print(f"[{datetime.now()}] DEBUG: load_user mengembalikan user: {user.id if user else 'None'}")
    # print(f"[{datetime.now()}] DEBUG: Current session in load_user: {session}") # BARU: Periksa sesi di user_loader
    return user


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
        'api_upload_qr_image',
        'api_update_user_comment_run_status',
        'api_onboarding_trial_bot_completed'
    ]
    
    if request.endpoint == 'serve_qr_code':
        return

    if request.endpoint in api_key_endpoints:
        provided_api_key = request.headers.get('X-API-Key')
        if not provided_api_key or provided_api_key != API_BOT_KEY:
            return jsonify({"message": "Unauthorized: Invalid API Key."}), 401

# ===============================================
# Middleware Pengalihan Onboarding (BARU)
# ===============================================
@app.before_request
def onboarding_redirect_middleware():
    # Lewati jika tidak ada user yang login atau sedang mengakses endpoint yang diizinkan
    if not current_user.is_authenticated:
        #print(f"[{datetime.now()}] DEBUG Middleware: Endpoint={request.endpoint}, Is Authenticated={current_user.is_authenticated}, User ID={current_user.id if current_user.is_authenticated else 'N/A'}") # TAMBAH USER ID
        #print(f"[{datetime.now()}] DEBUG Middleware: Current session in middleware: {session}") # BARU: Periksa sesi di middleware
        # Izinkan akses ke welcome, register, login, static files
        if request.endpoint in ['welcome', 'register', 'login', 'static', 'serve_qr_code']:
            return None
        #print(f"[{datetime.now()}] DEBUG Middleware: Redirecting unauthenticated user from {request.endpoint} to welcome.")
        return redirect(url_for('welcome')) # Arahkan ke welcome jika belum login
    
    # Lewati untuk endpoint API bot worker (sudah ditangani oleh api_key_auth)
    # Dan endpoint API UI untuk ambil settings (akan dicek di rute masing-masing)
    if request.endpoint and request.endpoint.startswith('api_'):
        return None

    # Lewati untuk endpoint logout dan payment (payment akan dihandle secara terpisah)
    if request.endpoint in ['logout', 'payment']:
        return None

    user = current_user

    # Jika sudah berlangganan atau admin, arahkan ke dashboard normal
    if user.is_subscribed or user.is_admin:
        if request.endpoint in ['dashboard', 'ai_settings', 'tiktok_connect', 'ai_activity', 'comment_details']: # Izinkan akses ke semua rute normal
            return None # Sudah di dashboard
        # Jika sedang mengakses halaman onboarding, arahkan ke dashboard
        if request.endpoint in ['onboarding_ai_settings', 'onboarding_tiktok_connect', 'onboarding_trial_cta']:
            return redirect(url_for('dashboard'))
        return None # Biarkan mengakses halaman yang diminta (selain onboarding)

    # =========================================================================
    # Logika Pengalihan Onboarding untuk Pengguna yang Belum Berlangganan
    # =========================================================================
    
    current_onboarding_route = request.endpoint

    # Definisikan urutan alur onboarding
    onboarding_flow = {
        'REGISTERED': 'onboarding_ai_settings',
        'AI_SETTINGS_PENDING': 'onboarding_ai_settings',
        'TIKTOK_CONNECT_PENDING': 'onboarding_tiktok_connect',
        'TRIAL_CTA': 'onboarding_trial_cta',
        'TRIAL_RUNNING': 'onboarding_trial_cta',
        'TRIAL_COMPLETED': 'onboarding_trial_cta',
    }

    expected_route_for_stage = onboarding_flow.get(user.onboarding_stage)

    # Jika user mencoba mengakses rute yang bukan bagian dari flow onboarding
    if current_onboarding_route not in onboarding_flow.values() and current_onboarding_route not in ['dashboard', 'welcome']:
        flash('Harap lengkapi alur onboarding Anda.', 'info')
        return redirect(url_for(expected_route_for_stage))

    # Jika user tidak berada di halaman yang diharapkan sesuai tahap onboarding
    if expected_route_for_stage and current_onboarding_route != expected_route_for_stage:
        flash('Harap lengkapi alur onboarding Anda.', 'info')
        return redirect(url_for(expected_route_for_stage))
        
    return None

# ===============================================
# ROUTE WEBSITE (UI)
# ===============================================

@app.route('/')
def welcome():
    return render_template('welcome.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data)
        new_user = User(username=form.username.data, 
                        email=form.email.data, 
                        password_hash=hashed_password, 
                        is_admin=False,
                        onboarding_stage='AI_SETTINGS_PENDING',
                        is_active=False, 
                        is_subscribed=False,
                        has_used_free_trial=False) 
        db.session.add(new_user)
        db.session.commit()
        flash('Akun Anda berhasil didaftarkan! Silakan masuk.', 'success')
        login_user(new_user)
        # print(f"[{datetime.now()}] DEBUG Register: login_user dipanggil untuk user {new_user.id}. Mengalihkan ke onboarding_ai_settings.")
        # print(f"[{datetime.now()}] DEBUG Register: Session after login_user: {session}") # BARU: Periksa sesi setelah login_user
        return redirect(url_for('onboarding_ai_settings')) 
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
            # print(f"[{datetime.now()}] DEBUG Login: login_user dipanggil untuk user {user.id}. Mengalihkan.")
            # print(f"[{datetime.now()}] DEBUG Login: Session after login_user: {session}")
            next_page = request.args.get('next')
            if user.is_subscribed or user.is_admin:
                return redirect(next_page or url_for('dashboard'))
            else:
                return redirect(next_page or url_for('onboarding_ai_settings')) # Arahkan ke titik awal onboarding
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
    user = current_user # Pastikan mengambil user dari current_user
    total_videos = ProcessedVideo.query.filter_by(user_id=user.id).count()
    total_comments = ProcessedComment.query.filter(ProcessedComment.video.has(user_id=user.id)).count()
    return render_template('dashboard.html', total_videos=total_videos, total_comments=total_comments, user=user) # Pass user object

# ===============================================
# ROUTE ONBOARDING (BARU)
# ===============================================

@app.route('/onboarding/ai_settings', methods=['GET', 'POST'])
@login_required
def onboarding_ai_settings(): # Rute khusus untuk onboarding AI Settings
    form = AiSettingsForm()
    user = User.query.get(current_user.id)

    if not user:
        flash("User tidak ditemukan.", "danger")
        return redirect(url_for('welcome'))

    if form.validate_on_submit():
        user.tiktok_username = form.tiktok_username.data
        user.creator_character_description = form.creator_character_description.data
        
        # Untuk onboarding, kita tidak mengubah is_active dan daily_run_count
        # user.is_active = form.is_active.data 
        # user.daily_run_count = form.daily_run_count.data
        
        try:
            user.onboarding_stage = 'TIKTOK_CONNECT_PENDING' # Pindah ke tahap selanjutnya
            db.session.add(user)
            db.session.commit()
            flash('Pengaturan AI awal berhasil disimpan! Sekarang hubungkan akun TikTok Anda.', 'success')
            return redirect(url_for('onboarding_tiktok_connect'))
        except Exception as e:
            db.session.rollback()
            flash(f'Gagal menyimpan pengaturan AI: {e}', 'danger')

    elif request.method == 'GET':
        form.tiktok_username.data = user.tiktok_username
        form.creator_character_description.data = user.creator_character_description
        # Jangan isi is_active dan daily_run_count di mode onboarding
        # form.is_active.data = user.is_active
        # form.daily_run_count.data = str(user.daily_run_count)

    return render_template('ai_settings.html', form=form, user_settings=user, onboarding_mode=True)

@app.route('/onboarding/tiktok_connect')
@login_required
def onboarding_tiktok_connect(): # Rute khusus untuk onboarding TikTok Connect
    user = User.query.get(current_user.id)
    if not user:
        flash("User tidak ditemukan.", "danger")
        return redirect(url_for('welcome'))
    
    # Periksa apakah tiktok_username sudah diatur (harusnya sudah dari tahap sebelumnya)
    if not user.tiktok_username:
        flash('Silakan isi Nama Pengguna TikTok Anda terlebih dahulu.', 'warning')
        return redirect(url_for('onboarding_ai_settings'))
    
    cookies_present = bool(user.cookies_json and json.loads(user.cookies_json))
    
    qr_process_active = user.qr_process_active
    qr_generated_at = user.qr_generated_at
    
    qr_image_url = url_for('serve_qr_code', filename=f'qrcode_{user.id}.png')
    
    return render_template('tiktok_connect.html', 
                            cookies_present=cookies_present, 
                            tiktok_username=user.tiktok_username,
                            qr_image_url=qr_image_url,
                            qr_process_active=qr_process_active,
                            qr_generated_at=qr_generated_at.isoformat() if qr_generated_at else None,
                            onboarding_mode=True)

@app.route('/onboarding/trial_cta', methods=['GET', 'POST']) # BARU: Halaman CTA Trial
@login_required
def onboarding_trial_cta():
    user = current_user
    if not user:
        flash("User tidak ditemukan.", "danger")
        return redirect(url_for('welcome'))
    
    # Logika untuk halaman trial CTA
    # Ini akan diimplementasikan lebih detail di fase 7.5
    return render_template('onboarding_trial_cta.html', 
                           user=user, 
                           onboarding_mode=True,
                           has_used_free_trial=user.has_used_free_trial,
                           is_subscribed=user.is_subscribed,
                           onboarding_stage=user.onboarding_stage)


# ===============================================
# ROUTE WEBSITE (UI) - Rute Lama (Untuk Pengguna Berlangganan)
# ===============================================

@app.route('/tiktok_connect') # Menggunakan rute ini untuk pengguna berlangganan
@login_required
def tiktok_connect():
    user = User.query.get(current_user.id)
    if not user:
        flash("User tidak ditemukan.", "danger")
        return redirect(url_for('dashboard'))
    
    # Pengalihan sudah ditangani oleh middleware. Rute ini hanya untuk subscribed/admin.

    cookies_present = bool(user.cookies_json and json.loads(user.cookies_json))
    qr_process_active = user.qr_process_active
    qr_generated_at = user.qr_generated_at
    qr_image_url = url_for('serve_qr_code', filename=f'qrcode_{user.id}.png')
    
    return render_template('tiktok_connect.html', 
                            cookies_present=cookies_present, 
                            tiktok_username=user.tiktok_username,
                            qr_image_url=qr_image_url,
                            qr_process_active=qr_process_active,
                            qr_generated_at=qr_generated_at.isoformat() if qr_generated_at else None,
                            onboarding_mode=False) # Mode normal


@app.route('/ai_settings', methods=['GET', 'POST'])
@login_required
def ai_settings():
    form = AiSettingsForm()
    user = User.query.get(current_user.id)

    if not user:
        flash("User tidak ditemukan.", "danger")
        return redirect(url_for('dashboard'))

    if form.validate_on_submit():
        user.tiktok_username = form.tiktok_username.data
        user.creator_character_description = form.creator_character_description.data
        user.is_active = form.is_active.data
        
        try:
            daily_run_count_int = int(form.daily_run_count.data)
            if daily_run_count_int < 0:
                flash('Jumlah Jalan Per Hari tidak boleh negatif.', 'danger')
                return render_template('ai_settings.html', form=form, user_settings=user, onboarding_mode=False)
            user.daily_run_count = daily_run_count_int
        except ValueError:
            flash('Jumlah Jalan Per Hari harus berupa angka.', 'danger')
            return render_template('ai_settings.html', form=form, user_settings=user, onboarding_mode=False)
        
        try:
            db.session.add(user)
            db.session.commit()
            flash('Pengaturan AI berhasil diperbarui!', 'success')
            return redirect(url_for('ai_settings'))
        except Exception as e:
            db.session.rollback()
            flash(f'Gagal memperbarui pengaturan AI: {e}', 'danger')

    elif request.method == 'GET':
        form.tiktok_username.data = user.tiktok_username
        form.creator_character_description.data = user.creator_character_description
        form.is_active.data = user.is_active
        form.daily_run_count.data = str(user.daily_run_count)

    return render_template('ai_settings.html', form=form, user_settings=user, onboarding_mode=False)



@app.route('/tiktok_connect_legacy') # Rute lama untuk non-onboarding user
@login_required
def tiktok_connect_legacy(): # Rute ini bisa dihapus atau digunakan untuk mode normal jika perlu
    user = User.query.get(current_user.id)
    if not user:
        flash("User tidak ditemukan.", "danger")
        return redirect(url_for('dashboard'))
    
    # Hanya izinkan akses jika user sudah subscribed atau admin
    if not (user.is_subscribed or user.is_admin):
        flash("Akses ditolak. Silakan lengkapi alur onboarding atau berlangganan.", "danger")
        return redirect(url_for('dashboard'))

    # ... (logika sama seperti tiktok_connect sebelumnya, tapi tanpa cek tiktok_username awal) ...
    cookies_present = bool(user.cookies_json and json.loads(user.cookies_json))
    qr_process_active = user.qr_process_active
    qr_generated_at = user.qr_generated_at
    qr_image_url = url_for('serve_qr_code', filename=f'qrcode_{user.id}.png')
    
    return render_template('tiktok_connect.html', 
                            cookies_present=cookies_present, 
                            tiktok_username=user.tiktok_username,
                            qr_image_url=qr_image_url,
                            qr_process_active=qr_process_active,
                            qr_generated_at=qr_generated_at.isoformat() if qr_generated_at else None,
                            onboarding_mode=False) # Mode normal

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
    user = current_user # Mengambil user dari current_user
    is_subscribed = user.is_subscribed # Mengambil status langganan dari user
    subscription_end_date = None # Akan diisi dari model User jika ada
    
    # Contoh riwayat transaksi (dummy data)
    transaction_history = []

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

@app.route('/api/trigger_qr_login', methods=['POST'])
@login_required
def api_trigger_qr_login():
    user = User.query.get(current_user.id)
    if not user:
        return jsonify({"message": "User tidak ditemukan."}), 404
    
    # HANYA izinkan trigger QR jika user dalam tahap onboarding TIKTOK_CONNECT_PENDING
    # atau sudah subscribed (untuk re-connect)
    if not (user.onboarding_stage == 'TIKTOK_CONNECT_PENDING' or user.is_subscribed or user.is_admin):
        return jsonify({"message": "Akses ditolak. Tahap onboarding tidak sesuai atau belum berlangganan."}), 403

    try:
        user.qr_process_active = True
        user.qr_generated_at = None
        user.cookies_json = json.dumps([])

        db.session.add(user)
        db.session.commit()

        enqueue_qr_login_task(user.id)

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
        "cookies_json": user.cookies_json,
        "qr_process_active": user.qr_process_active,
        "qr_generated_at": user.qr_generated_at.isoformat() if user.qr_generated_at else None,
        "onboarding_stage": user.onboarding_stage, # BARU: Kirim tahap onboarding
        "has_used_free_trial": user.has_used_free_trial, # BARU: Kirim status free trial
        "is_subscribed": user.is_subscribed # BARU: Kirim status langganan
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
        
        # BARU: Jika login TikTok berhasil dan user dalam tahap TIKTOK_CONNECT_PENDING, pindahkan ke TRIAL_CTA
        if user.onboarding_stage == 'TIKTOK_CONNECT_PENDING':
            user.onboarding_stage = 'TRIAL_CTA'
            flash('Koneksi TikTok berhasil! Sekarang jalankan uji coba bot komentar Anda.', 'success')
        
        
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

@app.route('/api/users/<int:user_id>/update_comment_run_status', methods=['PUT'])
def api_update_user_comment_run_status(user_id):
    data = request.get_json()
    if not data:
        return jsonify({"message": "Data diperlukan."}), 400

    last_comment_run_at_str = data.get('last_comment_run_at')
    comment_runs_today = data.get('comment_runs_today')
    onboarding_stage = data.get('onboarding_stage')

    if comment_runs_today is None:
        return jsonify({"message": "comment_runs_today diperlukan."}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "User tidak ditemukan."}), 404

    try:
        if last_comment_run_at_str:
            user.last_comment_run_at = datetime.fromisoformat(last_comment_run_at_str)
        else:
            user.last_comment_run_at = None
        user.comment_runs_today = comment_runs_today
        
        if onboarding_stage:
            user.onboarding_stage = onboarding_stage

        db.session.commit()
        return jsonify({"message": "Status run komentar user berhasil diperbarui."}), 200
    except Exception as e:
        db.session.rollback()
        print(f"ERROR: Gagal memperbarui status run komentar user {user_id}: {e}")
        return jsonify({"message": f"Gagal memperbarui status run komentar: {e}"}), 500

@app.route('/api/onboarding/trial_bot_completed/<int:user_id>', methods=['PUT'])
def api_onboarding_trial_bot_completed(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "User not found."}), 404
    
    try:
        if user.onboarding_stage == 'TRIAL_RUNNING':
            user.onboarding_stage = 'TRIAL_COMPLETED'
            db.session.commit()
            print(f"[{datetime.now()}] API: Onboarding stage untuk user {user_id} diatur ke TRIAL_COMPLETED.")
            return jsonify({"message": "Onboarding stage updated to TRIAL_COMPLETED."}), 200
        else:
            return jsonify({"message": "User not in TRIAL_RUNNING stage."}), 400
    except Exception as e:
        db.session.rollback()
        print(f"[{datetime.now()}] API ERROR: Gagal memperbarui onboarding stage ke TRIAL_COMPLETED untuk user {user_id}: {e}")
        return jsonify({"message": f"Error updating onboarding stage: {e}"}), 500

@app.route('/api/onboarding/trigger_trial_bot', methods=['POST'])
@login_required
def api_onboarding_trigger_trial_bot():
    user = current_user
    if not user:
        return jsonify({"message": "User tidak ditemukan."}), 404

    # Periksa kondisi untuk menjalankan uji coba
    if user.has_used_free_trial:
        return jsonify({"message": "Anda sudah menggunakan uji coba gratis."}), 403
    if not user.tiktok_username:
        return jsonify({"message": "Nama pengguna TikTok belum diatur."}), 400
    if not user.cookies_json or not json.loads(user.cookies_json):
        return jsonify({"message": "Akun TikTok belum terhubung."}), 400
    if user.onboarding_stage not in ['TRIAL_CTA', 'TRIAL_COMPLETED']: # Boleh trigger dari TRIAL_COMPLETED jika user belum subscribe dan ingin re-run
        return jsonify({"message": "Tahap onboarding tidak sesuai untuk menjalankan uji coba."}), 403

    try:
        user.has_used_free_trial = True # Tandai sudah menggunakan uji coba
        user.onboarding_stage = 'TRIAL_RUNNING' # Ubah status ke bot sedang berjalan
        db.session.commit()

        # Antrekan tugas bot komentar
        # Untuk uji coba, kita bisa menggunakan daily_run_count=1 atau nilai default
        enqueue_comment_processing_task(user.id)

        return jsonify({"message": "Uji coba bot komentar berhasil dimulai!"}), 200
    except Exception as e:
        db.session.rollback()
        print(f"[{datetime.now()}] API ERROR: Gagal memicu uji coba bot untuk user {user.id}: {e}")
        return jsonify({"message": f"Gagal memicu uji coba bot: {e}"}), 500

# BARU: API Endpoint untuk simulasi langganan
@app.route('/api/onboarding/subscribe', methods=['POST'])
@login_required
def api_onboarding_subscribe():
    user = current_user
    if not user:
        return jsonify({"message": "User tidak ditemukan."}), 404

    if user.is_subscribed:
        return jsonify({"message": "Anda sudah berlangganan."}), 400

    try:
        user.is_subscribed = True
        user.onboarding_stage = 'SUBSCRIBED' # Pindah ke tahap subscribed
        user.is_active = True # Aktifkan bot setelah berlangganan
        # Set daily_run_count ke default jika belum diset atau sesuaikan
        if user.daily_run_count < 1: 
            user.daily_run_count = 1 

        db.session.commit()
        flash('Selamat! Anda berhasil berlangganan. Selamat datang di Dashboard!', 'success')
        return jsonify({"message": "Berlangganan berhasil."}), 200
    except Exception as e:
        db.session.rollback()
        print(f"[{datetime.now()}] API ERROR: Gagal memproses langganan untuk user {user.id}: {e}")
        return jsonify({"message": f"Gagal berlangganan: {e}"}), 500

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
    # ... (logika ini akan diubah saat kita mengimplementasikan scheduler)
    """
    Mengembalikan daftar user ID yang aktif dan perlu diproses oleh bot worker.
    Membutuhkan API Key.
    """
    try:
        current_time = datetime.now()
        
        # Ambil semua user yang aktif DAN memiliki cookies DAN tiktok_username
        # Serta bukan dalam tahap onboarding QR atau Trial Running
        active_users = User.query.filter(
            User.is_active == True,
            User.cookies_json.isnot(None),
            User.tiktok_username.isnot(None),
            User.onboarding_stage.notin(['TIKTOK_CONNECT_PENDING', 'TRIAL_RUNNING']) # Tidak proses user yang lagi QR/Trial
        ).all()
        
        users_to_process = []
        for user in active_users:
            # ... existing logic ... (Ini akan direvisi saat implementasi scheduler)
            should_process = False
            
            # Logika penjadwalan sederhana (akan diganti oleh APScheduler nanti)
            # Untuk sementara, jika belum pernah run, atau sudah lebih dari X jam
            if not user.last_comment_run_at: # Menggunakan last_comment_run_at
                should_process = True
            elif user.daily_run_count > 0:
                interval_hours = 24 / user.daily_run_count
                next_run_time = user.last_comment_run_at + timedelta(hours=interval_hours)
                
                if current_time >= next_run_time:
                    should_process = True
            
            if should_process:
                users_to_process.append({
                    "user_id": user.id,
                    "tiktok_username": user.tiktok_username,
                    "last_comment_run_at": user.last_comment_run_at.isoformat() if user.last_comment_run_at else None,
                    "next_run_estimate": (user.last_comment_run_at + timedelta(hours=24 / user.daily_run_count)).isoformat() if user.last_comment_run_at and user.daily_run_count > 0 else "N/A"
                })

        return jsonify({"users": users_to_process}), 200
    except Exception as e:
        print(f"ERROR: Gagal mengambil daftar user aktif untuk bot: {e}")
        return jsonify({"message": f"Error fetching active users for bot: {e}"}), 500

if __name__ == '__main__':
    print(f"Aplikasi Flask akan menggunakan database di: {db_path}") 
    app.run(debug=True, host='0.0.0.0', port=5000)