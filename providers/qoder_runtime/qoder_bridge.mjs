/** Read-only Qoder SDK quota query. Never submits a user prompt or Agent turn. */
import { query, qodercliAuth } from '@qoder-ai/qoder-agent-sdk';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const cwd = path.dirname(fileURLToPath(import.meta.url));
let releaseInput;
let q;
let output;
let authExpired = false;
async function* noPrompt() {
  await new Promise((resolve) => { releaseInput = resolve; });
}
const finite = (v) => typeof v === 'number' && Number.isFinite(v);
function quota(v, org = false) {
  if (!v || typeof v !== 'object') return undefined;
  const out = {};
  for (const key of [org ? 'cap' : 'total', 'used', 'remaining', 'percentage']) {
    if (finite(v[key])) out[key] = v[key];
  }
  if (typeof v.unit === 'string') out.unit = v.unit;
  if (typeof v.available === 'boolean') out.available = v.available;
  return out;
}
try {
  q = query({
    prompt: noPrompt(),
    options: {
      auth: qodercliAuth(), cwd, persistSession: false, settingSources: [],
      strictMcpConfig: true, mcpServers: {}, allowedMcpServerNames: [],
      hooks: {}, plugins: [], maxTurns: 0,
      enableFileCheckpointing: false,
      stderr: () => {},
      controlRequestTimeoutMs: 18000,
      closeGraceMs: 500,
      onAuthExpired: () => { authExpired = true; },
      canUseTool: async () => ({ behavior: 'deny', message: 'Quota reader does not execute tools.' }),
      resolveModel: async () => { throw new Error('Quota reader cannot start a model request.'); },
    },
  });
  await q.initializationResult();
  const usage = await q.getUsageInfo();
  if (!usage) output = { error: authExpired ? 'auth_required' : 'usage_unavailable' };
  else {
    output = {
      userQuota: quota(usage.userQuota),
      addOnQuota: quota(usage.addOnQuota),
      orgResourcePackage: quota(usage.orgResourcePackage, true),
      userType: typeof usage.userType === 'string' ? usage.userType : undefined,
      expiresAt: finite(usage.expiresAt) ? usage.expiresAt : undefined,
      source: 'Qoder SDK',
    };
  }
} catch {
  // Exceptions from transports may include credentials; never print raw text.
  output = { error: authExpired ? 'auth_required' : 'sdk_query_failed' };
} finally {
  releaseInput?.();
  if (q) { try { await q.close(); } catch {} }
}
process.stdout.write(JSON.stringify(output) + '\n');
process.exit(0);
