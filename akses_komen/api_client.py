import requests
import json
from typing import Dict, Any, Optional

class APIClient:
    def __init__(self, base_url: str, api_key: str):
        """
        Menginisialisasi APIClient untuk berkomunikasi dengan Flask API.
        
        Args:
            base_url (str): URL dasar API Flask (contoh: "http://103.52.114.253:5000").
            api_key (str): Kunci API untuk otentikasi bot ke Flask API.
        """
        self.base_url = base_url
        self.api_key = api_key
        # Kita akan menggunakan API Key di header untuk otentikasi sederhana
        self.headers = {"X-API-Key": self.api_key, "Content-Type": "application/json"}
        print(f"APIClient diinisialisasi dengan base_url: {base_url}")

    def _make_request(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Any:
        """
        Membuat permintaan HTTP umum ke API.
        """
        url = f"{self.base_url}/{endpoint}"
        try:
            if method == "GET":
                response = requests.get(url, headers=self.headers, params=params)
            elif method == "POST":
                response = requests.post(url, headers=self.headers, json=data)
            elif method == "PUT": # Akan berguna jika kita perlu mengupdate record
                response = requests.put(url, headers=self.headers, json=data)
            else:
                raise ValueError(f"Metode HTTP {method} tidak didukung.")

            response.raise_for_status() # Akan menimbulkan HTTPError untuk respons 4xx atau 5xx
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"ERROR API Request Gagal: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Kode status respons: {e.response.status_code}")
                print(f"Body respons: {e.response.text}")
            raise # Lemparkan kembali exception setelah mencetak detailnya

    def get_user_settings(self, user_id: int) -> Dict[str, Any]:
        """
        Mengambil pengaturan user dari API Flask.
        """
        print(f"Mengambil pengaturan user {user_id} dari API...")
        return self._make_request("GET", f"api/users/{user_id}")

    def update_user_cookies(self, user_id: int, cookies_json: str) -> Dict[str, Any]:
        """
        Memperbarui cookies login TikTok untuk user tertentu melalui API Flask.
        """
        print(f"Memperbarui cookies untuk user {user_id} melalui API...")
        return self._make_request("POST", f"api/users/{user_id}/cookies", {"cookies_json": cookies_json})

    def get_processed_video(self, user_id: int, video_url: str) -> Optional[Dict[str, Any]]:
        """
        Mengambil detail video yang sudah diproses (termasuk transkrip) dari API Flask.
        Mengembalikan None jika video tidak ditemukan.
        """
        print(f"Mencari transkrip video untuk user {user_id} dan URL: {video_url} dari API...")
        try:
            # Karena video_url bisa panjang, kita kirim sebagai query parameter
            # Flask API perlu diatur untuk menerima ini
            return self._make_request("GET", f"api/processed_videos/by_url", params={"user_id": user_id, "video_url": video_url})
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                print(f"Transkrip video untuk {video_url} tidak ditemukan di API (404).")
                return None
            raise # Lemparkan error lain yang tidak 404

    def save_processed_video(self, user_id: int, video_url: str, transcript: str) -> Dict[str, Any]:
        """
        Menyimpan data video yang sudah diproses (termasuk transkrip) ke API Flask.
        """
        print(f"Menyimpan transkrip video untuk user {user_id} dan URL: {video_url} ke API...")
        data = {
            "user_id": user_id,
            "video_url": video_url,
            "transcript": transcript
        }
        return self._make_request("POST", "api/processed_videos", data)

    # Metode lain seperti untuk melaporkan komentar yang dibalas bisa ditambahkan di sini.