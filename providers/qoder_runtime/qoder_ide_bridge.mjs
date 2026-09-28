/**
 * Compatibility fallback for an already running Qoder IDE.
 * Uses the same local read-only credit/usage request as its Credits panel.
 * Does not initialize a workspace, start the IDE, or read authentication secrets.
 */
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';

function quota(v, org = false) {
  if (!v || typeof v !== 'object') return undefined;
  const out = {};
  for (const key of [org ? 'cap' : 'total', 'used', 'remaining', 'percentage']) {
    if (typeof v[key] === 'number' && Number.isFinite(v[key])) out[key] = v[key];
  }
  if (typeof v.unit === 'string') out.unit = v.unit;
  if (typeof v.available === 'boolean') out.available = v.available;
  return out;
}
function sanitize(usage) {
  if (!usage || typeof usage !== 'object') return { error: 'usage_unavailable' };
  return {
    userQuota: quota(usage.userQuota),
    addOnQuota: quota(usage.addOnQuota),
    orgResourcePackage: quota(usage.orgResourcePackage, true),
    userType: typeof usage.userType === 'string' ? usage.userType : undefined,
    expiresAt: typeof usage.expiresAt === 'number' && Number.isFinite(usage.expiresAt)
      ? usage.expiresAt : undefined,
    source: 'Qoder IDE',
  };
}

let socket;
let timeout;
let finished = false;
function finish(result) {
  if (finished) return;
  finished = true;
  clearTimeout(timeout);
  socket?.destroy();
  process.stdout.write(JSON.stringify(result) + '\n');
}
try {
  if (process.platform !== 'win32') throw new Error('unsupported_platform');
  const appdata = process.env.APPDATA || path.join(process.env.USERPROFILE || '', 'AppData', 'Roaming');
  const metadataPath = path.join(appdata, 'Qoder', 'SharedClientCache', '.info.json');
  const info = JSON.parse(fs.readFileSync(metadataPath, 'utf8'));
  const pipe = info.ipcServerPath;
  if (typeof pipe !== 'string' || !/^\\\\\.\\pipe\\qoder-[a-z0-9-]+$/i.test(pipe)) {
    throw new Error('unsupported_pipe');
  }
  const requestId = 90001;
  const request = JSON.stringify({ jsonrpc: '2.0', id: requestId, method: 'credit/usage' });
  let buffer = Buffer.alloc(0);
  timeout = setTimeout(() => finish({ error: 'ide_timeout' }), 12000);
  socket = net.createConnection(pipe);
  socket.on('connect', () => socket.write(`Content-Length: ${Buffer.byteLength(request)}\r\n\r\n${request}`));
  socket.on('error', (error) => finish({ error: error.code === 'EPERM' || error.code === 'EACCES' ? 'ide_permission' : 'ide_unavailable' }));
  socket.on('end', () => finish({ error: 'ide_unavailable' }));
  socket.on('data', (chunk) => {
    try {
      buffer = Buffer.concat([buffer, chunk]);
      if (buffer.length > 2 * 1024 * 1024) return finish({ error: 'invalid_response' });
      while (!finished) {
        const end = buffer.indexOf('\r\n\r\n');
        if (end < 0) return;
        const match = /Content-Length:\s*(\d+)/i.exec(buffer.subarray(0, end).toString('ascii'));
        const length = match ? Number(match[1]) : NaN;
        if (!Number.isInteger(length) || length <= 0 || length > 2 * 1024 * 1024) {
          return finish({ error: 'invalid_response' });
        }
        if (buffer.length < end + 4 + length) return;
        const message = JSON.parse(buffer.subarray(end + 4, end + 4 + length).toString('utf8'));
        buffer = buffer.subarray(end + 4 + length);
        if (message.id === requestId) {
          return finish(message.error ? { error: 'usage_unavailable' } : sanitize(message.result));
        }
      }
    } catch { finish({ error: 'invalid_response' }); }
  });
} catch { finish({ error: 'ide_unavailable' }); }
