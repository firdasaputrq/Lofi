#!/usr/bin/env python3
"""
generate_animation.py
Membuat animasi lofi cafe/bedroom yang UNIK setiap video berdasarkan seed.
100% procedural — tidak menggunakan asset eksternal atau copyrighted GIF.

Scene yang di-generate:
  - Background: ruangan (cafe/bedroom/library/studio) dengan warna berbeda
  - Jendela dengan hujan / salju / bintang / langit sore
  - Efek parallax lembut
  - Rain/snow particle system
  - Lampu berkedip halus
  - Steam dari kopi
  - Teks judul di sudut
  - Semua di-export sebagai MP4 dengan ffmpeg
"""

import argparse
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ── Config ────────────────────────────────────────────────────────────────────

WIDTH, HEIGHT = 1920, 1080
FPS = 24

# ── Color palettes (tiap punya "feel" berbeda) ────────────────────────────────

PALETTES = [
    # Rainy night cafe
    {
        "name": "rainy_night",
        "sky": (15, 18, 35),
        "sky2": (30, 25, 55),
        "wall": (45, 35, 55),
        "floor": (30, 22, 35),
        "window_glow": (255, 200, 120),
        "accent": (180, 140, 255),
        "rain": True, "snow": False, "stars": False,
    },
    # Afternoon bedroom
    {
        "name": "afternoon_bedroom",
        "sky": (255, 180, 100),
        "sky2": (255, 140, 80),
        "wall": (220, 180, 150),
        "floor": (160, 120, 90),
        "window_glow": (255, 220, 160),
        "accent": (255, 150, 100),
        "rain": False, "snow": False, "stars": False,
    },
    # Snowy night
    {
        "name": "snowy_night",
        "sky": (10, 15, 40),
        "sky2": (20, 30, 70),
        "wall": (50, 55, 75),
        "floor": (35, 40, 55),
        "window_glow": (200, 220, 255),
        "accent": (150, 200, 255),
        "rain": False, "snow": True, "stars": True,
    },
    # Cozy library dusk
    {
        "name": "library_dusk",
        "sky": (60, 30, 80),
        "sky2": (120, 50, 100),
        "wall": (80, 55, 45),
        "floor": (55, 38, 28),
        "window_glow": (255, 160, 90),
        "accent": (255, 200, 100),
        "rain": False, "snow": False, "stars": True,
    },
    # Neon rain
    {
        "name": "neon_rain",
        "sky": (5, 5, 20),
        "sky2": (10, 5, 35),
        "wall": (20, 15, 40),
        "floor": (15, 10, 30),
        "window_glow": (100, 255, 200),
        "accent": (255, 80, 200),
        "rain": True, "snow": False, "stars": False,
    },
    # Golden hour studio
    {
        "name": "golden_studio",
        "sky": (255, 200, 80),
        "sky2": (255, 160, 40),
        "wall": (200, 155, 100),
        "floor": (140, 100, 65),
        "window_glow": (255, 230, 150),
        "accent": (255, 180, 50),
        "rain": False, "snow": False, "stars": False,
    },
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def lerp_color(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))

