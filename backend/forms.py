from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, ValidationError
from backend.models import User # Menggunakan User dari models.py
from flask_login import current_user 
from backend.models import User

class RegistrationForm(FlaskForm):
    username = StringField('Nama Pengguna', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Kata Sandi', validators=[DataRequired()])
    confirm_password = PasswordField('Konfirmasi Kata Sandi', 
                                     validators=[DataRequired(), EqualTo('password', message='Kata sandi harus cocok')])
    submit = SubmitField('Daftar')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('Nama pengguna sudah ada. Silakan pilih nama lain.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('Alamat email sudah terdaftar. Silakan gunakan yang lain atau masuk.')

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Kata Sandi', validators=[DataRequired()])
    remember_me = BooleanField('Ingat Saya')
    submit = SubmitField('Masuk')
    
class AiSettingsForm(FlaskForm):
    tiktok_username = StringField('Nama Pengguna TikTok', description='Nama pengguna TikTok (tanpa "@") yang akan dipantau oleh AI. Harus unik untuk setiap klien.')
    creator_character_description = StringField('Deskripsi Karakter Kreator', description='Contoh: "pria, usia 20-an, tegas, suka humor". AI akan meniru karakter ini saat membalas.')
    is_active = BooleanField('Aktifkan AI Auto-Responder', description='Centang untuk mengaktifkan AI agar memproses komentar secara otomatis.')
    daily_run_count = StringField('Jumlah Jalan Per Hari', description='Berapa kali AI akan memeriksa dan membalas komentar dalam sehari. Misal: "3" untuk 3 kali sehari.')
    submit = SubmitField('Simpan Pengaturan AI')

    def validate_tiktok_username(self, tiktok_username):
        if tiktok_username.data: # Hanya validasi jika ada input
            # Periksa apakah tiktok_username sudah digunakan oleh user lain
            user = User.query.filter_by(tiktok_username=tiktok_username.data).first()
            if user and user.id != current_user.id: # current_user harus diimpor di app.py
                raise ValidationError('Nama pengguna TikTok ini sudah terdaftar oleh klien lain. Harap masukkan nama unik.')