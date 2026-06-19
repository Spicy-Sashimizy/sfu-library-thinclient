// Precompile the SFU Library Suite apps: JSX -> plain JS, so the browser never
// runs the (slow, 3 MB) in-browser Babel transformer. Big first-load speedup.
//
// First run MIGRATES: extracts each app's `type="text/babel"` source into
// web/src/<app>.jsx and rewrites the HTML to load the compiled web/<app>.js
// (dropping vendor/babel.min.js). Subsequent runs just recompile src/ -> js.
//
// Run:  node scripts/build_web.mjs        (uses the vendored Babel via Node)
//   or: PW unused; relies only on web/vendor/babel.min.js
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const WEB = path.join(ROOT, 'web');
const SRC = path.join(WEB, 'src');
globalThis.window = globalThis.window || {};
const Babel = (await import(path.join(WEB, 'vendor', 'babel.min.js'))).default || globalThis.Babel;

const APPS = [
  { html: 'search.html',        src: 'search.jsx',        js: 'search.js' },
  { html: 'analytics.html',     src: 'analytics.jsx',     js: 'analytics.js' },
  { html: 'index_manager.html', src: 'index_manager.jsx', js: 'index_manager.js' },
];

if (!existsSync(SRC)) mkdirSync(SRC, { recursive: true });

// Match a babel script tag, optionally with src="...", capturing src + inline body.
const BABEL_TAG = /<script type="text\/babel"(?:\s+src="([^"]+)")?\s*>([\s\S]*?)<\/script>/g;

let built = 0;
for (const app of APPS) {
  const htmlPath = path.join(WEB, app.html);
  const srcPath = path.join(SRC, app.src);
  let html = readFileSync(htmlPath, 'utf8');

  // MIGRATION (only if we haven't extracted source yet AND the HTML still has babel tags)
  if (!existsSync(srcPath) && BABEL_TAG.test(html)) {
    BABEL_TAG.lastIndex = 0;
    const parts = [];
    let m;
    while ((m = BABEL_TAG.exec(html))) {
      if (m[1]) parts.push(`/* ==== ${m[1]} ==== */\n` + readFileSync(path.join(WEB, m[1]), 'utf8'));
      else parts.push(m[2]);
    }
    writeFileSync(srcPath, parts.join('\n\n'));
    // Replace the first babel tag with the compiled <script>, drop the rest + babel vendor.
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

  // COMPILE shared sidebar + src/<app>.jsx -> web/<app>.js
  // _sidebar.jsx is prepended into EVERY app so all three render an identical
  // sidebar (nav + Session Replay panel + AI status) from one source.
  const sharedPath = path.join(SRC, '_sidebar.jsx');
  const shared = existsSync(sharedPath) ? readFileSync(sharedPath, 'utf8') + '\n\n' : '';
  const jsx = shared + readFileSync(srcPath, 'utf8');
  const out = Babel.transform(jsx, { presets: ['react'], compact: false }).code;
  writeFileSync(path.join(WEB, app.js), '/* AUTO-GENERATED from src/' + app.src + ' by scripts/build_web.mjs — do not edit. */\n' + out);
  console.log(`  built web/${app.js} (${(out.length/1024).toFixed(0)} KB)`);
  built++;
}
console.log(`done: ${built} app(s) compiled.`);
