#!/usr/bin/env node
/**
 * render.js — Headless Tone.js audio renderer
 *
 * Menerima parameter musik dari jacbz/Lofi VAE model (via CLI --params JSON),
 * merender audio secara offline (tidak butuh sound card nyata),
 * dan menyimpan ke file WAV.
 *
 * Cara pakai:
 *   node render.js --params '{"chords":[1,4,5,4],...}' --duration 240 --output /tmp/track.wav
 */

"use strict";

const argv     = require("minimist")(process.argv.slice(2));
const wav      = require("node-wav");
const fs       = require("fs");
const path     = require("path");

// Tone.js berjalan di Node via Web Audio API polyfill
// Untuk environment GitHub Actions, kita gunakan OfflineAudioContext dari web-audio-api
const { OfflineAudioContext } = require("web-audio-api");

// ── CLI args ────────────────────────────────────────────────────────────────
const params   = JSON.parse(argv.params || "{}");
const duration = parseInt(argv.duration || "240", 10);
const output   = argv.output || "/tmp/lofi_track.wav";
const SAMPLE_RATE = 44100;

// ── Music theory helpers ─────────────────────────────────────────────────────

const NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

// Mode intervals (semitones dari root)
const MODE_INTERVALS = {
  1: [0, 2, 4, 5, 7, 9, 11],  // Ionian (major)
  2: [0, 2, 3, 5, 7, 9, 10],  // Dorian
  3: [0, 1, 3, 5, 7, 8, 10],  // Phrygian
  4: [0, 2, 4, 6, 7, 9, 11],  // Lydian
  5: [0, 2, 4, 5, 7, 9, 10],  // Mixolydian
  6: [0, 2, 3, 5, 7, 8, 10],  // Aeolian (natural minor)
  7: [0, 1, 3, 5, 6, 8, 10],  // Locrian
};

// Roman numeral chord → scale degree (0-indexed)
const CHORD_DEGREE = { 1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6 };

function getScaleNotes(key, mode) {
  const intervals = MODE_INTERVALS[mode] || MODE_INTERVALS[1];
  return intervals.map(i => (key - 1 + i) % 12);
}

function noteToFreq(midiNote) {
  return 440 * Math.pow(2, (midiNote - 69) / 12);
}

function scaleDegreesToMidi(degree, scalePCs, octave = 4) {
  if (degree === 0) return null; // rest
  const pc = scalePCs[(degree - 1) % scalePCs.length];
  const oct = octave + Math.floor((degree - 1) / scalePCs.length);
  return pc + (oct + 1) * 12;
}

function chordToMidiNotes(romanNumeral, scalePCs, octave = 3) {
  if (!romanNumeral || romanNumeral === 0 || romanNumeral === 8) return [];
  const degree = CHORD_DEGREE[romanNumeral] || 0;
  const root   = scalePCs[degree];
  const third  = scalePCs[(degree + 2) % 7];
  const fifth  = scalePCs[(degree + 4) % 7];
  return [
    root  + (octave + 1) * 12,
    third + (octave + 1) * 12 + (third < root ? 12 : 0),
    fifth + (octave + 1) * 12 + (fifth < root ? 12 : 0),
  ];
}

// ── Audio synthesis primitives ───────────────────────────────────────────────

function createSawOscillator(ctx, freq, gain, startTime, endTime) {
  const osc = ctx.createOscillator();
  const gainNode = ctx.createGain();

  osc.type = "sawtooth";
  osc.frequency.value = freq;

  // Soft attack/release envelope
  gainNode.gain.setValueAtTime(0, startTime);
  gainNode.gain.linearRampToValueAtTime(gain, startTime + 0.02);
  gainNode.gain.setValueAtTime(gain, endTime - 0.05);
  gainNode.gain.linearRampToValueAtTime(0, endTime);

  osc.connect(gainNode);
  osc.start(startTime);
  osc.stop(endTime);

  return gainNode;
}

