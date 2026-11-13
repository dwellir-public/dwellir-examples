import assert from 'node:assert/strict';
import test from 'node:test';
import {
  agreement,
  blockValid,
  logFingerprint,
  receiptValid,
  rpcResult,
} from '../lib/validate.mjs';
import { priceWorkload, validatePrices } from '../lib/pricing.mjs';
import { createClient } from '../lib/transport.mjs';
import { createServer } from 'node:http';
import { once } from 'node:events';

const h = (n) => `0x${n.repeat(64)}`;
const log = {
  blockNumber: '0x64',
  blockHash: h('a'),
  transactionHash: h('b'),
  transactionIndex: '0x0',
  logIndex: '0x0',
  address: `0x${'c'.repeat(40)}`,
  topics: [h('d')],
  data: '0x1234',
  removed: false,
};

test('RPC envelopes reject null, missing IDs, contradictory fields and malformed errors', () => {
  const response = (body, status = 200) => rpcResult({ status, body });
  assert.equal(response({ jsonrpc: '2.0', id: 1, result: null }).verdict, 'null');
  assert.equal(response({ jsonrpc: '2.0', result: '0x1' }).verdict, 'invalid envelope');
  assert.equal(
    response({ jsonrpc: '2.0', id: 1, result: '0x1', error: {} }).verdict,
    'invalid envelope',
  );
  assert.equal(
    response({ jsonrpc: '2.0', id: 1, error: { code: '-32000', message: 'bad' } }).verdict,
    'invalid error',
  );
  assert.equal(
    response({ jsonrpc: '2.0', id: 1, error: { code: -32000, message: 'unavailable' } }).verdict,
    'RPC -32000',
  );
  assert.equal(response({}, 429).verdict, 'HTTP 429');
});

test('a block and receipt must belong to the requested identities', () => {
  const block = { number: '0x64', hash: h('a'), transactions: [h('b')] };
  const receipt = { blockNumber: '0x64', blockHash: h('a'), transactionHash: h('b') };
  assert.ok(blockValid(block, 100, h('a')));
  assert.ok(!blockValid(block, 101));
  assert.ok(!blockValid({ ...block, transactions: [null] }, 100));
  assert.ok(receiptValid(receipt, h('b'), block));
  assert.ok(!receiptValid({ ...receipt, blockHash: h('c') }, h('b'), block));
  assert.ok(!receiptValid({ ...receipt, transactionHash: h('c') }, h('b'), block));
});

test('log fingerprints include content, reject malformed or duplicate logs, and ignore result order', () => {
  const other = { ...log, logIndex: '0x1', data: '0x5678' };
  assert.equal(logFingerprint([log, other], 100, 100), logFingerprint([other, log], 100, 100));
  assert.notEqual(
    logFingerprint([log], 100, 100),
    logFingerprint([{ ...log, data: '0xabcd' }], 100, 100),
  );
  assert.notEqual(logFingerprint([], 100, 100), null);
  for (const payload of [
    null,
    {},
    [null],
    [log, log],
    [{ ...log, removed: true }],
    [{ ...log, blockNumber: '0x65' }],
    [{ ...log, topics: ['broken'] }],
  ]) {
    assert.equal(logFingerprint(payload, 100, 100), null);
  }
  assert.equal(logFingerprint([log], 100, 100, { address: `0x${'d'.repeat(40)}` }), null);
});

test('agreement never treats a lone response or a split vote as a match', () => {
  for (const [values, expected] of [
    [
      ['A', 'A'],
      ['match', 'match'],
    ],
    [
      ['A', 'B'],
      ['no quorum', 'no quorum'],
    ],
    [
      ['A', 'B', 'C'],
      ['no quorum', 'no quorum', 'no quorum'],
    ],
    [
      ['A', 'A', 'B'],
      ['match', 'match', 'disagrees'],
    ],
    [
      ['A', null],
      ['unverified', 'unavailable'],
    ],
    [
      ['A', 'A', 'B', 'B'],
      ['no quorum', 'no quorum', 'no quorum', 'no quorum'],
    ],
  ])
    assert.deepEqual(agreement(values), expected);
});


const plan = {
  id: 'fixture',
  name: 'Fixture plan',
  sourceUrl: 'https://example.test/pricing',
  checkedAt: '2026-11-13',
  model: 'responses',
  monthlyUsd: 49,
  includedUnits: 25_000_000,
  overageUsdPerMillion: 5,
};
const now = new Date('2026-11-13T12:00:00Z');

test('pricing adds subscription and overage; unknown methods never receive guessed CU weights', () => {
  const result = priceWorkload(plan, { eth_call: 30_000_000 }, now);
  assert.equal(result.estimatedUsd, 74);
  assert.equal(result.overageUsd, 25);
  const weighted = {
    ...plan,
    model: 'compute-units',
    monthlyUsd: 0,
    includedUnits: 0,
    overageUsdPerMillion: 0.5,
    weights: { eth_call: 20 },
    weightsSourceUrl: 'https://example.test/weights',
  };
  assert.equal(priceWorkload(weighted, { eth_call: 10_000_000 }, now).estimatedUsd, 100);
  assert.equal(priceWorkload(weighted, { eth_unknown: 1 }, now).estimatedUsd, null);
  assert.equal(priceWorkload(undefined, { eth_call: 1 }, now).verdict, 'unpriced');
  assert.equal(
    priceWorkload(
      { ...plan, model: 'unresolved', reason: 'Conflicting rates' },
      { eth_call: 1 },
      now,
    ).estimatedUsd,
    null,
  );
  assert.equal(priceWorkload(plan, { eth_call: 0 }, now).estimatedUsd, null);
  assert.equal(priceWorkload(plan, { eth_call: 1 }, new Date('2026-12-20')).stale, true);
  assert.equal(priceWorkload(plan, { eth_call: 1 }, new Date('2026-11-01')).estimatedUsd, null);
  for (const invalid of [
    { ...plan, sourceUrl: '' },
    { ...plan, checkedAt: '' },
    { ...plan, monthlyUsd: -1 },
    { ...weighted, weights: null },
  ]) {
    assert.throws(() => validatePrices({ plans: [invalid] }));
  }
});

test('HTTP transport bounds response size and total request duration, and records real socket reuse', async () => {
  const server = createServer((request, response) => {
    request.resume();
    if (request.url === '/large') return response.end('x'.repeat(1024));
    if (request.url === '/hang') return;
    response.setHeader('content-type', 'application/json');
    response.end('{"jsonrpc":"2.0","id":1,"result":"0x1"}');
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const base = `http://127.0.0.1:${server.address().port}`;
  const clients = [];
  const client = (path) => {
    const result = createClient(
      { name: 'fixture', http: new URL(base + path) },
      { gapMs: 1, timeoutMs: 100, maxBytes: 256 },
    );
    clients.push(result);
    return result;
  };
  try {
    const normal = client('/');
    assert.equal((await normal.call('eth_chainId')).verdict, 'ok');
    assert.equal((await normal.call('eth_chainId')).reused, true);
    assert.equal((await normal.call('eth_chainId', [], true)).reused, false);
    assert.equal((await client('/large').call('eth_chainId')).verdict, 'response too large');
    assert.equal((await client('/hang').call('eth_chainId')).verdict, 'client timeout');
  } finally {
    clients.forEach((item) => item.close());
    server.closeAllConnections();
    server.close();
  }
});
