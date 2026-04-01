#!/usr/bin/env python3
"""
get_refresh_token.py
Jalankan SEKALI di laptop untuk mendapat YouTube refresh token.
Setelah dapat, simpan ke GitHub Secrets.

Cara pakai:
  pip install google-auth-oauthlib
  python get_refresh_token.py
"""

import json
from google_auth_oauthlib.flow import InstalledAppFlow

# Ganti dengan client_id dan client_secret dari Google Cloud Console
CLIENT_ID = "GANTI_DENGAN_CLIENT_ID_KAMU"
CLIENT_SECRET = "GANTI_DENGAN_CLIENT_SECRET_KAMU"

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def main():
    client_config = {
        "installed": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=8080)

    print("\n" + "="*60)
    print("✅ BERHASIL! Simpan nilai ini ke GitHub Secrets:")
    print("="*60)
    print(f"\nYOUTUBE_CLIENT_ID:\n{CLIENT_ID}")
    print(f"\nYOUTUBE_CLIENT_SECRET:\n{CLIENT_SECRET}")
    print(f"\nYOUTUBE_REFRESH_TOKEN:\n{creds.refresh_token}")
    print("\n" + "="*60)
    print("Cara tambah ke GitHub Secrets:")
    print("Repo Settings → Secrets and variables → Actions → New repository secret")
    print("="*60)

if __name__ == "__main__":
    main()