function createPianoNote(ctx, freq, gain, startTime, duration) {
  // Simulated piano dengan sine + harmonics
  const gainNode = ctx.createGain();
  const harmonics = [1, 2, 3, 4];
  const harmonicGains = [1.0, 0.5, 0.25, 0.1];

  harmonics.forEach((h, i) => {
    const osc = ctx.createOscillator();
    const hGain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = freq * h;

    // Piano-like envelope: quick attack, exponential decay
    hGain.gain.setValueAtTime(0, startTime);
    hGain.gain.linearRampToValueAtTime(gain * harmonicGains[i], startTime + 0.005);
    hGain.gain.exponentialRampToValueAtTime(
      Math.max(gain * harmonicGains[i] * 0.1, 0.0001),
      startTime + duration * 0.7
    );
    hGain.gain.linearRampToValueAtTime(0.0001, startTime + duration);

    osc.connect(hGain);
    hGain.connect(gainNode);
    osc.start(startTime);
    osc.stop(startTime + duration + 0.1);
  });

  gainNode.gain.value = 1.0;
  return gainNode;
}

function createKick(ctx, startTime) {
  const gainNode = ctx.createGain();
  const osc = ctx.createOscillator();

  osc.type = "sine";
  osc.frequency.setValueAtTime(150, startTime);
  osc.frequency.exponentialRampToValueAtTime(40, startTime + 0.08);

  gainNode.gain.setValueAtTime(0.8, startTime);
  gainNode.gain.exponentialRampToValueAtTime(0.001, startTime + 0.3);

  osc.connect(gainNode);
  osc.start(startTime);
  osc.stop(startTime + 0.35);

  return gainNode;
}

function createHihat(ctx, startTime, open = false) {
  const bufferSize = ctx.sampleRate * (open ? 0.3 : 0.05);
  const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < bufferSize; i++) {
    data[i] = (Math.random() * 2 - 1);
  }

  const source = ctx.createBufferSource();
  source.buffer = buffer;

  const filter = ctx.createBiquadFilter();
  filter.type = "highpass";
  filter.frequency.value = 8000;

  const gainNode = ctx.createGain();
  gainNode.gain.setValueAtTime(open ? 0.15 : 0.08, startTime);
  gainNode.gain.exponentialRampToValueAtTime(0.001, startTime + (open ? 0.3 : 0.05));

  source.connect(filter);
  filter.connect(gainNode);
  source.start(startTime);

  return gainNode;
}

function createSnare(ctx, startTime) {
  const bufferSize = ctx.sampleRate * 0.2;
  const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < bufferSize; i++) {
    data[i] = (Math.random() * 2 - 1) * Math.exp(-i / (ctx.sampleRate * 0.05));
  }

  const source = ctx.createBufferSource();
  source.buffer = buffer;

  const osc = ctx.createOscillator();
  const oscGain = ctx.createGain();
  osc.type = "triangle";
  osc.frequency.value = 220;
  oscGain.gain.setValueAtTime(0.3, startTime);
  oscGain.gain.exponentialRampToValueAtTime(0.001, startTime + 0.1);

  const gainNode = ctx.createGain();
  gainNode.gain.setValueAtTime(0.4, startTime);
  gainNode.gain.exponentialRampToValueAtTime(0.001, startTime + 0.2);

  source.connect(gainNode);
  osc.connect(oscGain);
  oscGain.connect(gainNode);

  osc.start(startTime);
  osc.stop(startTime + 0.25);
  source.start(startTime);

  return gainNode;
}

function createVinylNoise(ctx, level, duration) {
  const bufferSize = ctx.sampleRate * Math.min(duration, 10);
  const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
  const data = buffer.getChannelData(0);

  // Pink noise approximation
  let b0=0, b1=0, b2=0, b3=0, b4=0, b5=0;
  for (let i = 0; i < bufferSize; i++) {
    const w = Math.random() * 2 - 1;
    b0 = 0.99886 * b0 + w * 0.0555179;
    b1 = 0.99332 * b1 + w * 0.0750759;
    b2 = 0.96900 * b2 + w * 0.1538520;
    b3 = 0.86650 * b3 + w * 0.3104856;
    b4 = 0.55000 * b4 + w * 0.5329522;
    b5 = -0.7616 * b5 - w * 0.0168980;
    data[i] = (b0 + b1 + b2 + b3 + b4 + b5 + w * 0.5362) * 0.11;
  }

  const source = ctx.createBufferSource();
  source.buffer = buffer;
  source.loop = true;

  const gainNode = ctx.createGain();
  gainNode.gain.value = level * 0.04;

  source.connect(gainNode);
  source.start(0);

  return gainNode;
}

