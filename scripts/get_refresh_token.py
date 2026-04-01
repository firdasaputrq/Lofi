#!/usr/bin/env python3
"""
get_refresh_token.py
Jalankan ini SEKALI di komputer lokal untuk mendapatkan refresh token.
Token ini kemudian dimasukkan ke GitHub Secrets.

Usage:
  python3 scripts/get_refresh_token.py --client-secret client_secret.json
"""

import argparse
import json
import sys
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-secret", required=True,
                        help="Path ke file client_secret.json dari Google Cloud Console")
    args = parser.parse_args()

    flow = InstalledAppFlow.from_client_secrets_file(args.client_secret, SCOPES)
    credentials = flow.run_local_server(port=0)

    print("\n" + "=" * 60)
    print("✅ Berhasil! Masukkan nilai berikut ke GitHub Secrets:")
    print("=" * 60)
    print(f"\nYOUTUBE_CLIENT_ID={credentials.client_id}")
    print(f"YOUTUBE_CLIENT_SECRET={credentials.client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN={credentials.refresh_token}")
    print("\n" + "=" * 60)
    print("Lihat docs/YOUTUBE_OAUTH_SETUP.md untuk langkah selanjutnya.")


if __name__ == "__main__":
    main()
