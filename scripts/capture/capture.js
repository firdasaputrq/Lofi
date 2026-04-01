/**
 * capture.js
 * Membuka lofi.jacobzhang.de di Chrome headless,
 * menekan tombol play, lalu merekam audio via FFmpeg dari PulseAudio VirtualSink.
 *
 * Tidak lagi menggunakan puppeteer-stream (deprecated/abandoned).
 * Audio direkam langsung dari virtual sink PulseAudio yang sudah disetup di workflow.
 */

const puppeteer = require('puppeteer');
const { spawn } = require('child_process');
const fs = require('fs');
const yargs = require('yargs');

const argv = yargs
  .option('duration', {
    alias: 'd',
    type: 'number',
    description: 'Durasi rekaman dalam menit',
    default: 60
  })
  .option('output', {
    alias: 'o',
    type: 'string',
    description: 'Path output file',
    default: '/tmp/lofi_audio.webm'
  })
  .argv;

const DURATION_SEC = argv.duration * 60;
const OUTPUT_PATH = argv.output;
const LOFI_URL = 'https://lofi.jacobzhang.de/?default';
const WARMUP_MS = 8000;

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function startFfmpegRecording(outputPath, durationSec) {
  const pulseSink = process.env.PULSE_SINK || 'VirtualSink';
  const pulseSource = `${pulseSink}.monitor`;

  console.log(`[capture] FFmpeg merekam dari PulseAudio source: ${pulseSource}`);

  const ffmpeg = spawn('ffmpeg', [
    '-y',
    '-f', 'pulse',
    '-i', pulseSource,
    '-t', String(durationSec),
    '-acodec', 'libopus',
    '-ab', '192k',
    '-ar', '48000',
    outputPath,
  ], {
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  ffmpeg.stdout.on('data', d => process.stdout.write(d));
  ffmpeg.stderr.on('data', d => process.stderr.write(d));

  ffmpeg.on('error', err => {
    console.error(`[capture] FFmpeg spawn error: ${err.message}`);
  });

  return ffmpeg;
}

async function captureLofi() {
  console.log(`[capture] Mulai capture ${argv.duration} menit -> ${OUTPUT_PATH}`);
  console.log(`[capture] URL: ${LOFI_URL}`);

  const browser = await puppeteer.launch({
    executablePath: '/usr/bin/google-chrome-stable',
    defaultViewport: { width: 1280, height: 720 },
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-gpu',
      '--disable-web-security',
      '--autoplay-policy=no-user-gesture-required',
      '--use-fake-ui-for-media-stream',
      `--display=${process.env.DISPLAY || ':99'}`,
    ],
  });

  const page = await browser.newPage();

  const context = browser.defaultBrowserContext();
  await context.overridePermissions(LOFI_URL, ['microphone', 'camera']);

  page.on('console', msg => {
    if (msg.type() === 'error') {
      console.log(`[page-error] ${msg.text()}`);
    }
  });

  console.log('[capture] Membuka URL...');
  await page.goto(LOFI_URL, { waitUntil: 'networkidle2', timeout: 60000 });
  console.log('[capture] Halaman dimuat');

  await sleep(3000);

  // Klik tombol play
  console.log('[capture] Mencari tombol play...');
  try {
    const playSelectors = [
      '#play-button',
      '.play-button',
      'button[aria-label="play"]',
      'button.play',
      '[class*="play"]',
      'button',
    ];

    let clicked = false;
    for (const selector of playSelectors) {
      try {
        const el = await page.$(selector);
        if (el) {
          await el.click();
          console.log(`[capture] Klik berhasil: ${selector}`);
          clicked = true;
          break;
        }
      } catch (e) { /* lanjut */ }
    }

    if (!clicked) {
      await page.keyboard.press('Space');
      console.log('[capture] Coba spacebar sebagai play');
    }

    await page.evaluate(() => {
      if (window.Tone && window.Tone.context) {
        window.Tone.context.resume();
      }
      document.querySelectorAll('button, [role="button"]').forEach(b => {
        const text = b.textContent.toLowerCase();
        const cls = b.className.toLowerCase();
        if (text.includes('play') || cls.includes('play') || cls.includes('start')) {
          b.click();
        }
      });
    });

  } catch (e) {
    console.log(`[capture] Peringatan saat klik play: ${e.message}`);
  }

  // Warmup sebelum mulai rekam
  console.log(`[capture] Warmup ${WARMUP_MS / 1000} detik...`);
  await sleep(WARMUP_MS);

  // Mulai FFmpeg recording
  console.log('[capture] Mulai merekam via FFmpeg + PulseAudio...');
  const ffmpeg = startFfmpegRecording(OUTPUT_PATH, DURATION_SEC);

  // Progress indicator
  const startTime = Date.now();
  const progressInterval = setInterval(() => {
    const elapsed = Math.floor((Date.now() - startTime) / 60000);
    const remaining = argv.duration - elapsed;
    console.log(`[capture] Progress: ${elapsed}/${argv.duration} menit (sisa ${remaining} menit)`);
  }, 60000);

  // Tunggu FFmpeg selesai (duration-limited otomatis via -t flag)
  await new Promise((resolve, reject) => {
    ffmpeg.on('close', code => {
      clearInterval(progressInterval);
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`FFmpeg keluar dengan kode: ${code}`));
      }
    });
  });

  console.log('[capture] Rekaman selesai, menutup browser...');
  await browser.close();

  // Verifikasi output
  const stats = fs.statSync(OUTPUT_PATH);
  console.log(`[capture] File berhasil: ${OUTPUT_PATH} (${(stats.size / 1024 / 1024).toFixed(2)} MB)`);

  if (stats.size < 100000) {
    throw new Error(`File output terlalu kecil (${stats.size} bytes) - kemungkinan audio tidak ter-capture`);
  }

  console.log('[capture] Selesai!');
}

captureLofi().catch(err => {
  console.error('[capture] ERROR:', err);
  process.exit(1);
});