function createSimpleReverb(ctx, decay = 2.0) {
  const convolver = ctx.createConvolver();
  const length = ctx.sampleRate * decay;
  const impulse = ctx.createBuffer(2, length, ctx.sampleRate);

  for (let c = 0; c < 2; c++) {
    const data = impulse.getChannelData(c);
    for (let i = 0; i < length; i++) {
      data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / length, 2);
    }
  }
  convolver.buffer = impulse;
  return convolver;
}

// ── Main renderer ────────────────────────────────────────────────────────────

async function renderLofi(params, durationSecs) {
  const ctx = new OfflineAudioContext(2, SAMPLE_RATE * durationSecs, SAMPLE_RATE);

  // Extract params dengan defaults yang masuk akal
  const chords      = params.chords      || [1, 4, 5, 4];
  const melodies    = params.melodies    || chords.map(() => [0,3,5,7,5,3,2,0]);
  const tempo       = params.tempo       || 0.4;
  const key         = params.key         || 1;
  const mode        = params.mode        || 2;  // Dorian = lofi default
  const swing       = params.swing       || 0.55;
  const vinylLevel  = params.vinyl_noise || 0.35;
  const reverbLevel = params.reverb      || 0.5;
  const bassLevel   = params.bass_level  || 0.6;
  const drumLevel   = params.drum_level  || 0.45;

  // BPM: tempo [0,1] → [60, 100] BPM (lofi range)
  const bpm          = 60 + tempo * 40;
  const beatDuration = 60 / bpm;
  const barDuration  = beatDuration * 4;
  const numChords    = chords.length;
  const loopDuration = barDuration * numChords;

  const scalePCs = getScaleNotes(key, mode);

  // Master chain
  const masterGain = ctx.createGain();
  masterGain.gain.value = 0.7;

  // Reverb
  const reverb = createSimpleReverb(ctx, 1.5 + reverbLevel);
  const reverbGain = ctx.createGain();
  reverbGain.gain.value = reverbLevel * 0.4;

  masterGain.connect(ctx.destination);
  masterGain.connect(reverb);
  reverb.connect(reverbGain);
  reverbGain.connect(ctx.destination);

  // Vinyl noise (seluruh durasi)
  const vinyl = createVinylNoise(ctx, vinylLevel, durationSecs);
  vinyl.connect(ctx.destination);

  // Low-pass filter untuk karakter lofi
  const lofiFilter = ctx.createBiquadFilter();
  lofiFilter.type = "lowpass";
  lofiFilter.frequency.value = 3500 + (1 - tempo) * 2000;
  lofiFilter.Q.value = 0.7;
  masterGain.connect(lofiFilter);
  lofiFilter.disconnect();  // akan di-connect nanti per instrumen

  // ── Schedule semua loop selama durationSecs ──────────────────────────────
  let t = 0;
  let loopIndex = 0;

  while (t < durationSecs - beatDuration) {
    const chordIdx = loopIndex % numChords;
    const chord    = chords[chordIdx];
    const melody   = melodies[chordIdx] || [];

    // ── Chord (piano chords, satu bar) ──────────────────────────────────
    const chordMidis = chordToMidiNotes(chord, scalePCs, 3);
    chordMidis.forEach(midi => {
      if (midi && t < durationSecs) {
        const freq = noteToFreq(midi);
        const note = createPianoNote(ctx, freq, 0.18, t, barDuration * 0.9);
        note.connect(masterGain);
      }
    });

    // ── Bass (root note, bergerak setiap beat) ───────────────────────────
    if (chord && chord !== 0 && chord !== 8) {
      const degree  = CHORD_DEGREE[chord] || 0;
      const rootPC  = scalePCs[degree];
      const bassMidi = rootPC + 3 * 12;  // oktaf rendah
      const bassFreq = noteToFreq(bassMidi);

      for (let beat = 0; beat < 4; beat++) {
        const beatT = t + beat * beatDuration;
        if (beatT >= durationSecs) break;
        if (beat === 0 || (beat === 2 && Math.random() < 0.7)) {
          const bassNote = createSawOscillator(
            ctx, bassFreq, bassLevel * 0.3,
            beatT, beatT + beatDuration * 0.8
          );
          // Bass filter
          const bassFilter = ctx.createBiquadFilter();
          bassFilter.type = "lowpass";
          bassFilter.frequency.value = 300;
          bassNote.connect(bassFilter);
          bassFilter.connect(masterGain);
        }
      }
    }

    // ── Melodi (8 note per chord, tersebar dalam 1 bar) ─────────────────
    const noteStep = barDuration / 8;
    melody.forEach((degree, noteIdx) => {
      const noteT = t + noteIdx * noteStep;
      if (degree === 0 || noteT >= durationSecs) return;

      // Swing: note ganjil sedikit terlambat
      const swingOffset = (noteIdx % 2 === 1)
        ? (swing - 0.5) * noteStep * 0.5
        : 0;
      const actualT = noteT + swingOffset;

      const midi = scaleDegreesToMidi(degree, scalePCs, 4);
      if (!midi) return;

      const freq = noteToFreq(midi);
      const note = createPianoNote(ctx, freq, 0.25, actualT, noteStep * 0.85);
      note.connect(masterGain);
    });

    // ── Drums (lofi beat pattern: kick-snare-hat) ────────────────────────
    for (let beat = 0; beat < 4; beat++) {
      const beatT = t + beat * beatDuration;
      if (beatT >= durationSecs) break;

      // Kick: beat 1 dan 3 (+ occasional extra)
      if (beat === 0 || beat === 2 || (beat === 3 && Math.random() < 0.2)) {
        const kick = createKick(ctx, beatT);
        const kickGain = ctx.createGain();
        kickGain.gain.value = drumLevel;
        kick.connect(kickGain);
        kickGain.connect(ctx.destination);
      }

      // Snare: beat 2 dan 4
      if (beat === 1 || beat === 3) {
        const snare = createSnare(ctx, beatT + (swing - 0.5) * beatDuration * 0.1);
        const snareGain = ctx.createGain();
        snareGain.gain.value = drumLevel * 0.7;
        snare.connect(snareGain);
        snareGain.connect(ctx.destination);
      }

      // Hi-hats: setiap 8th note
      for (let eighth = 0; eighth < 2; eighth++) {
        const hatT = beatT + eighth * (beatDuration / 2);
        if (hatT >= durationSecs) break;
        const swingHat = (eighth === 1) ? (swing - 0.5) * beatDuration * 0.25 : 0;
        const isOpen = (beat === 1 && eighth === 1) || (beat === 3 && eighth === 1);
        const hat = createHihat(ctx, hatT + swingHat, isOpen);
        const hatGain = ctx.createGain();
        hatGain.gain.value = drumLevel * 0.5;
        hat.connect(hatGain);
        hatGain.connect(ctx.destination);
      }
    }

    t += barDuration;
    loopIndex++;
  }

  console.log(`  Rendering ${durationSecs}s @ ${bpm.toFixed(1)} BPM, key=${NOTES[key-1]}, mode=${mode}...`);

  // Render offline
  const renderedBuffer = await ctx.startRendering();
  return renderedBuffer;
}

