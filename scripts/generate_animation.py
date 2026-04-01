#!/usr/bin/env python3
"""
generate_animation.py
Generate animasi lofi procedural yang unik setiap kali.

OPTIMISASI vs versi lama:
  1. Resolusi render 960x540 → di-upscale ffmpeg ke 1920x1080 (4x lebih cepat render)
  2. Loop hanya 10 detik (bukan 30) → 3x lebih sedikit frame
  3. Vignette dihitung SEKALI di awal, bukan setiap frame
  4. Scanlines dihitung SEKALI di awal
  5. Sky gradient dihitung SEKALI di awal
  6. Frame dikirim langsung ke ffmpeg via pipe (tanpa simpan ribuan PNG)
  7. FPS turun ke 15 (bukan 24) → cukup untuk lofi aesthetic
  8. Noise array di-generate batch, bukan per-pixel
"""

import os
import sys
import math
import random
import argparse
import subprocess
import io
import struct
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageDraw
    import numpy as np
except ImportError:
    print("Installing dependencies...")
    subprocess.run([sys.executable, "-m", "pip", "install", "Pillow", "numpy", "--quiet"])
    from PIL import Image, ImageDraw
    import numpy as np

# ── Konfigurasi ────────────────────────────────────────────────────────────────

THEMES = {
    "night_cafe": {
        "sky": (15, 15, 35), "bg": (25, 20, 40),
        "accent": (255, 180, 80), "secondary": (180, 120, 200),
        "window_glow": (255, 200, 100), "particle_color": (255, 220, 150),
    },
    "rainy_window": {
        "sky": (30, 40, 60), "bg": (20, 30, 50),
        "accent": (100, 160, 220), "secondary": (70, 100, 150),
        "window_glow": (200, 220, 255), "particle_color": (150, 180, 220),
    },
    "cozy_bedroom": {
        "sky": (10, 15, 30), "bg": (35, 25, 20),
        "accent": (220, 140, 60), "secondary": (160, 100, 80),
        "window_glow": (255, 210, 140), "particle_color": (255, 200, 100),
    },
    "forest_dawn": {
        "sky": (40, 60, 30), "bg": (20, 40, 25),
        "accent": (150, 200, 100), "secondary": (100, 150, 80),
        "window_glow": (220, 255, 180), "particle_color": (180, 220, 150),
    },
    "city_rooftop": {
        "sky": (5, 5, 20), "bg": (15, 15, 35),
        "accent": (255, 100, 100), "secondary": (100, 100, 255),
        "window_glow": (200, 200, 100), "particle_color": (255, 255, 200),
    },
    "library": {
        "sky": (20, 15, 10), "bg": (30, 25, 15),
        "accent": (200, 160, 80), "secondary": (150, 100, 60),
        "window_glow": (255, 220, 160), "particle_color": (220, 180, 100),
    },
}

# OPTIMISASI #1: render di resolusi kecil, ffmpeg upscale ke 1080p
RENDER_W, RENDER_H = 960, 540   # render resolution (setengah dari 1920x1080)
OUTPUT_W, OUTPUT_H = 1920, 1080  # output resolution (di-upscale ffmpeg)
FPS = 15                          # OPTIMISASI #7: 15fps cukup untuk lofi
LOOP_SECONDS = 10                 # OPTIMISASI #2: loop 10 detik (bukan 30)

# ── Helper ─────────────────────────────────────────────────────────────────────

def lerp(a, b, t):
    return a + (b - a) * t

def lerp_color(c1, c2, t):
    return tuple(int(lerp(c1[i], c2[i], t)) for i in range(3))

def ease_in_out(t):
    return t * t * (3 - 2 * t)

# ── Scene Renderer ──────────────────────────────────────────────────────────────

