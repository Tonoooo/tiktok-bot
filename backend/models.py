from flask_sqlalchemy import SQLAlchemy
# import Flask # Baris ini tidak lagi diperlukan di sini, cukup di app.py dan initialize_db.py
import json

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False) # BARU: Tambahkan kolom ini

    # BARU: Tambahkan relasi ke CreatorSettings
    creator_settings = db.relationship('CreatorSettings', backref='user', lazy=True, uselist=False)

    def __repr__(self):
        return f'<User {self.username}>'

class CreatorSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    
    # BARU: Tambahkan kolom user_id sebagai foreign key
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False) 
    
    tiktok_username = db.Column(db.String(120), unique=True, nullable=False)
    creator_character_description = db.Column(db.Text, nullable=True)
    gemini_api_key = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    daily_run_count = db.Column(db.Integer, default=0)
    processed_video_urls_json = db.Column(db.Text, default="[]")
    last_run_at = db.Column(db.DateTime, nullable=True)
    cookies_json = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<CreatorSettings {self.tiktok_username}>'