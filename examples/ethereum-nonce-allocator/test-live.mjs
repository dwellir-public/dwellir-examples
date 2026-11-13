// Read-only Dwellir replay and live checks. Reservations are synthetic.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { setTimeout } from 'node:timers/promises';
import { readNonces, reconcile } from './nonces.mjs';

const fixture = JSON.parse(fs.readFileSync(new URL('./dwellir-counts.json', import.meta.url)));
const records = [5n, 6n, 7n, 8n].map((nonce) => ({ nonce, hashes: [] }));
const stringify = (value) => JSON.stringify(value, (_, v) => typeof v === 'bigint' ? v.toString() : v);
for (const observation of fixture.observations) {
  const view = { latest: BigInt(observation.latest), pending: BigInt(observation.pending) };
  const repaired = reconcile(records, view, 0n, 'verified-consecutive');
  assert.equal(repaired.action, 'repair');
  assert.deepEqual(repaired.notCounted, [6n, 7n, 8n]);
  assert.deepEqual(repaired.usedNeedReceipt, [5n]);
  assert.equal(repaired.next, 9n);
  assert.equal(reconcile([{ nonce: 2n }], view).action, 'stop');
  assert.equal(reconcile([], view, 6n, 'unknown', 6n).next, 6n);
  assert.equal(reconcile([], view).action, 'stop');
  const unresolved = reconcile(records, view, 0n, 'unknown', 6n);
  assert.equal(unresolved.action, 'stop');
  assert.equal(unresolved.lowestUnresolved, 6n);
  console.log(stringify({ host: observation.host, source: fixture.source, view,
    syntheticRecords: true, hypotheticalConsecutiveSemantics: repaired, hostedSemantics: unresolved }));
}

if (process.argv.includes('--live')) {
  const key = process.env.DWELLIR_API_KEY;
  assert.ok(key, 'Set DWELLIR_API_KEY for live checks');
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (...args) => {
    await setTimeout(800);
    return originalFetch(...args);
  };
  try {
    for (const observation of fixture.observations) {
      const url = `https://${observation.host}/${key}`;
      const response = await fetch(url, { method: 'POST',
        headers: { 'content-type': 'application/json' }, signal: AbortSignal.timeout(15_000),
        body: JSON.stringify({ jsonrpc: '2.0', id: 1000, method: 'eth_chainId', params: [] }) });
      assert.ok(response.ok);
      const chain = await response.json();
      assert.equal(chain.jsonrpc, '2.0');
      assert.equal(chain.id, 1000);
      assert.equal(chain.result, '0x1');
      const view = await readNonces(url, fixture.sender);
      const result = reconcile(records, view, 0n, 'unknown', 6n);
      assert.equal(result.action, 'stop');
      console.log(stringify({ at: new Date().toISOString(), host: observation.host,
        chainId: chain.result, view, result, readOnly: true }));
    }
  } catch {
    throw new Error('Dwellir live check failed; authenticated URLs omitted');
  } finally {
    globalThis.fetch = originalFetch;
  }
}
console.log('PASS Dwellir count replay; no transaction sent');
