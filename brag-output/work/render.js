const { chromium } = require('playwright');
const fs = require('fs'); const path = require('path');
(async () => {
  const mode = process.argv[2]; // "stills" t1,t2,... | "all"
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  await page.goto('file://' + path.resolve(__dirname, 'video.html'));
  await page.evaluate(() => window.ready);
  const shot = async (t, file) => { await page.evaluate(t => window.render(t), t); await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))); await page.screenshot({ path: file, type: 'jpeg', quality: 95 }); };
  if (mode === 'stills') {
    fs.mkdirSync('stills', { recursive: true });
    for (const t of process.argv[3].split(',').map(Number)) await shot(t, `stills/t${t.toFixed(2)}.jpg`);
  } else {
    fs.mkdirSync('frames', { recursive: true });
    const N = 22 * 30;
    for (let i = 0; i < N; i++) await shot(i / 30, `frames/f${String(i).padStart(4, '0')}.jpg`);
  }
  await browser.close();
})();
