#!/usr/bin/env python3
"""
generate_metadata.py
Generate judul, deskripsi, dan tags YouTube yang unik setiap video.
Semua berbasis seed agar konsisten tapi tidak repetitif.
"""

import argparse
import json
import random
from datetime import datetime


# ── Template bank ──────────────────────────────────────────────────────────────

TITLE_TEMPLATES = [
    "{mood} lofi hip hop ~ {activity} beats",
    "lofi {time_of_day} ☕ {activity} music",
    "{mood} lofi ~ beats to {activity} to",
    "1 hour of {mood} lofi beats · {theme}",
    "{theme} lofi 🎵 {activity} & study music",
    "late night lofi ~ {mood} beats for {activity}",
    "{mood} lofi radio 📻 {theme} vibes",
    "cozy lofi beats · {time_of_day} {activity}",
    "{mood} lo-fi hip hop · 1 hour · {theme}",
    "lofi {theme} 🌧️ {activity} music mix",
]

MOODS = [
    "chill", "dreamy", "mellow", "rainy day", "cozy", "peaceful",
    "nostalgic", "sleepy", "cloudy", "misty", "warm", "soft",
    "gentle", "calm", "hazy", "breezy", "foggy", "tender",
]

ACTIVITIES = [
    "study", "work", "relax", "sleep", "focus", "code",
    "read", "draw", "write", "think", "create", "chill",
    "unwind", "meditate", "breathe", "rest",
]

TIMES = [
    "morning", "afternoon", "evening", "night", "late night",
    "golden hour", "midnight", "dawn", "dusk", "3am",
]

THEMES = [
    "cafe", "bedroom", "rainy window", "city lights", "forest",
    "library", "studio", "apartment", "rooftop", "jazz club",
    "coffee shop", "autumn leaves", "winter night", "spring breeze",
    "neon city", "quiet room", "old town",
]

DESCRIPTION_INTROS = [
    "Take a break and let the music carry you away.",
    "A full hour of handcrafted lofi beats, generated uniquely for this session.",
    "Close your eyes, breathe, and let the chill vibes wash over you.",
    "Perfect background music for your productive session.",
    "No two sessions sound alike — every beat is uniquely generated.",
    "Let the gentle melodies accompany your study or work session.",
    "Sit back, sip your coffee, and enjoy the flow.",
    "Crafted with care — each melody freshly composed just for you.",
]

DESCRIPTION_BODIES = [
    "This session was procedurally generated using a VAE (Variational Autoencoder) model trained on thousands of lo-fi tracks. Every chord, melody, and rhythm is unique to this upload.",
    "Built with an ML model that understands the language of lo-fi — chord progressions, swing rhythms, dusty textures, and that perfect mellow mood.",
    "Generated using deep learning techniques trained on real lo-fi compositions. The result is music that feels familiar yet fresh every time.",
    "Each upload is a one-of-a-kind musical experience. The AI model samples from a latent space of musical parameters to create something new.",
]

TAGS_BASE = [
    "lofi", "lo-fi", "lofi hip hop", "lofi beats", "study music",
    "chill music", "relaxing music", "focus music", "background music",
    "work music", "lofi radio", "lofi mix", "lofi 1 hour",
    "chillhop", "lofi chillhop", "jazz lofi", "lofi jazz",
    "anime lofi", "lofi anime", "beats to study to", "beats to relax to",
    "lofi hip hop radio", "study beats", "chill beats", "calm music",
    "sleep music", "meditation music", "deep focus", "concentration music",
]

TAGS_EXTRA = [
    ["rainy day lofi", "rain music", "rainy lofi", "lofi rain"],
    ["cozy lofi", "winter lofi", "snow lofi", "cozy music"],
    ["late night lofi", "midnight lofi", "lofi night", "night music"],
    ["morning lofi", "lofi morning", "coffee music", "morning music"],
    ["lofi cafe", "coffee shop music", "cafe music", "lofi coffee"],
    ["bedroom lofi", "bedroom beats", "lofi bedroom", "chill bedroom"],
]


def generate_metadata(seed: int) -> dict:
    rng = random.Random(seed)
    now = datetime.utcnow()

    mood     = rng.choice(MOODS)
    activity = rng.choice(ACTIVITIES)
    time_of_day = rng.choice(TIMES)
    theme    = rng.choice(THEMES)

    title_tmpl = rng.choice(TITLE_TEMPLATES)
    title = title_tmpl.format(
        mood=mood,
        activity=activity,
        time_of_day=time_of_day,
        theme=theme,
    )

    intro  = rng.choice(DESCRIPTION_INTROS)
    body   = rng.choice(DESCRIPTION_BODIES)

    description = f"""{intro}

{body}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Track info:
• Duration: 1 hour
• Generated: {now.strftime('%B %Y')}
• Seed: #{seed}
• Mood: {mood.title()}
• Theme: {theme.title()}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

No copyright — free to use for studying, streaming, or just chilling.
Subscribe for new sessions uploaded automatically throughout the day.

#lofi #lofihiphop #studymusic #chillbeats #lofibeats"""

    # Tags: base + extra dari tema yang dipilih
    extra_tags = rng.choice(TAGS_EXTRA)
    mood_tags  = [mood + " lofi", "lofi " + mood, mood + " music"]
    theme_tags = [theme + " lofi", "lofi " + theme]
    all_tags   = list(dict.fromkeys(
        TAGS_BASE + extra_tags + mood_tags + theme_tags
    ))
    rng.shuffle(all_tags)
    tags = all_tags[:30]  # YouTube max ~500 chars, ~30 tags

    return {
        "title": title,
        "description": description,
        "tags": tags,
        "category_id": "10",  # Music
        "privacy": "public",
        "made_for_kids": False,
        "language": "en",
        "seed": seed,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed",   type=int,  required=True)
    parser.add_argument("--output", type=str,  required=True)
    args = parser.parse_args()

    metadata = generate_metadata(args.seed)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"📝 Metadata generated:")
    print(f"   Title: {metadata['title']}")
    print(f"   Tags: {', '.join(metadata['tags'][:8])}...")
    print(f"   Saved: {args.output}")


if __name__ == "__main__":
    main()
