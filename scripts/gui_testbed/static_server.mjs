import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const WEB = path.join(ROOT, 'web');
const PORT = parseInt(process.env.GUITB_PORT || '8080', 10);
const HOST = process.env.GUITB_HOST || '127.0.0.1';

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js':   'text/javascript; charset=utf-8',
  '.mjs':  'text/javascript; charset=utf-8',
  '.css':  'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg':  'image/svg+xml',
  '.png':  'image/png',
  '.ico':  'image/x-icon',
  '.woff2':'font/woff2',
  '.woff': 'font/woff',
};

const DETACH = process.argv.includes('--detach');
if (DETACH) {
  const { spawn } = await import('node:child_process');
  const child = spawn(process.execPath, [fileURLToPath(import.meta.url)], {
    detached: true, stdio: 'ignore', env: { ...process.env, GUITB_PORT: String(PORT) },
  });
  child.unref();
  console.log(child.pid);
  process.exit(0);
}

const server = http.createServer((req, res) => {
  let urlPath = decodeURIComponent((req.url || '/').split('?')[0]);
  let fsPath;
  if (urlPath === '/app' || urlPath === '/app/') {
    res.writeHead(302, { Location: '/app/suite.html' });
    return res.end();
  }
  if (urlPath.startsWith('/app/')) fsPath = path.join(WEB, urlPath.slice('/app/'.length));
  else if (urlPath === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify({ status: 'offline', tools: 0, warm: false }));
  } else {
    res.writeHead(404); return res.end('not found');
  }
  fsPath = path.normalize(fsPath);
  if (!fsPath.startsWith(WEB)) { res.writeHead(403); return res.end('forbidden'); }
  fs.stat(fsPath, (err, st) => {
    if (err || !st) { res.writeHead(404); return res.end('not found'); }
    if (st.isDirectory()) fsPath = path.join(fsPath, 'index.html');
    fs.readFile(fsPath, (e, data) => {
      if (e) { res.writeHead(404); return res.end('not found'); }
      res.writeHead(200, { 'Content-Type': MIME[path.extname(fsPath)] || 'application/octet-stream' });
      res.end(data);
    });
  });
});

server.listen(PORT, HOST, () => {
  process.stderr.write(`gui_testbed static_server: ${WEB} at http://${HOST}:${PORT}/app (pid ${process.pid})\n`);
});

process.on('SIGTERM', () => { server.close(() => process.exit(0)); });
process.on('SIGINT', () => { server.close(() => process.exit(0)); });
