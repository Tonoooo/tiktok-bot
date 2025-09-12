from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.sqlite import JSON # Tidak perlu lagi kalau processed_video_urls_json dihapus
from datetime import datetime
from flask_login import UserMixin # BARU: Import UserMixin

db = SQLAlchemy()

# PERUBAHAN: Model User mewarisi UserMixin
class User(db.Model, UserMixin): # Tambahkan UserMixin di sini
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False) 
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False) # BARU: Kolom created_at

    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    # Kolom yang digabungkan dari CreatorSettings
    tiktok_username = db.Column(db.String(120), unique=True, nullable=True) # Unique, tapi bisa Nullable untuk registrasi awal
    creator_character_description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    daily_run_count = db.Column(db.Integer, default=0)
    last_run_at = db.Column(db.DateTime, nullable=True)
    cookies_json = db.Column(db.Text, nullable=True) # Akan menyimpan cookies TikTok

    # Relasi ke model ProcessedVideo yang baru
    processed_videos = db.relationship('ProcessedVideo', backref='user', lazy=True)

    def __repr__(self):
        return f'<User {self.username}>'

    # Metode yang diperlukan oleh Flask-Login (UserMixin sudah menyediakannya, tapi bagus untuk tahu)
    # def is_authenticated(self):
    #     return True
    # def is_active(self):
    #     return True
    # def is_anonymous(self):
    #     return False
    # def get_id(self):
    #     return str(self.id)

class ProcessedVideo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    video_url = db.Column(db.String(255), unique=True, nullable=False) # URL video
    transcript = db.Column(db.Text, nullable=True) # Transkrip video
    processed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False) # Kapan terakhir diproses

    processed_comments = db.relationship('ProcessedComment', backref=db.backref('video', lazy=True, cascade="all, delete-orphan"))

    def __repr__(self):
        return f'<ProcessedVideo {self.video_url}>'
    
class ProcessedComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    processed_video_id = db.Column(db.Integer, db.ForeignKey('processed_video.id'), nullable=False)
    
    # ID komentar asli dari TikTok (jika tersedia dan dapat diidentifikasi)
    tiktok_comment_id = db.Column(db.String(255), nullable=True) 
    
    comment_text = db.Column(db.Text, nullable=False)
    reply_text = db.Column(db.Text, nullable=True) # Balasan dari AI, atau [TIDAK_MEMBALAS]
    
    # Kapan komentar ini diproses dan dibalas
    processed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Flag untuk menunjukkan apakah balasan benar-benar diposting
    is_replied = db.Column(db.Boolean, default=False, nullable=False) 
    
    # Opsional: Untuk menyimpan keputusan mentah LLM jika diperlukan untuk debugging
    llm_raw_decision = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<ProcessedComment {self.id} for Video {self.processed_video_id}>'