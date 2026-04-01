#!/usr/bin/env python3
"""
upload_youtube.py
Upload video ke YouTube menggunakan OAuth2 refresh token.
"""

import os
import sys
import json
import time
import argparse
import requests

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install",
                    "google-api-python-client", "google-auth-httplib2",
                    "google-auth-oauthlib", "--quiet"])
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request


def get_credentials():
    """Buat credentials dari env vars (refresh token flow)."""
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        raise ValueError(
            "Missing environment variables: YOUTUBE_CLIENT_ID, "
            "YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN"
        )

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/youtube.upload"]
    )

    # Refresh token untuk mendapat access token
    creds.refresh(Request())
    print(f"[upload] Credentials valid: {creds.valid}")
    return creds


def upload_video(video_path: str, title: str, description: str, tags: list):
    """Upload video ke YouTube dengan retry logic."""
    print(f"[upload] File: {video_path}")
    print(f"[upload] Title: {title}")
    print(f"[upload] Tags: {tags[:5]}...")

    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title[:100],  # YouTube max 100 chars
            "description": description[:5000],  # YouTube max 5000 chars
            "tags": tags[:30],  # YouTube max 30 tags
            "categoryId": "10",  # Music category
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "madeForKids": False,
        }
    }

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024  # 10MB chunks
    )

    # Upload dengan retry
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"[upload] Attempt {attempt + 1}/{max_retries}...")
            request = youtube.videos().insert(
                part=",".join(body.keys()),
                body=body,
                media_body=media
            )

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    print(f"[upload] Progress: {progress}%")

            video_id = response["id"]
            video_url = f"https://youtu.be/{video_id}"
            print(f"[upload] ✅ SUKSES! Video ID: {video_id}")
            print(f"[upload] URL: {video_url}")
            return video_id

        except Exception as e:
            print(f"[upload] Error attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                wait_time = 30 * (attempt + 1)
                print(f"[upload] Retry dalam {wait_time} detik...")
                time.sleep(wait_time)
            else:
                raise

    raise Exception("Upload gagal setelah semua retry")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, help="Path ke file video MP4")
    parser.add_argument("--title", required=True, help="Judul video YouTube")
    parser.add_argument("--description", default="", help="Deskripsi video")
    parser.add_argument("--tags", default="lofi,study music,chill", help="Tags dipisah koma")
    args = parser.parse_args()

    tags_list = [t.strip() for t in args.tags.split(",") if t.strip()]

    # Cek file ada
    if not os.path.exists(args.video):
        print(f"[upload] ERROR: File tidak ditemukan: {args.video}")
        sys.exit(1)

    file_size_mb = os.path.getsize(args.video) / 1024 / 1024
    print(f"[upload] File size: {file_size_mb:.1f} MB")

    if file_size_mb < 1:
        print("[upload] ERROR: File terlalu kecil, kemungkinan kosong")
        sys.exit(1)

    video_id = upload_video(args.video, args.title, args.description, tags_list)
    print(f"[upload] Done! https://youtu.be/{video_id}")


if __name__ == "__main__":
    main()
