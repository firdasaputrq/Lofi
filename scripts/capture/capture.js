/**
 * capture.js
 * Membuka lofi.jacobzhang.de di Chrome headless,
 * menekan tombol play, lalu merekam audio selama durasi yang ditentukan.
 *
 * FIXES:
 * - Hapus --disable-gpu yang memblokir Web Audio API
 * - Tambah flag audio yang lebih lengkap
 * - Tambah verifikasi bahwa audio benar-benar terekam
 * - Gunakan puppeteer v19 yang kompatibel dengan puppeteer-stream
 */

const { launch, getStream } = require('puppeteer-stream');
const fs = require('fs');
const path = require('path');
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

const DURATION_MS = argv.duration * 60 * 1000;
const OUTPUT_PATH = argv.output;
const LOFI_URL = 'https://lofi.jacobzhang.de/?default';
const WARMUP_MS = 10000;

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function captureLofi() {
  console.log(`[capture] Mulai capture ${argv.duration} menit -> ${OUTPUT_PATH}`);
  console.log(`[capture] URL: ${LOFI_URL}`);
  console.log(`[capture] DISPLAY: ${process.env.DISPLAY}`);
  console.log(`[capture] PULSE_SERVER: ${process.env.PULSE_SERVER || '(default)'}`);

  const browser = await launch({
    executablePath: '/usr/bin/google-chrome-stable',
    defaultViewport: { width: 1280, height: 720 },
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      // JANGAN pakai --disable-gpu karena memblokir Web Audio API
      '--disable-web-security',
      '--autoplay-policy=no-user-gesture-required',
      '--use-fake-ui-for-media-stream',
      '--enable-usermedia-screen-capturing',
      '--allow-http-screen-capture',
      '--disable-background-timer-throttling',
      '--disable-backgrounding-occluded-windows',
      '--disable-renderer-backgrounding',
      // Audio flags
      '--audio-output-channels=2',
      '--disable-features=AudioServiceOutOfProcess',
      `--display=${process.env.DISPLAY || ':99'}`,
    ],
  });

  const page = await browser.newPage();

  // Grant permissions
  const context = browser.defaultBrowserContext();
  await context.overridePermissions(LOFI_URL, ['microphone', 'camera']);

  page.on('console', msg => {
    console.log(`[page-${msg.type()}] ${msg.text()}`);
  });

  page.on('pageerror', err => {
    console.log(`[page-error] ${err.message}`);
  });

  console.log('[capture] Membuka URL...');
  await page.goto(LOFI_URL, { waitUntil: 'networkidle2', timeout: 60000 });
  console.log('[capture] Halaman dimuat');

  await sleep(3000);

  // Cari dan klik tombol play
  console.log('[capture] Mencari tombol play...');
  const playSelectors = [
    '#play-button',
    '.play-button',
    'button[aria-label="play"]',
    'button[aria-label="Play"]',
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
    } catch (e) {
      // lanjut
    }
  }

  if (!clicked) {
    await page.keyboard.press('Space');
    console.log('[capture] Coba spacebar sebagai play');
  }

  // Resume AudioContext via evaluate
  await page.evaluate(() => {
    if (window.Tone && window.Tone.context) {
      window.Tone.context.resume();
      console.log('[eval] Tone.js context resumed');
    }
    const buttons = document.querySelectorAll('button, [role="button"]');
    buttons.forEach(b => {
      const text = b.textContent.toLowerCase();
      const classes = b.className.toLowerCase();
      if (text.includes('play') || classes.includes('play') || classes.includes('start')) {
        b.click();
      }
    });
  });

  // Warmup
  console.log(`[capture] Warmup ${WARMUP_MS / 1000} detik...`);
  await sleep(WARMUP_MS);

  // Cek apakah ada AudioContext yang berjalan
  const audioCheck = await page.evaluate(() => {
    const ctx = window.Tone && window.Tone.context
      ? window.Tone.context
      : null;
    return {
      toneState: ctx ? ctx.state : 'no Tone.js',
      hasAudio: typeof AudioContext !== 'undefined',
    };
  });
  console.log(`[capture] Audio check: ${JSON.stringify(audioCheck)}`);

  // Mulai capture stream
  console.log('[capture] Mulai merekam...');
  let stream;
  try {
    stream = await getStream(page, {
      audio: true,
      video: false,
      mimeType: 'audio/webm;codecs=opus',
      audioBitsPerSecond: 192000,
    });
  } catch (e) {
    console.error('[capture] getStream gagal:', e.message);
    console.log('[capture] Mencoba fallback dengan video=true...');
    // Fallback: capture dengan video juga (lalu extract audio saat convert)
    stream = await getStream(page, {
      audio: true,
      video: true,
      mimeType: 'video/webm;codecs=vp8,opus',
      audioBitsPerSecond: 192000,
    });
  }

  const outputStream = fs.createWriteStream(OUTPUT_PATH);
  stream.pipe(outputStream);

  console.log(`[capture] Merekam selama ${argv.duration} menit...`);

  const startTime = Date.now();
  const progressInterval = setInterval(() => {
    const elapsed = Math.floor((Date.now() - startTime) / 60000);
    const remaining = argv.duration - elapsed;
    // Cek ukuran file sementara
    try {
      const stats = fs.statSync(OUTPUT_PATH);
      const sizeMB = (stats.size / 1024 / 1024).toFixed(2);
      console.log(`[capture] Progress: ${elapsed}/${argv.duration} menit | File: ${sizeMB} MB`);
      if (stats.size < 10000 && elapsed > 0) {
        console.warn('[capture] ⚠️  File terlalu kecil - kemungkinan audio tidak ter-capture!');
      }
    } catch (_) {}
  }, 60000);

  await sleep(DURATION_MS);
  clearInterval(progressInterval);

  console.log('[capture] Durasi selesai, menghentikan rekaman...');
  stream.destroy();
  outputStream.end();

  // Tunggu file selesai ditulis
  await sleep(2000);

  await browser.close();

  const stats = fs.statSync(OUTPUT_PATH);
  const sizeMB = (stats.size / 1024 / 1024).toFixed(2);
  console.log(`[capture] File: ${OUTPUT_PATH} (${sizeMB} MB)`);

  if (stats.size < 100000) {
    throw new Error(
      `File output terlalu kecil (${stats.size} bytes) - audio tidak ter-capture. ` +
      `Cek apakah PulseAudio berjalan dan DISPLAY sudah di-set dengan benar.`
    );
  }

  console.log('[capture] Selesai!');
}

captureLofi().catch(err => {
  console.error('[capture] ERROR:', err);
  process.exit(1);
});
