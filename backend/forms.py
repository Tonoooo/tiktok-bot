from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, ValidationError
from backend.models import User # Menggunakan User dari models.py

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