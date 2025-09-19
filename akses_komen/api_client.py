import requests
import json
import os
from typing import Optional, Dict, Any
from datetime import datetime

class APIClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.headers = {
            'X-API-KEY': self.api_key,
            'Content-Type': 'application/json'
        }
        print(f"APIClient diinisialisasi dengan base_url: {self.base_url}")
        
    def _make_request(self, method, endpoint, data=None, params: Optional[Dict] = None, json_data: Optional[Dict] = None, files: Optional[Dict] = None) -> Dict:
        url = f"{self.base_url}{endpoint}"
        # Inisialisasi 'response' ke None di sini
        response = None
        
        # Untuk file uploads, kita tidak set Content-Type secara manual
        headers = {"X-API-Key": self.api_key}
        if not files:
            headers['Content-Type'] = 'application/json'

        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, params=params, timeout=30)
            elif method == 'POST':
                # 'data' untuk form-data, 'json_data' untuk application/json
                response = requests.post(url, headers=headers, data=data, json=json_data, files=files, timeout=30)
            elif method == 'PUT':
                response = requests.put(url, headers=headers, json=data, timeout=30)
            else:
                raise ValueError("Metode HTTP tidak didukung.")
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            error_message = f"ERROR APIClient: Gagal terhubung ke VPS API atau ada masalah respons: {e}"
            # Cek 'response' di sini
            if response is not None:
                try:
                    error_data = response.json()
                    error_message += f" - Detail: {error_data.get('message', str(error_data))}"
                except json.JSONDecodeError:
                    error_message += f" - Teks Respons: {response.text}"
            raise Exception(error_message)

        
        
    def get_user_settings(self, user_id: int):
        endpoint = f"/api/users/{user_id}"
        return self._make_request('GET', endpoint)
    
    def update_user_last_comment_run(self, user_id: int, last_run_at: datetime, comment_runs_today: int, onboarding_stage: str = None): # BARU: Tambah onboarding_stage
        """
        Memperbarui timestamp terakhir bot komentar dijalankan dan hitungan run harian untuk user.
        Juga dapat memperbarui onboarding_stage jika disediakan.
        """
        endpoint = f"/api/users/{user_id}/update_comment_run_status"
        data = {
            "last_comment_run_at": last_run_at.isoformat() if last_run_at else None,
            "comment_runs_today": comment_runs_today
        }
        if onboarding_stage: # BARU: Tambahkan ke payload jika ada
            data['onboarding_stage'] = onboarding_stage
        return self._make_request('PUT', endpoint, data)
    
    def update_onboarding_stage_after_trial(self, user_id: int):
        endpoint = f"/api/onboarding/trial_bot_completed/{user_id}"
        return self._make_request('PUT', endpoint)
    
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