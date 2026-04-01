#!/usr/bin/env python3
"""
generate_audio.py
Mengambil parameter musik dari Lofi Flask API, lalu merender audio
menggunakan Node.js headless renderer (Tone.js via OfflineAudioContext).
Menghasilkan WAV penuh 1 jam dengan beberapa track berbeda disambung.
"""

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests


# ── Config ─────────────────────────────────────────────────────────────────

TRACK_DURATION_SECONDS = 240   # 4 menit per track
MIN_TRACKS_PER_HOUR   = 15     # 15 × 4 mnt = 60 mnt


# ── Helpers ─────────────────────────────────────────────────────────────────

def fetch_track_params(api_url: str, seed: int, track_index: int) -> dict:
    """Minta parameter musik dari Lofi Flask API."""
    # Variasikan seed tiap track agar hasilnya berbeda
    varied_seed = (seed * 31 + track_index * 97) % 999983

    try:
        resp = requests.post(
            f"{api_url.rstrip('/')}/api/generate",
            json={"seed": varied_seed},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        # Fallback: gunakan /api/random endpoint (API asli jacbz)
        try:
            resp = requests.get(
                f"{api_url.rstrip('/')}/api/random",
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            # Last resort: generate params secara lokal (tanpa server)
            print(f"  ⚠️  API tidak bisa diakses, generate params lokal (track {track_index})")
            return generate_local_params(varied_seed)


def generate_local_params(seed: int) -> dict:
    """
    Generate parameter lofi secara lokal tanpa server.
    Menggunakan distribusi yang sama dengan model VAE jacbz.
    """
    rng = random.Random(seed)

    # Chord progression (Roman numeral: 0=rest, 1-7=I-VII, 8=end)
    chord_options = [
        [1, 4, 5, 4],     # I-IV-V-IV (paling common di lofi)
        [1, 5, 6, 4],     # I-V-vi-IV
        [2, 5, 1, 1],     # ii-V-I
        [6, 4, 1, 5],     # vi-IV-I-V
        [1, 4, 6, 5],     # I-IV-vi-V
        [4, 1, 5, 6],     # IV-I-V-vi
        [1, 6, 4, 5],     # I-vi-IV-V
        [2, 6, 3, 7],     # ii-vi-iii-VII
    ]
    chords = rng.choice(chord_options)

    # Melodi: 8 not per chord, scale degree 0-15 (0=rest)
    melodies = []
    for _ in chords:
        melody = []
        for _ in range(8):
            if rng.random() < 0.25:
                melody.append(0)  # rest
            else:
                # Lebih banyak di register tengah (3-9)
                melody.append(rng.choices(
                    range(16),
                    weights=[2,2,2,4,5,5,5,5,4,4,3,3,2,2,1,1]
                )[0])
        melodies.append(melody)

    return {
        "chords": chords,
        "melodies": melodies,
        "tempo": rng.uniform(0.25, 0.65),    # slow-medium lofi tempo
        "key": rng.randint(1, 12),
        "mode": rng.choice([1, 2, 6]),        # major, dorian, aeolian (paling lofi)
        "swing": rng.uniform(0.45, 0.65),
        "vinyl_noise": rng.uniform(0.2, 0.6),
        "reverb": rng.uniform(0.3, 0.7),
        "delay": rng.uniform(0.1, 0.4),
        "bass_level": rng.uniform(0.4, 0.8),
        "drum_level": rng.uniform(0.3, 0.6),
    }


def render_track_nodejs(params: dict, duration: int, output_path: str,
                         node_renderer_dir: str) -> bool:
    """Render satu track ke WAV menggunakan Node.js + Tone.js OfflineAudioContext."""
    params_json = json.dumps(params)
    script = os.path.join(node_renderer_dir, "render.js")

    cmd = [
        "node", script,
        "--params", params_json,
        "--duration", str(duration),
        "--output", output_path,
    ]

    env = os.environ.copy()
    env["DISPLAY"] = os.environ.get("DISPLAY", ":99")

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=duration + 120,  # extra buffer
        )
        if result.returncode != 0:
            print(f"    Node renderer error:\n{result.stderr[:500]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"    ⚠️  Node renderer timeout setelah {duration+120}s")
        return False


def concat_wavs_ffmpeg(wav_files: list, output_path: str) -> bool:
    """Gabungkan beberapa WAV menjadi satu dengan ffmpeg."""
    # Buat file list untuk ffmpeg concat
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        for wav in wav_files:
            f.write(f"file '{wav}'\n")
        list_file = f.name

    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-ar", "44100",
            "-ac", "2",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return result.returncode == 0
    finally:
        os.unlink(list_file)


def crossfade_wavs_ffmpeg(wav_files: list, output_path: str,
                           fade_duration: float = 3.0) -> bool:
    """
    Gabungkan WAV dengan crossfade halus antar track menggunakan ffmpeg.
    Crossfade 3 detik membuat transisi tidak terasa.
    """
    if len(wav_files) == 1:
        import shutil
        shutil.copy(wav_files[0], output_path)
        return True

    # ffmpeg acrossfade filter untuk smooth transition
    inputs = []
    for w in wav_files:
        inputs += ["-i", w]

    # Build filter_complex untuk chain crossfade
    filter_parts = []
    labels = []

    # Label input pertama
    filter_parts.append(f"[0:a]aformat=sample_rates=44100:channel_layouts=stereo[a0]")

    for i in range(1, len(wav_files)):
        prev = f"a{i-1}" if i > 1 else "a0"
        curr = i
        out  = f"a{i}"
        filter_parts.append(
            f"[{prev}][{curr}:a]acrossfade=d={fade_duration}:c1=tri:c2=tri[{out}]"
        )

    filter_complex = ";".join(filter_parts)
    final_label = f"a{len(wav_files)-1}"

    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + ["-filter_complex", filter_complex,
           "-map", f"[{final_label}]",
           "-ar", "44100", "-ac", "2",
           "-acodec", "pcm_s16le",
           output_path]
    )

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        print(f"  crossfade error: {result.stderr[:400]}")
        # Fallback ke concat biasa
        return concat_wavs_ffmpeg(wav_files, output_path)
    return True


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate 1-hour lofi audio")
    parser.add_argument("--seed",       type=int,   default=42)
    parser.add_argument("--duration",   type=int,   default=3600, help="Total detik")
    parser.add_argument("--output",     type=str,   required=True)
    parser.add_argument("--api-url",    type=str,   default="https://lofi.jacobzhang.de")
    parser.add_argument("--track-dur",  type=int,   default=TRACK_DURATION_SECONDS)
    args = parser.parse_args()

    renderer_dir = Path(__file__).parent / "tonejs-renderer"
    total_tracks = max(
        MIN_TRACKS_PER_HOUR,
        (args.duration + args.track_dur - 1) // args.track_dur
    )

    print(f"🎵 Generating {total_tracks} tracks × {args.track_dur}s = {total_tracks * args.track_dur}s audio")
    print(f"   Seed: {args.seed} | API: {args.api_url}")

    track_files = []
    tmpdir = tempfile.mkdtemp(prefix="lofi_tracks_")

    for i in range(total_tracks):
        track_path = os.path.join(tmpdir, f"track_{i:03d}.wav")
        print(f"\n  Track {i+1}/{total_tracks}...")

        # Ambil parameter dari API
        params = fetch_track_params(args.api_url, args.seed, i)
        print(f"    key={params.get('key','?')} mode={params.get('mode','?')} "
              f"tempo={params.get('tempo',0):.2f}")

        # Render audio
        ok = render_track_nodejs(params, args.track_dur, track_path, str(renderer_dir))

        if ok and os.path.exists(track_path) and os.path.getsize(track_path) > 1000:
            track_files.append(track_path)
            print(f"    ✅ Rendered ({os.path.getsize(track_path) // 1024} KB)")
        else:
            print(f"    ❌ Render gagal, skip track ini")

    if not track_files:
        print("❌ Tidak ada track yang berhasil dirender!")
        sys.exit(1)

    print(f"\n🔗 Menggabungkan {len(track_files)} tracks dengan crossfade...")
    ok = crossfade_wavs_ffmpeg(track_files, args.output, fade_duration=3.0)

    if ok and os.path.exists(args.output):
        size_mb = os.path.getsize(args.output) / (1024 * 1024)
        print(f"✅ Audio final: {args.output} ({size_mb:.1f} MB)")
    else:
        print("❌ Gagal menggabungkan tracks!")
        sys.exit(1)

    # Cleanup
    for f in track_files:
        try:
            os.unlink(f)
        except Exception:
            pass
    try:
        os.rmdir(tmpdir)
    except Exception:
        pass


if __name__ == "__main__":
    main()
