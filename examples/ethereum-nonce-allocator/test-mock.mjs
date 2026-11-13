// Offline transport failures, source-derived pool gaps, and receipt-checkpoint cases.
import assert from 'node:assert/strict';
import http from 'node:http';
import { readNonces, reconcile } from './nonces.mjs';
let mode = '';
const srv = http.createServer((req, res) => { let b = ''; req.on('data', (c) => (b += c)); req.on('end', () => {
  const q = JSON.parse(b); const tag = q.params[1];
  const out = { jsonrpc: '2.0', id: mode === 'wrong-id' ? q.id + 1 : q.id };
  if (mode === 'error' && tag === 'pending') out.error = { code: -32000, message: 'boom' };
  else out.result = mode === 'pending-below' ? (tag === 'latest' ? '0x10' : '0xf') : mode === 'malformed' ? '0x010' : (tag === 'latest' ? '0x10' : '0x12');
  res.setHeader('content-type', 'application/json'); res.end(JSON.stringify(out)); }); });
await new Promise((r) => srv.listen(0, r));
const url = `http://127.0.0.1:${srv.address().port}`;
const A = '0x' + '11'.repeat(20);
try {
  mode = 'ok';
  assert.deepEqual(await readNonces(url, A), { latest: 16n, pending: 18n });
  for (mode of ['pending-below', 'malformed', 'error', 'wrong-id']) {
    await assert.rejects(readNonces(url, A));
  }
  console.log('PASS valid counts and four rejected RPC replies');
} finally {
  srv.close();
}

// The cited Erigon implementation returns the same counts for these distinct pools.
const saved = [6n, 7n, 8n].map((nonce) => ({ nonce }));
for (const pool of [[6, 7, 8], [7, 8]]) {
  const view = { latest: 6n, pending: BigInt(Math.max(...pool) + 1) };
  assert.deepEqual(view, { latest: 6n, pending: 9n });
  for (const semantics of [undefined, 'unknown', 'highest-nonce']) {
    const result = reconcile(saved, view, 6n, semantics, 6n);
    assert.equal(result.action, 'stop');
    assert.equal(result.lowestUnresolved, 6n);
    assert.equal(result.next, undefined);
    console.log('Erigon fixture', pool, semantics ?? 'default', result);
  }
}
const consecutive = 'verified-consecutive';
assert.equal(reconcile(saved, { latest: 6n, pending: 6n }, 6n, consecutive).action, 'repair');
assert.equal(reconcile(saved, { latest: 6n, pending: 9n }, 6n, consecutive).action, 'ok');
console.log('PASS pool-semantics fixtures');

// Checkpoint fixtures assume the custody and finalized-receipt procedure in the article.
const checkpointCases = [
  { name: 'new unused key', records: [], latest: 0n, pending: 0n, baseline: 0n, settledNext: 0n, next: 0n },
  { name: 'existing key handover', records: [], latest: 42n, pending: 42n, baseline: 42n, settledNext: 42n, next: 42n },
  { name: 'reservation still open', records: [{ nonce: 42n }], latest: 42n, pending: 42n, baseline: 42n, settledNext: 42n },
  { name: 'pending includes open reservation', records: [{ nonce: 42n }], latest: 42n, pending: 43n, baseline: 42n, settledNext: 42n },
  { name: 'included but unfinalized', records: [{ nonce: 42n }], latest: 43n, pending: 43n, baseline: 42n, settledNext: 42n },
  { name: 'receipt finalized', records: [{ nonce: 42n }], latest: 43n, pending: 43n, baseline: 42n, settledNext: 43n, next: 43n },
  { name: 'fully consumed without checkpoint', records: [{ nonce: 42n }], latest: 43n, pending: 43n, baseline: 42n },
  { name: 'fresh key without checkpoint', records: [], latest: 0n, pending: 0n, baseline: 0n },
  { name: 'unexplained activity', records: [], latest: 43n, pending: 43n, baseline: 42n, settledNext: 43n },
  { name: 'pending above settled range', records: [{ nonce: 42n }], latest: 43n, pending: 44n, baseline: 42n, settledNext: 43n },
  { name: 'count decreased after settlement', records: [{ nonce: 42n }], latest: 42n, pending: 42n, baseline: 42n, settledNext: 43n },
];
for (const c of checkpointCases) {
  const result = reconcile(c.records, { latest: c.latest, pending: c.pending }, c.baseline, 'unknown', c.settledNext);
  assert.equal(result.action, c.next === undefined ? 'stop' : 'ok', c.name);
  assert.equal(result.next, c.next, c.name);
  console.log('Checkpoint fixture', c.name, result);
}
console.log('PASS 11 receipt-checkpoint fixtures');