class LofiSceneRenderer:
    def __init__(self, theme_name: str, seed: int):
        self.theme = THEMES.get(theme_name, THEMES["night_cafe"])
        self.rng = np.random.default_rng(seed)
        self.py_rng = random.Random(seed)
        self.seed = seed
        self._init_scene()
        self._precompute_static()  # OPTIMISASI #3,4,5

    def _init_scene(self):
        rng = self.py_rng
        theme = self.theme

        self.stars = [
            (rng.randint(0, RENDER_W), rng.randint(0, RENDER_H // 2),
             rng.uniform(0.5, 1.5), rng.uniform(0, math.pi * 2))
            for _ in range(rng.randint(30, 80))
        ]

        self.buildings = []
        x = 0
        while x < RENDER_W:
            w = rng.randint(40, 120)
            h = rng.randint(RENDER_H // 4, RENDER_H * 2 // 3)
            floors = rng.randint(3, 10)
            wpf = max(1, w // 25)
            self.buildings.append({
                "x": x, "w": w, "h": h, "floors": floors, "wpf": wpf,
                "lit": set(
                    (rng.randint(0, floors), rng.randint(0, wpf))
                    for _ in range(rng.randint(floors // 2, max(floors // 2 + 1, floors * wpf // 2)))
                ),
                "color": lerp_color(theme["bg"], (50, 50, 70), rng.uniform(0, 1))
            })
            x += w + rng.randint(0, 15)

        self.particles = [{
            "x": rng.uniform(0, RENDER_W),
            "y": rng.uniform(0, RENDER_H),
            "vx": rng.uniform(-0.3, 0.3),
            "vy": rng.uniform(-0.5, 0.2),
            "size": rng.uniform(1, 3),
            "phase": rng.uniform(0, math.pi * 2),
            "speed": rng.uniform(0.01, 0.05),
            "alpha": rng.uniform(0.3, 1.0),
        } for _ in range(rng.randint(15, 40))]

        self.has_cat = rng.random() > 0.4
        self.cat_x = rng.randint(RENDER_W // 4, RENDER_W * 3 // 4)
        self.has_plant = rng.random() > 0.5
        self.plant_x = rng.choice([60, RENDER_W - 80])
        self.has_coffee = rng.random() > 0.3
        self.coffee_x = rng.randint(RENDER_W // 3, RENDER_W * 2 // 3)
        self.moon_x = rng.randint(RENDER_W // 4, RENDER_W * 3 // 4)
        self.moon_y = rng.randint(25, RENDER_H // 4)

    def _precompute_static(self):
        """OPTIMISASI: Hitung elemen statis SATU KALI, bukan per frame."""
        theme = self.theme

        # OPTIMISASI #5: Pre-render sky gradient sebagai array
        sky_arr = np.zeros((RENDER_H, RENDER_W, 3), dtype=np.uint8)
        half = RENDER_H // 2
        for y in range(half):
            ratio = y / half
            color = lerp_color(theme["sky"], lerp_color(theme["sky"], theme["bg"], 0.3), ratio)
            sky_arr[y, :] = color
        for y in range(half, RENDER_H):
            sky_arr[y, :] = theme["bg"]
        self._sky_arr = sky_arr

        # OPTIMISASI #3: Pre-compute vignette factor
        cx, cy = RENDER_W / 2, RENDER_H / 2
        y_coords, x_coords = np.mgrid[0:RENDER_H, 0:RENDER_W]
        dist = np.sqrt(((x_coords - cx) / cx) ** 2 + ((y_coords - cy) / cy) ** 2)
        self._vignette = np.clip(1 - dist * 0.5, 0.3, 1.0)[:, :, np.newaxis].astype(np.float32)

        # OPTIMISASI #4: Pre-compute scanline mask
        self._scanline_mask = np.ones((RENDER_H, RENDER_W, 3), dtype=np.float32)
        self._scanline_mask[::4] = 0.85

        # Pre-render buildings (statis, tidak beranimasi kecuali jendela flicker)
        # Simpan base building image tanpa jendela
        self._building_base = Image.new("RGB", (RENDER_W, RENDER_H), (0, 0, 0))
        draw = ImageDraw.Draw(self._building_base)
        for b in self.buildings:
            bx, bw, bh = b["x"], b["w"], b["h"]
            by = RENDER_H - bh
            draw.rectangle([bx, by, bx + bw, RENDER_H], fill=b["color"])
            draw.rectangle([bx - 2, by - 4, bx + bw + 2, by],
                           fill=lerp_color(b["color"], (80, 80, 100), 0.5))

    def render_frame(self, t: float) -> bytes:
        """Render satu frame, return sebagai raw RGB bytes."""
        # Mulai dari sky gradient yang sudah pre-computed
        arr = self._sky_arr.copy()
        img = Image.fromarray(arr)
        draw = ImageDraw.Draw(img)

        self._draw_moon_stars(draw, t)

        # Paste building base
        img.paste(self._building_base, mask=Image.fromarray(
            np.any(np.array(self._building_base) > 0, axis=2).astype(np.uint8) * 255
        ))
        draw = ImageDraw.Draw(img)

        self._draw_window_lights(draw, t)
        self._draw_foreground(draw, t)
        self._draw_particles(draw, t)
        if self.has_cat:
            self._draw_cat(draw, t)

        # Apply vignette + scanlines via numpy (OPTIMISASI)
        arr = np.array(img, dtype=np.float32)
        arr = arr * self._vignette
        arr = arr * self._scanline_mask

        # Noise ringan
        noise = self.rng.integers(-3, 3, arr.shape, dtype=np.int16)
        arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        return arr.tobytes()  # return raw bytes langsung

    def _draw_moon_stars(self, draw, t):
        theme = self.theme
        mx, my = self.moon_x, self.moon_y

        # Glow (lebih sedikit iterasi)
        for r in range(40, 0, -8):
            glow_color = lerp_color(theme["sky"], theme["window_glow"], r / 40 * 0.3)
            draw.ellipse([mx - r, my - r, mx + r, my + r], fill=glow_color)

        draw.ellipse([mx - 15, my - 15, mx + 15, my + 15], fill=theme["window_glow"])

        # Stars
        for (sx, sy, size, phase) in self.stars:
            twinkle = 0.5 + 0.5 * math.sin(t * 1.5 + phase)
            brightness = int(180 * twinkle)
            r = size * twinkle
            if r > 0.5:
                draw.ellipse([sx - r, sy - r, sx + r, sy + r],
                             fill=(brightness, brightness, min(255, brightness + 40)))

    def _draw_window_lights(self, draw, t):
        theme = self.theme
        floor_h = 16
        window_w, window_h = 6, 8

        for b in self.buildings:
            bx, bw, bh = b["x"], b["w"], b["h"]
            by = RENDER_H - bh
            for floor in range(b["floors"]):
                fy = RENDER_H - floor_h * (floor + 1) - 15
                if fy < by:
                    break
                for wp in range(b["wpf"]):
                    wx = bx + 6 + wp * (window_w + 8)
                    if wx + window_w > bx + bw - 6:
                        break
                    if (floor, wp) in b["lit"]:
                        flicker = 0.88 + 0.12 * math.sin(t * 3 + floor * 1.7 + wp * 2.3)
                        wcolor = tuple(int(c * flicker) for c in theme["window_glow"])
                        draw.rectangle([wx, fy, wx + window_w, fy + window_h], fill=wcolor)
                    else:
                        draw.rectangle([wx, fy, wx + window_w, fy + window_h], fill=(20, 20, 30))

    def _draw_foreground(self, draw, t):
        theme = self.theme
        table_y = RENDER_H * 2 // 3

        for y in range(table_y, RENDER_H):
            ratio = (y - table_y) / (RENDER_H - table_y)
            color = lerp_color((40, 30, 20), (20, 15, 10), ratio)
            draw.line([(0, y), (RENDER_W, y)], fill=color)

        draw.rectangle([0, table_y, RENDER_W, table_y + 6], fill=(60, 45, 30))

        if self.has_coffee:
            self._draw_coffee(draw, t)
        if self.has_plant:
            self._draw_plant(draw)

        book_x = RENDER_W // 2 - 100
        draw.rectangle([book_x, table_y - 10, book_x + 80, table_y + 2], fill=(140, 60, 60))
        draw.rectangle([book_x + 3, table_y - 9, book_x + 77, table_y], fill=(160, 80, 80))

    def _draw_coffee(self, draw, t):
        theme = self.theme
        cx = self.coffee_x
        cy = RENDER_H * 2 // 3 - 4

        draw.ellipse([cx - 18, cy - 4, cx + 18, cy + 4], fill=(180, 160, 140))
        draw.polygon([(cx - 13, cy - 4), (cx + 13, cy - 4),
                      (cx + 10, cy - 26), (cx - 10, cy - 26)], fill=(200, 180, 160))
        draw.ellipse([cx - 9, cy - 25, cx + 9, cy - 19], fill=(60, 35, 15))
        draw.arc([cx + 9, cy - 22, cx + 19, cy - 8], start=320, end=50,
                 fill=(180, 160, 140), width=2)

        # Asap (lebih sedikit titik)
        for i in range(2):
            smoke_x = cx - 4 + i * 8
            for j in range(5):
                sway = 2 * math.sin(t * 2 + i * 1.2 + j * 0.5)
                sy = cy - 30 - j * 4
                alpha = 1 - j / 5
                smoke_color = lerp_color((180, 180, 180), theme["bg"], 1 - alpha * 0.4)
                r = 1.5 + j * 0.2
                draw.ellipse([smoke_x + sway - r, sy - r, smoke_x + sway + r, sy + r],
                             fill=smoke_color)

    def _draw_plant(self, draw):
        px = self.plant_x
        py = RENDER_H * 2 // 3

        draw.polygon([(px - 10, py), (px + 10, py),
                      (px + 8, py - 18), (px - 8, py - 18)], fill=(140, 90, 60))
        leaf_colors = [(60, 140, 70), (40, 120, 50), (80, 160, 80)]
        positions = [(px - 14, py - 28), (px + 14, py - 32), (px - 10, py - 40),
                     (px + 7, py - 44), (px, py - 50)]
        for i, (lx, ly) in enumerate(positions):
            draw.ellipse([lx - 9, ly - 6, lx + 9, ly + 6],
                         fill=leaf_colors[i % len(leaf_colors)])

    def _draw_cat(self, draw, t):
        theme = self.theme
        cx = self.cat_x
        cy = RENDER_H * 2 // 3 - 2
        cat_color = (80, 70, 60)
        cat_dark = (50, 40, 35)

        draw.ellipse([cx - 22, cy - 26, cx + 22, cy + 4], fill=cat_color)
        draw.ellipse([cx - 16, cy - 48, cx + 16, cy - 20], fill=cat_color)

        # Telinga
        draw.polygon([(cx - 13, cy - 45), (cx - 6, cy - 45), (cx - 11, cy - 57)], fill=cat_color)
        draw.polygon([(cx + 6, cy - 45), (cx + 13, cy - 45), (cx + 11, cy - 57)], fill=cat_color)
        draw.polygon([(cx - 11, cy - 46), (cx - 7, cy - 46), (cx - 10, cy - 54)], fill=(180, 130, 130))
        draw.polygon([(cx + 7, cy - 46), (cx + 11, cy - 46), (cx + 10, cy - 54)], fill=(180, 130, 130))

        # Mata
        blink = (t * 0.3) % 1.0
        if blink > 0.95:
            draw.line([(cx - 9, cy - 38), (cx - 5, cy - 38)], fill=cat_dark, width=2)
            draw.line([(cx + 5, cy - 38), (cx + 9, cy - 38)], fill=cat_dark, width=2)
        else:
            draw.ellipse([cx - 10, cy - 40, cx - 5, cy - 35], fill=(50, 80, 50))
            draw.ellipse([cx + 5, cy - 40, cx + 10, cy - 35], fill=(50, 80, 50))
            draw.ellipse([cx - 8, cy - 39, cx - 7, cy - 37], fill=cat_dark)
            draw.ellipse([cx + 7, cy - 39, cx + 8, cy - 37], fill=cat_dark)

        draw.polygon([(cx, cy - 33), (cx - 2, cy - 31), (cx + 2, cy - 31)], fill=(220, 150, 160))

        # Ekor
        tail_pts = [(cx - 22 - i * 4,
                     cy + 2 + math.sin(t * 1.5 + i * 0.5) * (15 * (i / 8)))
                    for i in range(9)]
        if len(tail_pts) >= 2:
            draw.line(tail_pts, fill=cat_dark, width=3)

    def _draw_particles(self, draw, t):
        theme = self.theme
        for p in self.particles:
            x = (p["x"] + p["vx"] * t * 20) % RENDER_W
            y = (p["y"] + p["vy"] * t * 20) % RENDER_H
            alpha = p["alpha"] * (0.5 + 0.5 * math.sin(t * p["speed"] * 100 + p["phase"]))
            color = tuple(int(c * alpha) for c in theme["particle_color"])
            r = p["size"]
            if all(c > 5 for c in color):
                draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--theme', type=str, default='night_cafe')
    parser.add_argument('--duration', type=int, default=60, help='Durasi dalam menit')
    parser.add_argument('--output', type=str, default='/tmp/lofi_animation.mp4')
    args = parser.parse_args()

    theme = args.theme if args.theme in THEMES else list(THEMES.keys())[args.seed % len(THEMES)]
    print(f"[animation] Tema: {theme} | Seed: {args.seed} | Durasi: {args.duration} menit")
    print(f"[animation] Render: {RENDER_W}x{RENDER_H} @ {FPS}fps → upscale ke {OUTPUT_W}x{OUTPUT_H}")

    renderer = LofiSceneRenderer(theme_name=theme, seed=args.seed)

    n_frames = FPS * LOOP_SECONDS
    total_seconds = args.duration * 60
    loop_count = math.ceil(total_seconds / LOOP_SECONDS)

    print(f"[animation] Render {n_frames} frame ({LOOP_SECONDS}s loop, di-loop {loop_count}x)...")

    # OPTIMISASI #6: Pipe frame langsung ke ffmpeg, tanpa simpan PNG ke disk
    ffmpeg_loop = subprocess.Popen(
        [
            "ffmpeg", "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{RENDER_W}x{RENDER_H}",
            "-pix_fmt", "rgb24",
            "-r", str(FPS),
            "-i", "pipe:0",
            "-vf", f"scale={OUTPUT_W}:{OUTPUT_H}:flags=lanczos",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-crf", "23",
            "/tmp/lofi_loop.mp4"
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.DEVNULL
    )

    for i in range(n_frames):
        t = i / FPS
        frame_bytes = renderer.render_frame(t)
        ffmpeg_loop.stdin.write(frame_bytes)

        if i % (FPS * 3) == 0:
            pct = 100 * i // n_frames
            print(f"[animation] Frame {i}/{n_frames} ({pct}%)")

    ffmpeg_loop.stdin.close()
    ffmpeg_loop.wait()

    if ffmpeg_loop.returncode != 0:
        print("[animation] ERROR: ffmpeg loop encoding gagal!")
        sys.exit(1)

    print("[animation] Loop video selesai, membuat video panjang...")

    # Loop ke durasi penuh dengan stream copy (sangat cepat)
    cmd_loop = [
        "ffmpeg", "-y",
        "-stream_loop", str(loop_count),
        "-i", "/tmp/lofi_loop.mp4",
        "-c", "copy",
        "-t", str(total_seconds),
        args.output
    ]
    result = subprocess.run(cmd_loop, capture_output=True)
    if result.returncode != 0:
        print(f"[animation] ERROR loop: {result.stderr.decode()}")
        sys.exit(1)

    # Cleanup temp
    try:
        os.remove("/tmp/lofi_loop.mp4")
    except Exception:
        pass

    size_mb = os.path.getsize(args.output) / 1024 / 1024
    print(f"[animation] ✅ Selesai! {args.output} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
