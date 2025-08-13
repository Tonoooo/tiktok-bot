from flask import Flask, render_template, request, redirect, url_for, jsonify
from backend.models import db, User, CreatorSettings
import os

def create_app():
    app = Flask(__name__)
    # Konfigurasi database SQLite
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Inisialisasi db dengan aplikasi Flask
    db.init_app(app)

    # Pastikan database ada saat aplikasi dimulai
    with app.app_context():
        db.create_all() # Ini akan membuat tabel jika belum ada

    @app.route('/')
    def index():
        # Contoh rute sederhana
        return "TikTok Auto-Responder Backend is running!"

    # Contoh rute API untuk melihat semua creator settings
    @app.route('/api/creators', methods=['GET'])
    def get_creators():
        creators = CreatorSettings.query.all()
        creator_list = []
        for creator in creators:
            creator_list.append({
                'id': creator.id,
                'tiktok_username': creator.tiktok_username,
                'is_active': creator.is_active,
                'last_run_at': creator.last_run_at.isoformat() if creator.last_run_at else None,
                'daily_run_count': creator.daily_run_count
            })
        return jsonify(creator_list)

    # Di sini Anda bisa menambahkan rute lain untuk manajemen user/creator

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000)