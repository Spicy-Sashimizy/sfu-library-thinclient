import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const WEB = path.join(ROOT, 'web');
const SRC = path.join(WEB, 'source');
globalThis.window = globalThis.window || {};
const Babel = (await import(path.join(WEB, 'vendor', 'babel.min.js'))).default || globalThis.Babel;

const APPS = [
  { html: 'search.html',        src: 'search.jsx',        js: 'search.js' },
  { html: 'analytics.html',     src: 'analytics.jsx',     js: 'analytics.js' },
  { html: 'index_manager.html', src: 'index_manager.jsx', js: 'index_manager.js' },
];

if (!existsSync(SRC)) mkdirSync(SRC, { recursive: true });

const BABEL_TAG = /<script type="text\/babel"(?:\s+src="([^"]+)")?\s*>([\s\S]*?)<\/script>/g;

let built = 0;
for (const app of APPS) {
  const htmlPath = path.join(WEB, app.html);
  const srcPath = path.join(SRC, app.src);
  let html = readFileSync(htmlPath, 'utf8');

  if (!existsSync(srcPath) && BABEL_TAG.test(html)) {
    BABEL_TAG.lastIndex = 0;
    const parts = [];
    let m;
    while ((m = BABEL_TAG.exec(html))) {
      if (m[1]) parts.push(`/* ==== ${m[1]} ==== */\n` + readFileSync(path.join(WEB, m[1]), 'utf8'));
      else parts.push(m[2]);
    }
    writeFileSync(srcPath, parts.join('\n\n'));
    let replaced = false;
    html = html.replace(BABEL_TAG, () => {
      if (!replaced) { replaced = true; return `<script src="${app.js}"></script>`; }
      return '';
    });
    html = html.replace(/[ \t]*<script src="vendor\/babel\.min\.js"><\/script>\n?/, '');
    html = html.replace(/\n{3,}/g, '\n\n');
    writeFileSync(htmlPath, html);
    console.log(`  migrated ${app.html} -> ${app.src} (HTML now loads ${app.js})`);
  }

  if (!existsSync(srcPath)) { console.log(`  SKIP ${app.html}: no ${app.src} and no babel tags`); continue; }

  const sharedPath = path.join(SRC, '_sidebar.jsx');
  const shared = existsSync(sharedPath) ? readFileSync(sharedPath, 'utf8') + '\n\n' : '';
  const jsx = shared + readFileSync(srcPath, 'utf8');
  const out = Babel.transform(jsx, { presets: ['react'], compact: false }).code;
  writeFileSync(path.join(WEB, app.js), '/* AUTO-GENERATED from source/' + app.src + ' by scripts/build_web.mjs — do not edit. */\n' + out);
  console.log(`  built web/${app.js} (${(out.length/1024).toFixed(0)} KB)`);
  built++;
}
console.log(`done: ${built} app(s) compiled.`);
