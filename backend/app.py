from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta
import threading 

from models import db, User, CreatorSettings

from akses_komen.bot import run_tiktok_bot_task # UNCOMMENT INI

app = Flask(__name__)
# ... existing app.config ...
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_secret_key' # Ganti dengan kunci rahasia yang kuat di produksi

CORS(app) 

db.init_app(app)

# Pastikan Anda telah menjalankan initialize_db.py TERPISAH sebelum menjalankan app ini.
# db.create_all() # Jangan panggil di sini setiap kali app dimulai, hanya di initialize_db.py

@app.route('/')
def index():
    return jsonify({"message": "TikTok Auto-Responder Backend API is running!"})

# Rute placeholder, akan diisi nanti
@app.route('/api/creator_settings/<int:user_id>', methods=['GET', 'POST'])
def handle_creator_settings(user_id):
    # Ini akan menjadi rute untuk mengelola pengaturan creator
    return jsonify({"message": f"Creator settings for user {user_id}"})


# BARU: Endpoint untuk memicu bot
@app.route('/api/run_bot/<int:creator_id>', methods=['POST'])
def trigger_bot_run(creator_id):
    creator = CreatorSettings.query.get(creator_id)
    if not creator:
        return jsonify({"message": f"Creator with ID {creator_id} not found."}), 404

    # Mencegah bot berjalan jika sudah terlalu sering dalam sehari (opsional, bisa diatur nanti)
    # if creator.last_run_at and (datetime.now() - creator.last_run_at).days == 0 and creator.daily_run_count >= 3:
    #     return jsonify({"message": f"Bot for creator {creator_id} has already run 3 times today."}), 429

    print(f"Memicu bot untuk creator ID: {creator_id} di thread terpisah.")
    
    # Jalankan bot dalam thread terpisah
    bot_thread = threading.Thread(target=run_tiktok_bot_task, args=(creator_id,))
    bot_thread.start()

    return jsonify({"message": f"Bot task started for creator ID {creator_id}. Check console for progress."}), 202


if __name__ == '__main__':
    # db.create_all() # Ini dipanggil di initialize_db.py, tidak perlu di sini setiap kali
    app.run(debug=True, host='0.0.0.0', port=5000)
