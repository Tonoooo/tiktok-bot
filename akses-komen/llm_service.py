import google.generativeai as genai
import os

# Konfigurasi API key
# Disarankan untuk menyimpan API key di variabel lingkungan (misal: GOOGLE_API_KEY)
# atau file konfigurasi terpisah, BUKAN LANGSUNG DI DALAM KODE.
# Namun, untuk demonstrasi, kita akan menempatkannya langsung di sini.
# GANTI 'YOUR_GEMINI_API_KEY' DENGAN KUNCI API ASLI ANDA!
API_KEY = os.getenv("GOOGLE_API_KEY", "AIzaSyDtIN6C60dm3-c3D3t2o0sYY293xktxe_U") 
genai.configure(api_key=API_KEY)

# Pilih model yang akan digunakan
# 'gemini-pro' cocok untuk tugas teks-ke-teks umum.
model = genai.GenerativeModel('gemini-2.0-flash')

def generate_ai_reply(video_transcript: str, original_comment: str, creator_description: str = "") -> str:
    """
    Menghasilkan balasan menggunakan model AI berdasarkan transkrip video, komentar asli, dan deskripsi creator.

    Args:
        video_transcript (str): Transkrip lengkap dari video.
        original_comment (str): Teks komentar yang ingin dibalas.
        creator_description (str): Deskripsi karakter creator (e.g., "pria, usia 20-an, tegas, suka humor").

    Returns:
        str: Balasan yang dihasilkan oleh AI.
    """
    # Tentukan persona creator berdasarkan input
    persona_instruction = f"Anda harus berbicara dengan persona seorang content creator yang {creator_description}." if creator_description else "Anda harus berbicara dengan persona seorang content creator yang ramah dan interaktif."

    prompt = f"""Anda adalah asisten AI yang membalas komentar di video TikTok. 
    {persona_instruction}
    Jawablah seolah-olah Anda adalah creatornya langsung.
    Buatlah balasan yang singkat, natural, dan relevan dengan konteks video dan komentar.
    Variasikan gaya bahasa dan frasa pembuka, hindari pengulangan seperti 'Wah, ...' atau frasa yang terlalu template.
    Hindari penggunaan panggilan 'Kak', 'Bapak', 'Ibu', atau panggilan formal lainnya. Hindari juga penggunaan emoji di dalam balasan Anda.

    Panduan Balasan:
    1.  **Komentar terkait produk/informasi yang kurang jelas di transkrip**: Jika komentar berkaitan langsung dengan produk yang dijual di video, atau membutuhkan informasi lebih lanjut yang tidak ada di transkrip, **prioritaskan untuk mengarahkan pengguna ke CTA (Call-to-Action)** seperti "cek keranjang kuning" atau "klik keranjang kuning". Balasan harus mendorong penjualan atau interaksi lebih lanjut.
    2.  **Komentar tidak terkait produk**: Jika komentar tidak berkaitan langsung dengan produk, balaslah secara umum, ramah, dan alami **tanpa menyelipkan CTA**. Tujuan utama adalah interaksi dan menjaga percakapan tetap natural.
    3.  **Komentar negatif/testimoni buruk/bertolak belakang**: Jika komentar menjelekkan produk, memberikan testimoni negatif, atau bertolak belakang dengan inti video, berikan balasan yang diplomatis, proaktif, atau menawarkan solusi. Contoh: "Terima kasih masukannya, Kak! Kami terus berusaha tingkatkan kualitas produk. Yuk, coba lagi atau bisa chat admin untuk info lebih lanjut." Jika tidak memungkinkan untuk menangani dengan baik (misalnya komentar yang terlalu agresif, spam, atau fitnah), maka balaslah dengan teks **[TIDAK_MEMBALAS]**.
    4.  **Komentar candaan/guyonan**: Jika komentar terdeteksi sebagai candaan atau guyonan, balaslah dengan teks **[TIDAK_MEMBALAS]**.
    5.  **Komentar tidak relevan/tidak dimengerti**: Jika komentar sama sekali tidak relevan dengan video atau tidak dapat dibalas dengan sopan dan relevan berdasarkan konteks, kembalikan teks **[TIDAK_MEMBALAS]**.

    Transkrip Video:
    ---
    {video_transcript}
    ---

    Komentar Asli: "{original_comment}"

    Balasan Anda (singkat, dibawah 150 karakter):"""

    try:
        response = model.generate_content(prompt)
        # Pastikan respons tidak kosong dan memiliki atribut 'text'
        if response and hasattr(response, 'text'):
            reply = response.text.strip()
            print(f"   -> AI berhasil menghasilkan balasan: \"{reply}\"")
            return reply
        else:
            print("   -> AI menghasilkan respons kosong atau tidak valid.")
            return "Maaf, saya tidak dapat membalas saat ini."
    except Exception as e:
        print(f"   -> ERROR SAAT MENGHASILKAN BALASAN AI: {e}")
        return "Maaf, terjadi masalah saat membalas. Silakan coba lagi nanti."

if __name__ == "__main__":
    # Contoh penggunaan (bisa dihapus setelah integrasi)
    contoh_transkrip = "Video ini membahas tentang cara cepat membuat kue bolu tanpa oven."
    contoh_komentar = "Wah, enak banget kuenya! Resepnya gimana kak?"
    
    balasan = generate_ai_reply(contoh_transkrip, contoh_komentar)
    print(f"\nBalasan AI untuk contoh: {balasan}")

    contoh_transkrip_2 = "Review film terbaru tentang petualangan di luar angkasa."
    contoh_komentar_2 = "Filmnya seru gak kak? Ada actionnya?"
    balasan_2 = generate_ai_reply(contoh_transkrip_2, contoh_komentar_2)
    print(f"\nBalasan AI untuk contoh 2: {balasan_2}")