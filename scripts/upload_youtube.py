#!/usr/bin/env python3
"""
upload_youtube.py
Upload video ke YouTube menggunakan YouTube Data API v3.
Menggunakan OAuth2 refresh token yang disimpan di GitHub Secrets.

Setup awal (sekali saja, dari komputer lokal):
  Lihat docs/YOUTUBE_OAUTH_SETUP.md
"""

import argparse
import json
import os
import sys
import time

import google.oauth2.credentials
import googleapiclient.discovery
import googleapiclient.errors
import googleapiclient.http


# ── OAuth2 helper ─────────────────────────────────────────────────────────────

def build_youtube_client():
    """Build YouTube API client dari environment variables (GitHub Secrets)."""
    client_id     = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print("❌ Missing YouTube credentials!")
        print("   Set secrets: YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN")
        sys.exit(1)

    credentials = google.oauth2.credentials.Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )

    return googleapiclient.discovery.build(
        "youtube", "v3",
        credentials=credentials,
        cache_discovery=False,
    )


# ── Upload ─────────────────────────────────────────────────────────────────────

def upload_video(youtube, video_path: str, metadata: dict) -> str:
    """Upload video ke YouTube. Return video ID jika sukses."""
    body = {
        "snippet": {
            "title":       metadata["title"],
            "description": metadata["description"],
            "tags":        metadata.get("tags", []),
            "categoryId":  metadata.get("category_id", "10"),
            "defaultLanguage": metadata.get("language", "en"),
        },
        "status": {
            "privacyStatus":  metadata.get("privacy", "public"),
            "madeForKids":    metadata.get("made_for_kids", False),
            "selfDeclaredMadeForKids": metadata.get("made_for_kids", False),
        },
    }

    media = googleapiclient.http.MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024 * 8,  # 8 MB chunks
    )

    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media,
    )

    print(f"📤 Uploading: {os.path.basename(video_path)}")
    print(f"   Size: {os.path.getsize(video_path) / (1024 * 1024):.1f} MB")
    print(f"   Title: {body['snippet']['title']}")

    response = None
    retry = 0
    max_retries = 5

    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                print(f"   Upload progress: {pct}%", end="\r")
        except googleapiclient.errors.HttpError as e:
            if e.resp.status in [500, 502, 503, 504] and retry < max_retries:
                retry += 1
                wait = 2 ** retry
                print(f"\n   ⚠️  HTTP {e.resp.status}, retry {retry}/{max_retries} in {wait}s...")
                time.sleep(wait)
            else:
                raise
        except Exception as e:
            if retry < max_retries:
                retry += 1
                wait = 2 ** retry
                print(f"\n   ⚠️  Error: {e}, retry {retry}/{max_retries} in {wait}s...")
                time.sleep(wait)
            else:
                raise

    video_id = response["id"]
    print(f"\n✅ Upload complete!")
    print(f"   Video ID: {video_id}")
    print(f"   URL: https://youtu.be/{video_id}")
    return video_id


def set_thumbnail(youtube, video_id: str, thumbnail_path: str):
    """Set custom thumbnail (opsional)."""
    if not os.path.exists(thumbnail_path):
        return
    try:
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=googleapiclient.http.MediaFileUpload(
                thumbnail_path, mimetype="image/jpeg"
            )
        ).execute()
        print(f"   🖼️  Thumbnail set: {thumbnail_path}")
    except Exception as e:
        print(f"   ⚠️  Thumbnail failed: {e}")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video",     type=str, required=True)
    parser.add_argument("--metadata",  type=str, required=True)
    parser.add_argument("--thumbnail", type=str, default=None)
    args = parser.parse_args()

    if not os.path.exists(args.video):
        print(f"❌ Video file not found: {args.video}")
        sys.exit(1)

    with open(args.metadata, encoding="utf-8") as f:
        metadata = json.load(f)

    youtube = build_youtube_client()
    video_id = upload_video(youtube, args.video, metadata)

    if args.thumbnail:
        set_thumbnail(youtube, video_id, args.thumbnail)

    # Simpan output untuk step berikutnya (opsional)
    result = {
        "video_id": video_id,
        "url": f"https://youtu.be/{video_id}",
        "title": metadata["title"],
    }
    print(f"\n📋 Result: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    main()
