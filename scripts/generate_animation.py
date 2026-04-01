#!/usr/bin/env python3
"""
generate_animation.py
Generate animasi lofi procedural yang unik setiap kali.
Pipe frame langsung ke FFmpeg via stdin — tanpa temp PNG files.
"""

import os
import sys
import math
import random
import argparse
import subprocess
from pathlib import Path

try:
    from PIL import Image, ImageDraw
    import numpy as np
except ImportError:
    print("Installing dependencies...")
    subprocess.run([sys.executable, "-m", "pip", "install", "Pillow", "numpy", "--quiet"])
    from PIL import Image, ImageDraw
    import numpy as np

# ── Konfigurasi ─────────────────────────────────────────────────────────────────

THEMES = {
    "night_cafe": {
        "sky": (15, 15, 35),
        "bg": (25, 20, 40),
        "accent": (255, 180, 80),
        "secondary": (180, 120, 200),
        "window_glow": (255, 200, 100),
        "particle_color": (255, 220, 150),
    },
    "rainy_window": {
        "sky": (30, 40, 60),
        "bg": (20, 30, 50),
        "accent": (100, 160, 220),
        "secondary": (70, 100, 150),
        "window_glow": (200, 220, 255),
        "particle_color": (150, 180, 220),
    },
    "cozy_bedroom": {
        "sky": (10, 15, 30),
        "bg": (35, 25, 20),
        "accent": (220, 140, 60),
        "secondary": (160, 100, 80),
        "window_glow": (255, 210, 140),
        "particle_color": (255, 200, 100),
    },
    "forest_dawn": {
        "sky": (40, 60, 30),
        "bg": (20, 40, 25),
        "accent": (150, 200, 100),
        "secondary": (100, 150, 80),
        "window_glow": (220, 255, 180),
        "particle_color": (180, 220, 150),
    },
    "city_rooftop": {
        "sky": (5, 5, 20),
        "bg": (15, 15, 35),
        "accent": (255, 100, 100),
        "secondary": (100, 100, 255),
        "window_glow": (200, 200, 100),
        "particle_color": (255, 255, 200),
    },
    "library": {
        "sky": (20, 15, 10),
        "bg": (30, 25, 15),
        "accent": (200, 160, 80),
        "secondary": (150, 100, 60),
        "window_glow": (255, 220, 160),
        "particle_color": (220, 180, 100),
    },
}

WIDTH, HEIGHT = 1920, 1080
FPS = 24

# ── Helpers ──────────────────────────────────────────────────────────────────────

def lerp(a, b, t):
    return a + (b - a) * t

def lerp_color(c1, c2, t):
    return tuple(int(lerp(c1[i], c2[i], t)) for i in range(3))

def ease_in_out(t):
    return t * t * (3 - 2 * t)

def add_noise(img_array, rng, intensity=4):
    noise = rng.integers(-intensity, intensity, img_array.shape, dtype=np.int16)
    return np.clip(img_array.astype(np.int16) + noise, 0, 255).astype(np.uint8)

# Precompute vignette multiplier once
def _build_vignette():
    cx, cy = WIDTH / 2, HEIGHT / 2
    y_coords, x_coords = np.mgrid[0:HEIGHT, 0:WIDTH]
    dist = np.sqrt(((x_coords - cx) / cx) ** 2 + ((y_coords - cy) / cy) ** 2)
    factor = np.clip(1 - dist * 0.5, 0.3, 1.0).astype(np.float32)
    return factor[:, :, np.newaxis]

VIGNETTE = _build_vignette()

# Precompute scanline mask once
SCANLINE_MASK = np.ones((HEIGHT, WIDTH, 3), dtype=np.float32)
SCANLINE_MASK[::4] = 0.85

# Precompute sky gradient once (static, only depends on theme colors)
def _build_sky_gradient(sky_color, bg_color):
    half = HEIGHT // 2
    ratios = np.linspace(0, 1, half, dtype=np.float32)
    mid_color = lerp_color(sky_color, bg_color, 0.3)
    gradient = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    for c in range(3):
        row = (sky_color[c] + (mid_color[c] - sky_color[c]) * ratios).astype(np.uint8)
        gradient[:half, :, c] = row[:, np.newaxis]
        gradient[half:, :, c] = bg_color[c]
    return gradient


# ── Scene Renderer ───────────────────────────────────────────────────────────────

