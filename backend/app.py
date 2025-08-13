from flask import Flask, request, jsonify # Pastikan jsonify ada
from flask_cors import CORS
from datetime import datetime, timedelta
import threading # Tambahkan import ini

from models import db, User, CreatorSettings

# Import fungsi bot yang sudah kita buat
from akses_komen.bot import run_tiktok_bot

app = Flask(__name__)
# ... existing app.config ...
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_secret_key' # Ganti dengan kunci rahasia yang kuat di produksi

CORS(app) # Enable CORS for all origins, adjust for production

db.init_app(app)

# ... existing routes (e.g., /register, /login) ...


@app.route('/api/creator_settings/<int:user_id>', methods=['GET', 'POST'])
def handle_creator_settings(user_id):
    # ... existing code ...
    pass # Anda bisa menyisipkan perubahan ini di atas atau di bawah route yang sudah ada


# BARU: Endpoint untuk memicu bot
@app.route('/api/run_bot/<int:creator_id>', methods=['POST'])
def trigger_bot_run(creator_id):
    creator = CreatorSettings.query.get(creator_id)
    if not creator:
        return jsonify({"message": f"Creator with ID {creator_id} not found."}), 404

    # Periksa apakah bot baru saja dijalankan atau tidak aktif
    # Anda bisa mengatur batas waktu (misal, 1 jam antar jalankan) dan status is_active di DB
    current_time = datetime.now()
    if creator.last_run_at and (current_time - creator.last_run_at) < timedelta(minutes=5): # Contoh: batasi per 5 menit
        return jsonify({"message": f"Bot for {creator.tiktok_username} was run recently. Please wait."}), 429 # Too Many Requests

    if not creator.is_active:
        return jsonify({"message": f"Bot for {creator.tiktok_username} is not active."}), 400

    # Jalankan bot di thread terpisah agar tidak memblokir API
    thread = threading.Thread(target=run_tiktok_bot, args=(creator_id,))
    thread.start()

    return jsonify({"message": f"Bot for {creator.tiktok_username} started successfully in background.", "creator_id": creator_id}), 200

# ... existing if __name__ == '__main__': block ...
if __name__ == '__main__':
    with app.app_context():
        db.create_all() # Pastikan semua tabel dibuat jika belum ada
    app.run(debug=True, host='0.0.0.0', port=5000)
