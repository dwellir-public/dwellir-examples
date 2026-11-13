const isAddress = (v) => typeof v === 'string' && /^0x[0-9a-fA-F]{40}$/.test(v);
const isQuantity = (v) => typeof v === 'string' && /^0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)$/.test(v);
const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
let requestId = 0;

async function rpc(url, method, params) {
  const id = ++requestId;
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    signal: AbortSignal.timeout(10_000),
    body: JSON.stringify({ jsonrpc: '2.0', id, method, params }),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const body = await response.json();
  if (!isObject(body) || body.jsonrpc !== '2.0' || body.id !== id) throw new Error('Invalid RPC envelope');
  if (Object.hasOwn(body, 'error')) throw new Error(`RPC error: ${JSON.stringify(body.error)}`);
  if (!Object.hasOwn(body, 'result')) throw new Error('Missing RPC result');
  return body.result;
}

// Two separate reads, not a snapshot. Always send the block tag.
export async function readNonces(url, from) {
  if (!isAddress(from)) throw new Error('Not a 20-byte address');
  const latest = await rpc(url, 'eth_getTransactionCount', [from, 'latest']);
  const pending = await rpc(url, 'eth_getTransactionCount', [from, 'pending']);
  if (!isQuantity(latest) || !isQuantity(pending)) throw new Error('Invalid nonce reply');
  if (BigInt(pending) < BigInt(latest)) throw new Error('pending below latest; retry the pair');
  return { latest: BigInt(latest), pending: BigInt(pending) };
}

// records: one entry per nonce you allocated for this sender, e.g. { nonce: 42n, hashes: ['0x...'] }.
// baseline: finalized account nonce at exclusive handover (0n for a new, unused key).
// poolSemantics: 'verified-consecutive' requires evidence for every backend this endpoint can use.
// settledNext: durable receipt checkpoint under exclusive key custody, never copied from a live count.
export function reconcile(records, { latest, pending }, baseline = 0n, poolSemantics = 'unknown', settledNext = null) {
  if (latest < baseline) return { action: 'stop', reason: 'latest below saved baseline' };
  const open = records.filter((r) => r.nonce >= latest).sort((a, b) => (a.nonce < b.nonce ? -1 : 1));
  const used = records.filter((r) => r.nonce < latest).map((r) => r.nonce);
  const highest = records.reduce((m, r) => (r.nonce > m ? r.nonce : m), baseline - 1n);
  // Stop on activity that the saved allocation range cannot explain.
  if (latest > highest + 1n || pending > highest + 1n) {
    return { action: 'stop', reason: 'count above local records', latest, pending, highest };
  }
  const settled = open.length === 0 && latest === pending && latest === settledNext;
  if (poolSemantics !== 'verified-consecutive' && !settled) {
    return {
      action: 'stop',
      reason: 'need settled receipt checkpoint or verified consecutive pool',
      lowestUnresolved: open.length ? open[0].nonce : null,
    };
  }
  // With verified consecutive semantics, these nonces are outside the executable sequence.
  const notCounted = open.filter((r) => r.nonce >= pending).map((r) => r.nonce);
  const next = highest + 1n > latest ? highest + 1n : latest;
  return {
    action: notCounted.length ? 'repair' : 'ok',
    lowestUnresolved: open.length ? open[0].nonce : null, // first nonce to watch or replace
    notCounted, // rebroadcast saved bytes, starting with the lowest
    usedNeedReceipt: used, // find which saved hash won before closing each record
    next,
  };
}