class LofiSceneRenderer:
    def __init__(self, theme_name: str, seed: int):
        self.theme = THEMES.get(theme_name, THEMES["night_cafe"])
        self.rng = np.random.default_rng(seed)
        self.py_rng = random.Random(seed)
        self.seed = seed
        self._sky_gradient = _build_sky_gradient(self.theme["sky"], self.theme["bg"])
        self._init_scene()

    def _init_scene(self):
        rng = self.py_rng
        theme = self.theme

        self.stars = [
            (rng.randint(0, WIDTH), rng.randint(0, HEIGHT // 2),
             rng.uniform(0.5, 2.0), rng.uniform(0, math.pi * 2))
            for _ in range(rng.randint(40, 120))
        ]

        self.buildings = []
        x = 0
        while x < WIDTH:
            w = rng.randint(60, 180)
            h = rng.randint(HEIGHT // 4, HEIGHT * 2 // 3)
            floors = rng.randint(3, 12)
            wpf = max(1, w // 30)
            self.buildings.append({
                "x": x, "w": w, "h": h,
                "floors": floors,
                "windows_per_floor": wpf,
                "lit_windows": set(
                    (rng.randint(0, floors), rng.randint(0, wpf))
                    for _ in range(rng.randint(floors // 2, floors * wpf // 2))
                ),
                "color": lerp_color(theme["bg"], (50, 50, 70), rng.uniform(0, 1))
            })
            x += w + rng.randint(0, 20)

        self.particles = [{
            "x": rng.uniform(0, WIDTH),
            "y": rng.uniform(0, HEIGHT),
            "vx": rng.uniform(-0.3, 0.3),
            "vy": rng.uniform(-0.5, 0.2),
            "size": rng.uniform(1, 4),
            "phase": rng.uniform(0, math.pi * 2),
            "speed": rng.uniform(0.01, 0.05),
            "alpha": rng.uniform(0.3, 1.0),
        } for _ in range(rng.randint(20, 60))]

        self.has_cat = rng.random() > 0.4
        self.cat_x = rng.randint(WIDTH // 4, WIDTH * 3 // 4)
        self.has_plant = rng.random() > 0.5
        self.plant_x = rng.choice([100, WIDTH - 150])
        self.has_coffee = rng.random() > 0.3
        self.coffee_x = rng.randint(WIDTH // 3, WIDTH * 2 // 3)
        self.moon_x = rng.randint(WIDTH // 4, WIDTH * 3 // 4)
        self.moon_y = rng.randint(40, HEIGHT // 4)

    def render_frame(self, t: float) -> bytes:
        """Render satu frame, kembalikan raw RGB bytes."""
        # Start from precomputed sky gradient
        arr = self._sky_gradient.copy()
        img = Image.fromarray(arr)
        draw = ImageDraw.Draw(img)

        self._draw_moon_stars(draw, t)
        self._draw_buildings(draw, t)
        self._draw_foreground_table(draw, t)
        self._draw_particles(draw, t)
        self._draw_cat(draw, t)

        # Post-process via numpy (vignette + scanlines + noise) in one pass
        arr = np.array(img, dtype=np.float32)
        arr = arr * VIGNETTE * SCANLINE_MASK
        arr = np.clip(arr, 0, 255).astype(np.uint8)
        arr = add_noise(arr, self.rng, intensity=4)

        return arr.tobytes()

    def _draw_moon_stars(self, draw, t):
        theme = self.theme
        moon_glow_r = 60 + 10 * math.sin(t * 0.1)
        for r in range(int(moon_glow_r), 0, -4):
            alpha = int(30 * (1 - r / moon_glow_r))
            glow_color = lerp_color(theme["sky"], theme["window_glow"], alpha / 255)
            draw.ellipse(
                [self.moon_x - r, self.moon_y - r, self.moon_x + r, self.moon_y + r],
                fill=glow_color
            )
        draw.ellipse(
            [self.moon_x - 20, self.moon_y - 20, self.moon_x + 20, self.moon_y + 20],
            fill=theme["window_glow"]
        )
        for (sx, sy, size, phase) in self.stars:
            twinkle = 0.5 + 0.5 * math.sin(t * 1.5 + phase)
            brightness = int(180 * twinkle)
            star_color = (brightness, brightness, min(255, brightness + 40))
            r = size * twinkle
            draw.ellipse([sx - r, sy - r, sx + r, sy + r], fill=star_color)

    def _draw_buildings(self, draw, t):
        theme = self.theme
        for b in self.buildings:
            top = HEIGHT - b["h"]
            draw.rectangle([b["x"], top, b["x"] + b["w"], HEIGHT], fill=b["color"])
            fh = b["h"] // b["floors"]
            for floor in range(b["floors"]):
                for win in range(b["windows_per_floor"]):
                    if (floor, win) in b["lit_windows"]:
                        wx = b["x"] + 8 + win * (b["w"] - 16) // max(1, b["windows_per_floor"] - 1)
                        wy = top + 8 + floor * fh
                        flicker = 0.85 + 0.15 * math.sin(t * 3 + floor * 1.3 + win * 0.7)
                        wc = tuple(int(c * flicker) for c in theme["window_glow"])
                        draw.rectangle([wx - 5, wy, wx + 5, wy + fh - 8], fill=wc)

    def _draw_foreground_table(self, draw, t):
        theme = self.theme
        table_y = HEIGHT * 2 // 3
        draw.rectangle([0, table_y, WIDTH, HEIGHT], fill=theme["bg"])
        draw.line([(0, table_y), (WIDTH, table_y)], fill=theme["accent"], width=2)
        if self.has_coffee:
            self._draw_coffee(draw, t)
        if self.has_plant:
            self._draw_plant(draw)

    def _draw_coffee(self, draw, t):
        theme = self.theme
        cx = self.coffee_x
        cy = HEIGHT * 2 // 3 - 15
        draw.ellipse([cx - 18, cy - 8, cx + 18, cy + 8], fill=(60, 45, 35))
        draw.ellipse([cx - 15, cy - 5, cx + 15, cy + 5], fill=(30, 20, 15))
        draw.rectangle([cx - 15, cy - 30, cx + 15, cy - 8], fill=(80, 65, 55))
        draw.arc([cx + 12, cy - 30, cx + 26, cy - 10], start=320, end=50, fill=(180, 160, 140), width=3)
        for i in range(3):
            phase_offset = i * 1.2
            smoke_x = cx - 8 + i * 8
            smoke_y = cy - 40
            for j in range(8):
                sway = 3 * math.sin(t * 2 + phase_offset + j * 0.5)
                sy2 = smoke_y - j * 5
                alpha = max(0, 1 - j / 8)
                smoke_color = lerp_color((200, 200, 200), theme["bg"], 1 - alpha * 0.4)
                r = 2 + j * 0.3
                draw.ellipse([smoke_x + sway - r, sy2 - r, smoke_x + sway + r, sy2 + r],
                             fill=smoke_color)

    def _draw_plant(self, draw):
        px = self.plant_x
        py = HEIGHT * 2 // 3
        draw.polygon([(px - 15, py), (px + 15, py), (px + 12, py - 25), (px - 12, py - 25)],
                     fill=(140, 90, 60))
        draw.ellipse([px - 15, py - 28, px + 15, py - 22], fill=(160, 110, 80))
        leaf_colors = [(60, 140, 70), (40, 120, 50), (80, 160, 80)]
        leaf_positions = [
            (px - 20, py - 40), (px + 20, py - 45), (px - 15, py - 55),
            (px + 10, py - 60), (px, py - 70), (px - 25, py - 65)
        ]
        for i, (lx, ly) in enumerate(leaf_positions):
            draw.ellipse([lx - 12, ly - 8, lx + 12, ly + 8], fill=leaf_colors[i % len(leaf_colors)])

    def _draw_cat(self, draw, t):
        if not self.has_cat:
            return
        theme = self.theme
        cx = self.cat_x
        cy = HEIGHT * 2 // 3 - 2
        cat_body_color = (80, 70, 60)
        cat_dark = (50, 40, 35)
        draw.ellipse([cx - 30, cy - 35, cx + 30, cy + 5], fill=cat_body_color)
        draw.ellipse([cx - 22, cy - 65, cx + 22, cy - 28], fill=cat_body_color)
        draw.polygon([(cx - 18, cy - 62), (cx - 8, cy - 62), (cx - 15, cy - 78)], fill=cat_body_color)
        draw.polygon([(cx + 8, cy - 62), (cx + 18, cy - 62), (cx + 15, cy - 78)], fill=cat_body_color)
        draw.polygon([(cx - 16, cy - 64), (cx - 10, cy - 64), (cx - 14, cy - 74)], fill=(180, 130, 130))
        draw.polygon([(cx + 10, cy - 64), (cx + 16, cy - 64), (cx + 14, cy - 74)], fill=(180, 130, 130))
        blink_cycle = (t * 0.3) % 1.0
        if blink_cycle > 0.95:
            draw.line([(cx - 12, cy - 52), (cx - 6, cy - 52)], fill=cat_dark, width=2)
            draw.line([(cx + 6, cy - 52), (cx + 12, cy - 52)], fill=cat_dark, width=2)
        else:
            draw.ellipse([cx - 13, cy - 55, cx - 7, cy - 49], fill=(50, 80, 50))
            draw.ellipse([cx + 7, cy - 55, cx + 13, cy - 49], fill=(50, 80, 50))
            draw.ellipse([cx - 11, cy - 53, cx - 9, cy - 51], fill=cat_dark)
            draw.ellipse([cx + 9, cy - 53, cx + 11, cy - 51], fill=cat_dark)
            draw.ellipse([cx - 10, cy - 53, cx - 9, cy - 52], fill=(255, 255, 255))
            draw.ellipse([cx + 10, cy - 53, cx + 11, cy - 52], fill=(255, 255, 255))
        draw.polygon([(cx, cy - 46), (cx - 3, cy - 43), (cx + 3, cy - 43)], fill=(220, 150, 160))
        for side in [-1, 1]:
            for i in range(3):
                wx = cx + side * 8
                wy = cy - 44 + i * 3
                ex = cx + side * 22
                ey = cy - 43 + i * 3
                draw.line([(wx, wy), (ex, ey)], fill=(200, 200, 200), width=1)
        tail_points = []
        for i in range(10):
            t_ratio = i / 9
            tail_swing = 15 * math.sin(t * 1.5)
            tx = cx - 30 - i * 5
            ty = cy + 3 + math.sin(t * 1.5 + i * 0.5) * (tail_swing * t_ratio)
            tail_points.append((tx, ty))
        if len(tail_points) >= 2:
            draw.line(tail_points, fill=cat_dark, width=4)

    def _draw_particles(self, draw, t):
        theme = self.theme
        for p in self.particles:
            x = (p["x"] + p["vx"] * t * 20) % WIDTH
            y = (p["y"] + p["vy"] * t * 20) % HEIGHT
            alpha = p["alpha"] * (0.5 + 0.5 * math.sin(t * p["speed"] * 100 + p["phase"]))
            color = tuple(int(c * alpha) for c in theme["particle_color"])
            r = p["size"]
            if all(c > 5 for c in color):
                draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


# ── Main ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--theme', type=str, default='night_cafe')
    parser.add_argument('--duration', type=int, default=60, help='Durasi dalam menit')
    parser.add_argument('--output', type=str, default='/tmp/lofi_animation.mp4')
    args = parser.parse_args()

    theme = args.theme if args.theme in THEMES else list(THEMES.keys())[args.seed % len(THEMES)]
    print(f"[animation] Tema: {theme}, Seed: {args.seed}, Durasi: {args.duration} menit")

    renderer = LofiSceneRenderer(theme_name=theme, seed=args.seed)

    loop_duration = 30  # detik
    n_frames = FPS * loop_duration
    total_seconds = args.duration * 60
    loop_count = math.ceil(total_seconds / loop_duration)

    print(f"[animation] Render {n_frames} frame ({loop_duration}s loop) -> pipe ke FFmpeg...")

    # FFmpeg baca raw RGB dari stdin, encode langsung ke loop file
    ffmpeg_encode = subprocess.Popen([
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{WIDTH}x{HEIGHT}",
        "-pix_fmt", "rgb24",
        "-r", str(FPS),
        "-i", "pipe:0",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "23",
        "/tmp/lofi_loop.mp4"
    ], stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    for i in range(n_frames):
        t = i / FPS
        raw = renderer.render_frame(t)
        ffmpeg_encode.stdin.write(raw)
        if i % (FPS * 5) == 0:
            print(f"[animation] Frame {i}/{n_frames} ({100*i//n_frames}%)")

    ffmpeg_encode.stdin.close()
    ffmpeg_encode.wait()
    print("[animation] Encode loop selesai")

    # Loop ke durasi penuh
    print(f"[animation] Loop {loop_count}x ke {total_seconds}s -> {args.output}")
    subprocess.run([
        "ffmpeg", "-y",
        "-stream_loop", str(loop_count),
        "-i", "/tmp/lofi_loop.mp4",
        "-c", "copy",
        "-t", str(total_seconds),
        args.output
    ], check=True, capture_output=True)

    size_mb = os.path.getsize(args.output) / 1024 / 1024
    print(f"[animation] Selesai! {args.output} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