function bufferToWav(audioBuffer) {
  const numChannels = audioBuffer.numberOfChannels;
  const length      = audioBuffer.length;
  const sampleRate  = audioBuffer.sampleRate;

  const channels = [];
  for (let c = 0; c < numChannels; c++) {
    channels.push(audioBuffer.getChannelData(c));
  }

  // Interleave
  const interleaved = new Float32Array(length * numChannels);
  for (let i = 0; i < length; i++) {
    for (let c = 0; c < numChannels; c++) {
      interleaved[i * numChannels + c] = channels[c][i];
    }
  }

  // Convert to 16-bit PCM
  const pcm = new Int16Array(interleaved.length);
  for (let i = 0; i < interleaved.length; i++) {
    const s = Math.max(-1, Math.min(1, interleaved[i]));
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }

  return wav.encode([channels[0], channels[1] || channels[0]], {
    sampleRate,
    float: false,
    bitDepth: 16,
  });
}

// ── Entry point ───────────────────────────────────────────────────────────────

(async () => {
  if (argv.help || argv.h) {
    console.log("Usage: node render.js --params '{...}' --duration 240 --output /tmp/out.wav");
    process.exit(0);
  }

  if (!argv.params) {
    console.error("Missing --params");
    process.exit(1);
  }

  try {
    const audioBuffer = await renderLofi(params, duration);
    const wavData     = bufferToWav(audioBuffer);
    fs.writeFileSync(output, Buffer.from(wavData));
    console.log(`  ✅ Saved: ${output} (${(wavData.byteLength / 1024 / 1024).toFixed(2)} MB)`);
  } catch (err) {
    console.error("Render error:", err);
    process.exit(1);
  }
})();
