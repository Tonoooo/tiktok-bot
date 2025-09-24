def run_tiktok_bot_task(user_id: int, is_trial_run: bool = False):
    # ... (kode inisialisasi dan pengambilan user_settings tetap sama) ...
    try:
        # ...
        # Hapus baris ini: cookies = json.loads(cookies_json)

        # =========================
        # OPSI PERAMBAN BARU DENGAN PROFIL
        # =========================
        user_profile_path = os.path.abspath(os.path.join(PROFILES_DIR, f'user_{user_id}'))
        print(f"Memuat profil peramban dari: {user_profile_path}")

        if not os.path.exists(user_profile_path):
            print(f"ERROR: Direktori profil untuk user {user_id} tidak ditemukan. Jalankan Bot QR terlebih dahulu.")
            return

        options = uc.ChromeOptions()
        # Anda BISA mencoba menjalankan bot komen dalam mode headless sekarang,
        # karena sesi sudah terotentikasi penuh.
        # options.add_argument('--headless')

        # Opsi lain untuk stabilitas
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--window-size=1280,800')

        driver = uc.Chrome(options=options, user_data_dir=user_profile_path)
        print("WebDriver berhasil diinisialisasi menggunakan profil yang ada.")

        target_url = f"https://www.tiktok.com/@{tiktok_username}"
        driver.get(target_url) # Langsung buka halaman profil
        print(f"Navigasi ke: {target_url}")
        time.sleep(5)

        # --- HAPUS SELURUH BLOK KODE "Muat cookies" ---
        # (Karena cookies sudah otomatis dimuat dari profil)

        # ... (sisa kode untuk refresh halaman, scroll, dan memproses video tetap sama) ...