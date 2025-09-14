import requests
import json
import os
from typing import Optional, Dict, Any
class APIClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        print(f"APIClient diinisialisasi dengan base_url: {self.base_url}")
    def _make_request(self, method: str, endpoint: str, params: Optional[Dict] = None, json_data: Optional[Dict] = None, files: Optional[Dict] = None) -> Dict:
        url = f"{self.base_url}{endpoint}"
        headers = {"X-API-Key": self.api_key}
        
        try:
            if method == "GET":
                response = requests.get(url, headers=headers, params=params, timeout=30)
            elif method == "POST":
                if files: # Jika ada file untuk diupload
                    response = requests.post(url, headers=headers, params=params, files=files, timeout=30)
                else: # Jika hanya data JSON
                    response = requests.post(url, headers=headers, params=params, json=json_data, timeout=30) # PERBAIKAN: Gunakan json=json_data
            # ... (metode PUT, DELETE jika ada)
            else:
                raise ValueError(f"Metode HTTP tidak didukung: {method}")
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            return response.json()
        except requests.exceptions.Timeout:
            print(f"ERROR: Permintaan API ke {url} timeout setelah 30 detik.")
            raise
        except requests.exceptions.RequestException as e:
            print(f"ERROR: Kesalahan API saat meminta {url}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response content: {e.response.text}")
            raise
    def get_user_settings(self, user_id: int) -> Optional[Dict]:
        endpoint = f"/api/users/{user_id}"
        try:
            return self._make_request("GET", endpoint)
        except Exception:
            return None
    def update_user_cookies(self, user_id: int, cookies_json: str):
        endpoint = f"/api/users/{user_id}/cookies"
        data = {"cookies_json": cookies_json}
        return self._make_request("POST", endpoint, json_data=data) # PERBAIKAN: Gunakan json_data=data
    def update_user_last_run_api(self, user_id: int):
        endpoint = f"/api/users/{user_id}/last_run"
        # Tidak ada data body yang diperlukan untuk endpoint ini, hanya pemicu POST
        return self._make_request("POST", endpoint) # PERBAIKAN: Hapus json_data={} jika tidak ada body
    def get_processed_video(self, user_id: int, video_url: str) -> Optional[Dict]:
        endpoint = "/api/processed_videos/by_url"
        params = {"user_id": user_id, "video_url": video_url}
        try:
            return self._make_request("GET", endpoint, params=params)
        except Exception:
            return None
    def save_processed_video(self, user_id: int, video_url: str, transcript: str) -> Dict:
        endpoint = "/api/processed_videos"
        data = {
            "user_id": user_id,
            "video_url": video_url,
            "transcript": transcript
        }
        return self._make_request("POST", endpoint, json_data=data) # PERBAIKAN: Gunakan json_data=data
    def save_processed_comment(self, processed_video_id: int, tiktok_comment_id: Optional[str], comment_text: str, reply_text: Optional[str], is_replied: bool, llm_raw_decision: Optional[str]):
        endpoint = f"/api/processed_videos/{processed_video_id}/comments"
        data = {
            "tiktok_comment_id": tiktok_comment_id,
            "comment_text": comment_text,
            "reply_text": reply_text,
            "is_replied": is_replied,
            "llm_raw_decision": llm_raw_decision
        }
        return self._make_request("POST", endpoint, json_data=data) # PERBAIKAN: Gunakan json_data=data
    def update_user_qr_status(self, user_id: int, qr_process_active: bool, qr_generated_at: Optional[str] = None):
        endpoint = f"/api/users/{user_id}/update_qr_status"
        data = {
            "user_id": user_id,
            "qr_process_active": qr_process_active,
            "qr_generated_at": qr_generated_at
        }
        return self._make_request("POST", endpoint, json_data=data) # PERBAIKAN: Gunakan json_data=data
    def update_user_cookies_and_qr_status(self, user_id: int, cookies_json: str):
        endpoint = f"/api/users/{user_id}/update_cookies_status"
        data = {
            "user_id": user_id,
            "cookies_json": cookies_json
        }
        return self._make_request("POST", endpoint, json_data=data) # PERBAIKAN: Gunakan json_data=data
    
    def upload_qr_image_to_vps(self, user_id: int, image_path: str):
        endpoint = f"/api/upload_qr_image/{user_id}"
        try:
            with open(image_path, 'rb') as f:
                # 'qr_image' adalah nama field yang diharapkan oleh Flask API (backend/app.py)
                files = {'qr_image': (os.path.basename(image_path), f, 'image/png')}
                response = self._make_request("POST", endpoint, files=files) # PERBAIKAN: Gunakan files=files
                return response
        except Exception as e:
            print(f"ERROR: Gagal mengupload gambar QR code untuk user {user_id} ke VPS: {e}")
            raise # Re-raise exception agar bisa ditangani di qr_login_service
    
    def get_active_users_for_bot(self) -> Dict:
        endpoint = "/api/active_users_for_bot"
        return self._make_request("GET", endpoint)