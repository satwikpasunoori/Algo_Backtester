import multiprocessing
multiprocessing.freeze_support()
#!/usr/bin/env python3
"""
ALGO MACHINE — Main Entry Point
Starts the FastAPI server with the full dashboard.
"""

import os
import sys
import subprocess

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

PORT = int(os.getenv("PORT", 8000))
HOST = os.getenv("HOST", "0.0.0.0")


def main():
    print("""
╔══════════════════════════════════════════════════════════╗
║          ALGO MACHINE — Strategy Discovery Platform      ║
║          Powered by Dhan API + Python + FastAPI          ║
╠══════════════════════════════════════════════════════════╣
║  Dashboard → http://localhost:{port}                      ║
║  API Docs  → http://localhost:{port}/docs                 ║
╚══════════════════════════════════════════════════════════╝
    """.format(port=PORT))

    # Check .env
    if not os.path.exists('.env'):
        print("[WARN] .env file not found. Copying from .env.example...")
        if os.path.exists('.env.example'):
            import shutil
            shutil.copy('.env.example', '.env')
            print("[INFO] Created .env from template. Add your Dhan credentials.")
        else:
            print("[WARN] No .env.example either. Synthetic data will be used.")

    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    main()
