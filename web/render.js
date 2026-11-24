// Renders every frame of a timeline to JPEGs using headless Chromium + three.js.
// usage: node web/render.js timeline.json outDir [step=1] [workers=4]
const http = require('http');
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const [tlPath, outDir, stepArg = '1', workersArg = '4'] = process.argv.slice(2);
const step = parseInt(stepArg, 10), workers = parseInt(workersArg, 10);
const ROOT = path.resolve(__dirname, '..');
const TYPES = { '.js': 'text/javascript', '.html': 'text/html', '.otf': 'font/otf', '.glb': 'model/gltf-binary', '.json': 'application/json' };

const server = http.createServer((req, res) => {
  const p = path.join(ROOT, decodeURIComponent(req.url.split('?')[0]));
  if (!p.startsWith(ROOT)) { res.writeHead(403); return res.end(); }
  fs.readFile(p, (err, data) => {
    if (err) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(p)] || 'application/octet-stream' });
    res.end(data);
  });
});

(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const url = `http://127.0.0.1:${server.address().port}/web/race.html`;
  const tl = JSON.parse(fs.readFileSync(tlPath, 'utf8'));
  const frames = [];
  for (let f = 0; f < tl.frames; f += step) frames.push(f);

  const browser = await chromium.launch({
    args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--enable-webgl'],
  });
  const t0 = Date.now();
  let done = 0;
  const work = async (w) => {
    const page = await browser.newPage({ viewport: { width: 1080, height: 1920 } });
    page.on('pageerror', e => { console.error('PAGE ERROR', e.message); process.exit(1); });
    page.on('console', m => { if (m.type() === 'error') console.error('PAGE', m.text()); });
    await page.goto(url);
    await page.waitForFunction('window.ready === true', null, { timeout: 120000 });
    await page.evaluate(t => window.init(t), tl);
    for (let k = w; k < frames.length; k += workers) {
      const data = await page.evaluate(f => window.renderFrame(f), frames[k]);
      fs.writeFileSync(path.join(outDir, String(k).padStart(5, '0') + '.jpg'), Buffer.from(data.split(',')[1], 'base64'));
      if (++done % 60 === 0 || done === frames.length) {
        const el = (Date.now() - t0) / 1000;
        console.log(`  frames ${done}/${frames.length}  ${el.toFixed(0)}s  (~${(el / done * (frames.length - done)).toFixed(0)}s left)`);
      }
    }
    await page.close();
  };
  await Promise.all([...Array(workers).keys()].map(work));
  await browser.close();
  server.close();
})().catch(e => { console.error(e); process.exit(1); });