def add_noise(img_array, intensity=3):
    noise = np.random.randint(-intensity, intensity + 1, img_array.shape, dtype=np.int16)
    noisy = np.clip(img_array.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return noisy

def draw_gradient_rect(draw, x0, y0, x1, y1, color_top, color_bottom, steps=30):
    h = y1 - y0
    for i in range(steps):
        t = i / steps
        c = lerp_color(color_top, color_bottom, t)
        y_start = y0 + int(i * h / steps)
        y_end   = y0 + int((i + 1) * h / steps)
        draw.rectangle([x0, y_start, x1, y_end], fill=c)


# ── Scene renderer ────────────────────────────────────────────────────────────

class LofiSceneRenderer:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.np_rng = np.random.RandomState(seed)

        # Pilih palette
        palette_idx = seed % len(PALETTES)
        self.pal = PALETTES[palette_idx]

        # Randomize scene elements
        self.has_cat       = self.rng.random() < 0.55
        self.has_plant     = self.rng.random() < 0.7
        self.has_coffee    = self.rng.random() < 0.8
        self.has_books     = self.rng.random() < 0.65
        self.has_lamp      = self.rng.random() < 0.9
        self.has_vinyl     = self.rng.random() < 0.45
        self.window_size   = self.rng.choice(["small", "medium", "large"])
        self.num_stars     = self.rng.randint(40, 120) if self.pal["stars"] else 0
        self.num_particles = self.rng.randint(80, 200)

        # Star positions (static)
        if self.num_stars > 0:
            self.star_x = [self.rng.randint(650, WIDTH - 20) for _ in range(self.num_stars)]
            self.star_y = [self.rng.randint(20, 350) for _ in range(self.num_stars)]
            self.star_brightness = [self.rng.uniform(0.4, 1.0) for _ in range(self.num_stars)]

        # Rain/snow particles
        if self.pal["rain"]:
            self.particles = [
                {
                    "x": self.rng.uniform(600, WIDTH),
                    "y": self.rng.uniform(0, HEIGHT),
                    "speed": self.rng.uniform(8, 18),
                    "drift": self.rng.uniform(-1, 1),
                    "length": self.rng.randint(10, 25),
                    "alpha": self.rng.uniform(0.3, 0.8),
                }
                for _ in range(self.num_particles)
            ]
        elif self.pal["snow"]:
            self.particles = [
                {
                    "x": self.rng.uniform(600, WIDTH),
                    "y": self.rng.uniform(0, HEIGHT),
                    "speed": self.rng.uniform(1, 3),
                    "drift": self.rng.uniform(-0.5, 0.5),
                    "size": self.rng.randint(2, 6),
                    "alpha": self.rng.uniform(0.5, 1.0),
                }
                for _ in range(self.num_particles)
            ]
        else:
            self.particles = []

        # Lamp flicker curve
        self.lamp_flicker = [
            0.85 + 0.15 * np.sin(i * 0.3 + self.rng.uniform(0, 3.14))
            for i in range(1000)
        ]

        # Steam offsets
        self.steam_offset = [self.rng.uniform(0, 2 * np.pi) for _ in range(5)]

        # Window position
        if self.window_size == "small":
            self.win_x, self.win_y = 700, 80
            self.win_w, self.win_h = 300, 280
        elif self.window_size == "medium":
            self.win_x, self.win_y = 680, 60
            self.win_w, self.win_h = 400, 350
        else:
            self.win_x, self.win_y = 650, 40
            self.win_w, self.win_h = 500, 420

    def render_frame(self, frame_idx: int) -> np.ndarray:
        t = frame_idx / FPS  # detik
        img = Image.new("RGB", (WIDTH, HEIGHT), self.pal["wall"])
        draw = ImageDraw.Draw(img)

        # ── Background room ────────────────────────────────────────────
        # Floor
        floor_y = int(HEIGHT * 0.65)
        draw_gradient_rect(draw, 0, floor_y, WIDTH, HEIGHT,
                           self.pal["floor"],
                           tuple(max(0, c - 20) for c in self.pal["floor"]))

        # Wall
        draw_gradient_rect(draw, 0, 0, WIDTH, floor_y,
                           tuple(min(255, c + 15) for c in self.pal["wall"]),
                           self.pal["wall"])

        # ── Window ────────────────────────────────────────────────────
        wx, wy = self.win_x, self.win_y
        ww, wh = self.win_w, self.win_h

        # Sky outside window
        sky_t = (np.sin(t * 0.005) + 1) / 2  # very slow day cycle
        sky_color = lerp_color(self.pal["sky"], self.pal["sky2"], sky_t)
        draw_gradient_rect(draw, wx, wy, wx + ww, wy + wh,
                           sky_color,
                           tuple(max(0, c - 30) for c in sky_color))

        # Stars outside window
        for i in range(self.num_stars):
            twinkle = 0.5 + 0.5 * np.sin(t * 2 + i * 0.7)
            brightness = int(self.star_brightness[i] * twinkle * 220)
            sx, sy = self.star_x[i], self.star_y[i]
            if wx <= sx <= wx + ww and wy <= sy <= wy + wh:
                draw.ellipse([sx-1, sy-1, sx+1, sy+1], fill=(brightness, brightness, brightness + 20))

        # Window frame
        frame_c = tuple(max(0, c - 30) for c in self.pal["wall"])
        draw.rectangle([wx - 8, wy - 8, wx + ww + 8, wy + wh + 8], outline=frame_c, width=6)
        # Cross bars
        draw.line([wx + ww//2, wy, wx + ww//2, wy + wh], fill=frame_c, width=4)
        draw.line([wx, wy + wh//2, wx + ww, wy + wh//2], fill=frame_c, width=4)

        # Window glow (ambient light dari luar)
        glow_intensity = 0.12 + 0.05 * np.sin(t * 0.3)
        glow_layer = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
        gd = ImageDraw.Draw(glow_layer)
        for r in range(8, 0, -1):
            alpha = int(glow_intensity * r / 8 * 255)
            gc = tuple(min(255, c) for c in self.pal["window_glow"])
            gd.rectangle(
                [wx - r*12, wy - r*6, wx + ww + r*12, wy + wh + r*6],
                fill=gc
            )
        img = Image.blend(img, glow_layer, glow_intensity * 0.15)
        draw = ImageDraw.Draw(img)

        # ── Desk / furniture ──────────────────────────────────────────
        desk_y = int(HEIGHT * 0.60)
        desk_color = tuple(max(0, c - 40) for c in self.pal["floor"])
        draw.rectangle([0, desk_y, int(WIDTH * 0.55), desk_y + 140], fill=desk_color)
        # Desk edge
        draw.rectangle([0, desk_y, int(WIDTH * 0.55), desk_y + 8],
                       fill=tuple(max(0, c - 20) for c in desk_color))

        # ── Books ─────────────────────────────────────────────────────
        if self.has_books:
            book_colors = [
                (180, 60, 60), (60, 120, 180), (80, 160, 80),
                (200, 140, 40), (140, 80, 180), (60, 160, 160),
            ]
            bx = 30
            for j, bc in enumerate(book_colors[:self.rng.randint(3, 6)]):
                bw = self.rng.randint(18, 28)
                bh = self.rng.randint(90, 140)
                by = desk_y - bh
                draw.rectangle([bx, by, bx + bw, desk_y], fill=bc)
                draw.line([bx, by, bx + bw, by], fill=tuple(max(0,c-40) for c in bc), width=2)
                bx += bw + self.rng.randint(3, 8)

        # ── Laptop / screen ───────────────────────────────────────────
        screen_x, screen_y = 200, desk_y - 180
        screen_w, screen_h = 280, 180
        draw.rectangle([screen_x, screen_y, screen_x + screen_w, screen_y + screen_h],
                       fill=(20, 22, 28), outline=(60, 60, 70), width=3)
        # Screen content: code editor simulasi
        screen_glow = int(180 + 30 * np.sin(t * 0.5))
        draw.rectangle([screen_x + 5, screen_y + 5,
                        screen_x + screen_w - 5, screen_y + screen_h - 5],
                       fill=(15, 17, 24))
        for line_i in range(8):
            line_y = screen_y + 12 + line_i * 18
            line_w = self.rng.randint(40, screen_w - 30)
            lc = [(80, 200, 120), (100, 150, 255), (255, 180, 80), (180, 100, 255)]
            draw.rectangle([screen_x + 10, line_y, screen_x + 10 + line_w, line_y + 10],
                           fill=lc[line_i % len(lc)])
        # Keyboard
        kb_y = desk_y - 20
        draw.rectangle([screen_x, kb_y, screen_x + screen_w, desk_y],
                       fill=(40, 42, 48), outline=(60, 62, 68), width=1)

        # ── Coffee mug ────────────────────────────────────────────────
        if self.has_coffee:
            mug_x, mug_y = 500, desk_y - 70
            draw.ellipse([mug_x, mug_y + 60, mug_x + 45, mug_y + 70],
                         fill=(120, 80, 50))
            draw.rectangle([mug_x, mug_y, mug_x + 45, mug_y + 65],
                           fill=(130, 90, 60))
            draw.ellipse([mug_x, mug_y, mug_x + 45, mug_y + 15],
                         fill=(160, 115, 80))
            # Coffee surface
            draw.ellipse([mug_x + 4, mug_y + 2, mug_x + 41, mug_y + 13],
                         fill=(40, 20, 10))
            # Handle
            draw.arc([mug_x + 38, mug_y + 15, mug_x + 58, mug_y + 45],
                     start=0, end=180, fill=(110, 75, 45), width=4)

            # Steam animation
            if self.has_coffee:
                for si in range(3):
                    steam_t = t * 1.5 + self.steam_offset[si]
                    sx_base = mug_x + 10 + si * 12
                    for sj in range(4):
                        st = sj / 4
                        sx = sx_base + int(8 * np.sin(steam_t + sj * 0.8)) * (1 - st)
                        sy = mug_y - int(sj * 20 * (0.5 + 0.5 * np.sin(steam_t)))
                        alpha = int(120 * (1 - st))
                        steam_c = tuple(min(255, c + 60) for c in self.pal["wall"])
                        sz = max(1, int(4 * (1 - st)))
                        draw.ellipse([sx - sz, sy - sz, sx + sz, sy + sz],
                                     fill=steam_c + (alpha,) if False else steam_c)

        # ── Desk lamp ─────────────────────────────────────────────────
        if self.has_lamp:
            lamp_x, lamp_y = 430, desk_y
            flicker_t = self.lamp_flicker[frame_idx % len(self.lamp_flicker)]
            # Pole
            draw.line([lamp_x, lamp_y, lamp_x, lamp_y - 130], fill=(90, 90, 100), width=4)
            draw.line([lamp_x, lamp_y - 130, lamp_x + 60, lamp_y - 130], fill=(90, 90, 100), width=4)
            # Shade
            shade_pts = [
                (lamp_x + 35, lamp_y - 130),
                (lamp_x + 95, lamp_y - 100),
                (lamp_x + 50, lamp_y - 95),
                (lamp_x + 20, lamp_y - 95),
                (lamp_x - 15, lamp_y - 100),
            ]
            draw.polygon(shade_pts, fill=(200, 170, 100))
            # Light pool
            pool_intensity = flicker_t * 0.25
            pool_color = tuple(int(c * pool_intensity) for c in self.pal["window_glow"])
            for r in range(6, 0, -1):
                alpha_f = r / 6
                pc = tuple(int(c * alpha_f * flicker_t) for c in self.pal["window_glow"])
                draw.ellipse([
                    lamp_x + 30 - r * 18, desk_y - r * 4,
                    lamp_x + 30 + r * 18, desk_y + r * 4
                ], fill=pc)

        # ── Plant ─────────────────────────────────────────────────────
        if self.has_plant:
            pot_x, pot_y = 540, desk_y - 60
            sway = int(3 * np.sin(t * 0.4))
            # Pot
            draw.polygon([
                (pot_x, pot_y + 55), (pot_x + 40, pot_y + 55),
                (pot_x + 35, pot_y + 65), (pot_x + 5, pot_y + 65)
            ], fill=(140, 80, 50))
            # Soil
            draw.ellipse([pot_x, pot_y + 48, pot_x + 40, pot_y + 60], fill=(60, 40, 20))
            # Leaves
            leaf_c = (50, 140, 70)
            for li in range(5):
                angle = (li / 5) * 2 * np.pi + t * 0.1
                lx = pot_x + 20 + sway + int(30 * np.cos(angle))
                ly = pot_y + 20 + int(20 * np.sin(angle * 0.5))
                draw.ellipse([lx - 12, ly - 20, lx + 12, ly + 5], fill=leaf_c)

        # ── Vinyl record ──────────────────────────────────────────────
        if self.has_vinyl:
            vx, vy = 100, desk_y - 80
            spin = t * 45  # degrees
            draw.ellipse([vx, vy, vx + 70, vy + 70], fill=(20, 20, 20))
            # Grooves
            for r in range(3, 33, 4):
                draw.ellipse([vx + 35 - r, vy + 35 - r, vx + 35 + r, vy + 35 + r],
                             outline=(40, 40, 40), width=1)
            # Label
            draw.ellipse([vx + 20, vy + 20, vx + 50, vy + 50], fill=(180, 60, 60))
            draw.ellipse([vx + 32, vy + 32, vx + 38, vy + 38], fill=(20, 20, 20))

        # ── Cat ───────────────────────────────────────────────────────
        if self.has_cat:
            cat_x = int(WIDTH * 0.52)
            cat_y = desk_y - 60
            blink = (int(t * 2) % 8 == 0)
            # Body
            draw.ellipse([cat_x, cat_y + 20, cat_x + 60, cat_y + 60], fill=(80, 70, 65))
            # Head
            draw.ellipse([cat_x + 10, cat_y - 5, cat_x + 50, cat_y + 35], fill=(80, 70, 65))
            # Ears
            draw.polygon([(cat_x + 12, cat_y), (cat_x + 20, cat_y - 20), (cat_x + 28, cat_y)],
                         fill=(80, 70, 65))
            draw.polygon([(cat_x + 32, cat_y), (cat_x + 40, cat_y - 20), (cat_x + 48, cat_y)],
                         fill=(80, 70, 65))
            # Eyes
            if not blink:
                draw.ellipse([cat_x + 17, cat_y + 8, cat_x + 25, cat_y + 16], fill=(60, 180, 60))
                draw.ellipse([cat_x + 33, cat_y + 8, cat_x + 41, cat_y + 16], fill=(60, 180, 60))
                draw.ellipse([cat_x + 19, cat_y + 10, cat_x + 23, cat_y + 14], fill=(10, 10, 10))
                draw.ellipse([cat_x + 35, cat_y + 10, cat_x + 39, cat_y + 14], fill=(10, 10, 10))
            else:
                draw.line([cat_x + 17, cat_y + 12, cat_x + 25, cat_y + 12],
                          fill=(40, 35, 30), width=3)
                draw.line([cat_x + 33, cat_y + 12, cat_x + 41, cat_y + 12],
                          fill=(40, 35, 30), width=3)
            # Whiskers
            draw.line([cat_x + 10, cat_y + 22, cat_x - 10, cat_y + 20], fill=(200, 200, 200), width=1)
            draw.line([cat_x + 10, cat_y + 25, cat_x - 10, cat_y + 25], fill=(200, 200, 200), width=1)
            draw.line([cat_x + 48, cat_y + 22, cat_x + 68, cat_y + 20], fill=(200, 200, 200), width=1)
            draw.line([cat_x + 48, cat_y + 25, cat_x + 68, cat_y + 25], fill=(200, 200, 200), width=1)
            # Tail
            tail_t = np.sin(t * 1.2) * 20
            draw.arc([cat_x - 30, cat_y + 30 + int(tail_t),
                      cat_x + 20, cat_y + 80], start=0, end=180, fill=(80, 70, 65), width=6)

        # ── Rain / snow particles ─────────────────────────────────────
        for p in self.particles:
            px = p["x"]
            py = p["y"]

            # Check if particle is in window area
            in_window = (wx <= px <= wx + ww and wy <= py <= wy + wh)
            if not in_window:
                continue

            alpha = int(p["alpha"] * 200)
            rain_c = tuple(min(255, c + 80) for c in sky_color)

            if self.pal["rain"]:
                ex = px + p["drift"] * 3
                ey = py + p["length"]
                draw.line([int(px), int(py), int(ex), int(ey)],
                          fill=rain_c + (alpha,) if False else rain_c,
                          width=1)
            elif self.pal["snow"]:
                sz = p["size"]
                draw.ellipse([int(px) - sz, int(py) - sz,
                               int(px) + sz, int(py) + sz],
                             fill=(230, 240, 255))

        # ── Text overlay: judul dan info ──────────────────────────────
        text_alpha = min(255, int((t % 30) / 2 * 255) if t % 30 < 2 else 255)
        text_alpha = min(text_alpha, int((30 - t % 30) / 2 * 255) if t % 30 > 28 else text_alpha)

        scene_name = self.pal["name"].replace("_", " ").title()
        try:
            font_large = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", 36)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", 22)
        except Exception:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()

        # Title
        draw.text((40, HEIGHT - 80), "lofi beats to study / relax to",
                  fill=(220, 200, 255), font=font_large)
        draw.text((40, HEIGHT - 42), f"✦ {scene_name}",
                  fill=(160, 140, 200), font=font_small)

        # ── Grain overlay ─────────────────────────────────────────────
        arr = np.array(img)
        arr = add_noise(arr, intensity=4)
        img = Image.fromarray(arr)

        # Subtle vignette
        vignette = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
        vd = ImageDraw.Draw(vignette)
        for r in range(20, 0, -1):
            margin = r * 30
            alpha_v = int((20 - r) / 20 * 60)
            vd.rectangle([margin, margin, WIDTH - margin, HEIGHT - margin],
                         fill=(alpha_v, alpha_v, alpha_v))
        img = Image.blend(img, vignette, 0.3)

        return np.array(img)

    def update_particles(self):
        """Update posisi partikel untuk frame berikutnya."""
        for p in self.particles:
            if self.pal["rain"]:
                p["y"] += p["speed"]
                p["x"] += p["drift"]
                if p["y"] > HEIGHT or p["x"] < self.win_x or p["x"] > self.win_x + self.win_w:
                    p["y"] = self.win_y
                    p["x"] = random.uniform(self.win_x, self.win_x + self.win_w)
            elif self.pal["snow"]:
                p["y"] += p["speed"]
                p["x"] += p["drift"]
                if p["y"] > self.win_y + self.win_h:
                    p["y"] = self.win_y
                    p["x"] = random.uniform(self.win_x, self.win_x + self.win_w)


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate lofi animation")
    parser.add_argument("--seed",     type=int, required=True)
    parser.add_argument("--output",   type=str, required=True)
    parser.add_argument("--duration", type=int, default=3600)
    parser.add_argument("--loop-dur", type=int, default=30,
                        help="Durasi loop animasi dalam detik (sisanya looping)")
    args = parser.parse_args()

    scene = LofiSceneRenderer(args.seed)
    loop_frames = args.loop_dur * FPS
    total_frames = loop_frames  # Kita render loop pendek, lalu ffmpeg loop-kan

    print(f"🎨 Rendering {loop_frames} frames ({args.loop_dur}s loop) "
          f"| scene: {scene.pal['name']} | seed: {args.seed}")

    tmpdir = tempfile.mkdtemp(prefix="lofi_frames_")

    try:
        for fi in range(total_frames):
            frame = scene.render_frame(fi)
            img = Image.fromarray(frame)
            img.save(os.path.join(tmpdir, f"frame_{fi:05d}.png"))
            scene.update_particles()

            if fi % (FPS * 5) == 0:
                print(f"  Frame {fi}/{total_frames} ({fi/FPS:.0f}s)")

        print(f"✅ {total_frames} frames rendered")

        # Buat video loop {loop_dur}s, lalu extend ke durasi penuh dengan -stream_loop
        loop_video = os.path.join(tmpdir, "loop.mp4")
        cmd_make_loop = [
            "ffmpeg", "-y",
            "-framerate", str(FPS),
            "-i", os.path.join(tmpdir, "frame_%05d.png"),
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-pix_fmt", "yuv420p",
            loop_video
        ]
        r = subprocess.run(cmd_make_loop, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"ffmpeg loop error: {r.stderr[:400]}")
            sys.exit(1)

        # Loop video ke durasi penuh
        loops_needed = (args.duration // args.loop_dur) + 2
        cmd_extend = [
            "ffmpeg", "-y",
            "-stream_loop", str(loops_needed),
            "-i", loop_video,
            "-t", str(args.duration),
            "-c:v", "copy",
            args.output
        ]
        r = subprocess.run(cmd_extend, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"ffmpeg extend error: {r.stderr[:400]}")
            sys.exit(1)

        size_mb = os.path.getsize(args.output) / (1024 * 1024)
        print(f"✅ Animation: {args.output} ({size_mb:.1f} MB)")

    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
