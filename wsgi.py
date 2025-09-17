import sys
import os

# Tambahkan direktori proyek ke sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

# Impor objek `app` dari backend.app
from backend.app import app

# Ini adalah entry point untuk Gunicorn
if __name__ == "__main__":
    app.run()