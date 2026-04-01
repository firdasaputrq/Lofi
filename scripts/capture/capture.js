/**
 * capture.js
 * Membuka lofi.jacobzhang.de di Chrome headless,
 * menekan tombol play, lalu merekam audio selama durasi yang ditentukan.
 */

const puppeteer = require('puppeteer');
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

// Tambah sedikit buffer time untuk warmup
const WARMUP_MS = 8000;

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function captureLofi() {
  console.log(`[capture] Mulai capture ${argv.duration} menit -> ${OUTPUT_PATH}`);
  console.log(`[capture] URL: ${LOFI_URL}`);

  const browser = await launch({
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
      '--enable-usermedia-screen-capturing',
      '--allow-http-screen-capture',
      `--display=${process.env.DISPLAY || ':99'}`,
    ],
  });

  const page = await browser.newPage();

  // Grant microphone/audio permissions
  const context = browser.defaultBrowserContext();
  await context.overridePermissions(LOFI_URL, ['microphone', 'camera']);

  // Intercept console dari page untuk debug
  page.on('console', msg => {
    if (msg.type() === 'error') {
      console.log(`[page-error] ${msg.text()}`);
    }
  });

  console.log('[capture] Membuka URL...');
  await page.goto(LOFI_URL, { waitUntil: 'networkidle2', timeout: 60000 });
  console.log('[capture] Halaman dimuat');

  // Tunggu element musik siap
  await sleep(3000);

  // Cari dan klik tombol play
  console.log('[capture] Mencari tombol play...');
  try {
    // Coba berbagai selector yang mungkin ada di website lofi
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
      } catch (e) {
        // lanjut ke selector berikutnya
      }
    }

    if (!clicked) {
      // Coba klik via keyboard (spacebar sering jadi shortcut play)
      await page.keyboard.press('Space');
      console.log('[capture] Coba spacebar sebagai play');
    }

    // Coba juga via evaluate jika ada AudioContext yang perlu resume
    await page.evaluate(() => {
      // Resume semua AudioContext yang mungkin suspended
      if (window.Tone && window.Tone.context) {
        window.Tone.context.resume();
      }
      // Trigger click pada semua element bertipe button
      const buttons = document.querySelectorAll('button, [role="button"]');
      buttons.forEach(b => {
        const text = b.textContent.toLowerCase();
        const classes = b.className.toLowerCase();
        if (text.includes('play') || classes.includes('play') || classes.includes('start')) {
          b.click();
        }
      });
    });

  } catch (e) {
    console.log(`[capture] Peringatan saat klik play: ${e.message}`);
  }

  // Warmup - tunggu audio mulai
  console.log(`[capture] Warmup ${WARMUP_MS / 1000} detik...`);
  await sleep(WARMUP_MS);

  // Mulai capture stream
  console.log('[capture] Mulai merekam...');
  const stream = await getStream(page, {
    audio: true,
    video: false,  // audio only - lebih efisien
    mimeType: 'audio/webm;codecs=opus',
    audioBitsPerSecond: 192000,
  });

  const outputStream = fs.createWriteStream(OUTPUT_PATH);
  stream.pipe(outputStream);

  console.log(`[capture] Merekam selama ${argv.duration} menit...`);

  // Progress indicator
  const startTime = Date.now();
  const progressInterval = setInterval(() => {
    const elapsed = Math.floor((Date.now() - startTime) / 60000);
    const remaining = argv.duration - elapsed;
    console.log(`[capture] Progress: ${elapsed}/${argv.duration} menit (sisa ${remaining} menit)`);
  }, 60000);

  // Tunggu durasi selesai
  await sleep(DURATION_MS);
  clearInterval(progressInterval);

  console.log('[capture] Durasi selesai, menghentikan rekaman...');
  stream.destroy();
  outputStream.end();

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
