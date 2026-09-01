import net from 'node:net';

const PORT = parseInt(process.env.GUITB_PORT || '8080', 10);

import fs from 'node:fs';
import path from 'node:path';

function findPid() {
  const dir = '/proc';
  for (const name of fs.readdirSync(dir)) {
    if (!/^\d+$/.test(name)) continue;
    try {
      const cmd = fs.readFileSync(path.join(dir, name, 'cmdline'), 'utf8').replace(/\0/g, ' ');
      if (cmd.includes('gui_testbed/static_server.mjs')) return parseInt(name, 10);
    } catch {}
  }
  return null;
}

const pid = findPid();
if (pid) { try { process.kill(pid, 'SIGTERM'); } catch {} console.log(`stopped pid ${pid}`); }
else console.log('no gui_testbed static_server running');
