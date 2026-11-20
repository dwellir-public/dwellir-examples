import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fixtureServer } from './fixture-server.mjs';

const root = new URL('../', import.meta.url);
const example = JSON.parse(readFileSync(new URL('config.example.json', root)));
function run(args, env) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [new URL('audit.mjs', root).pathname, ...args], {
      cwd: root,
      env,
    });
    let output = '';
    child.stdout.on('data', (chunk) => {
      output += chunk;
    });
    child.stderr.on('data', (chunk) => {
      output += chunk;
    });
    child.on('close', (code) => resolve({ code, output }));
  });
}

test('CLI reports archive failures, log caps, pricing, batch members and a final WebSocket gap without leaking credentials', {
  timeout: 120_000,
}, async () => {
  const directory = mkdtempSync(join(tmpdir(), 'rpc-audit-test-'));
  const server = await fixtureServer(example.probe.blockHash);
  const key = 'fixture-secret-never-print';
  const config = structuredClone(example);
  config.endpoints = [
    {
      name: 'fixture-complete',
      http: `http://127.0.0.1:${server.port}/complete/\${FIXTURE_KEY}`,
      ws: `ws://127.0.0.1:${server.port}/complete/\${FIXTURE_KEY}`,
      priceId: 'dwellir-developer',
    },
    {
      name: 'fixture-pruned',
      http: `http://127.0.0.1:${server.port}/pruned/\${FIXTURE_KEY}`,
      priceId: 'alchemy-payg',
    },
  ];
  config.endpoints.push({
    name: 'fixture-unsubscribed',
    http: `http://127.0.0.1:${server.port}/complete/\${FIXTURE_KEY}`,
    ws: `ws://127.0.0.1:${server.port}/no-subscription/\${FIXTURE_KEY}`,
  });
  config.probe.archiveBlocks = [15537394];
  config.probe.logFilters = [config.probe.logFilters[0]];
  config.probe.logFilters[0].widths = [1, 501];
  Object.assign(config.settings, {
    latencyRounds: 1,
    coldRounds: 1,
    observationSeconds: 1,
    pollMs: 1000,
    graceMs: 100,
  });
  const configPath = join(directory, 'config.json');
  const output = join(directory, 'report');
  writeFileSync(configPath, JSON.stringify(config));
  try {
    const result = await run([configPath, new URL('prices.json', root).pathname, output], {
      ...process.env,
      FIXTURE_KEY: key,
    });
    assert.equal(result.code, 0, result.output);
    const json = readFileSync(`${output}.json`, 'utf8');
    const markdown = readFileSync(`${output}.md`, 'utf8');
    assert.ok(![json, markdown, result.output].some((value) => value.includes(key)));
    const report = JSON.parse(json);
    assert.ok(report.correctness.every((row) => row.verdict === 'ok'));
    assert.ok(
      report.archive.some(
        (row) => row.endpoint === 'fixture-pruned' && row.verdict === 'RPC -32000',
      ),
    );
    assert.ok(
      report.archive.some((row) => row.check.startsWith('receipt') && row.verdict === 'ok'),
    );
    assert.equal(report.cost[0].estimatedUsd, 49);
    assert.equal(report.cost[1].estimatedUsd, 118.56);
    for (const [endpoint, status] of [
      ['fixture-complete', 400],
      ['fixture-pruned', 429],
    ]) {
      const cap = report.logs.find((row) => row.endpoint === endpoint && row.http === status);
      assert.equal(cap.verdict, `HTTP ${status}`);
      assert.equal(cap.code, -32005);
      assert.match(cap.message, /Range exceeds 500 blocks/);
      assert.ok(!cap.message.includes(key));
      assert.equal(cap.fingerprint, null);
      assert.equal(cap.count, null);
      assert.equal(cap.comparison, 'unavailable');
    }
    assert.ok(report.logs.some((row) => row.comparison === 'match'));
    assert.ok(
      report.errors.some(
        (row) =>
          row.check === 'partial batch' &&
          row.verdict === 'recorded' &&
          row.shapes.some((member) => member.code === -32601),
      ),
    );
    assert.equal(report.websocket[0].missing, 1);
    assert.equal(report.websocket[0].to, 101);
    assert.equal(report.websocket[1].missing, null);
    assert.equal(report.websocket[2].missing, null);
    assert.equal(report.websocket[2].verdict, 'unverified');
    assert.ok(report.latency.every((row) => row.failed === 0));
    assert.ok(server.methods.every((method) => !/send|sign|submit/i.test(method)));
    if (process.env.AUDIT_FIXTURE_REPORT) {
      writeFileSync(`${process.env.AUDIT_FIXTURE_REPORT}.json`, json);
      writeFileSync(`${process.env.AUDIT_FIXTURE_REPORT}.md`, markdown);
    }
  } finally {
    server.close();
    rmSync(directory, { recursive: true, force: true });
  }
});

test('CLI rejects absent credentials before a network call and leaves no report', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'rpc-audit-config-'));
  const configPath = join(directory, 'config.json');
  writeFileSync(configPath, JSON.stringify(example));
  try {
    const result = await run(
      [configPath, new URL('prices.json', root).pathname, join(directory, 'report')],
      {},
    );
    assert.equal(result.code, 1);
    assert.match(result.output, /Invalid configuration/);
    assert.throws(() => readFileSync(join(directory, 'report.json')));
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test('cost-only CLI prices the monthly mix without credentials or network calls', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'rpc-audit-cost-'));
  try {
    const output = join(directory, 'cost');
    const result = await run(
      [
        '--cost-only',
        new URL('config.example.json', root).pathname,
        new URL('prices.json', root).pathname,
        output,
      ],
      {},
    );
    assert.equal(result.code, 0, result.output);
    const report = JSON.parse(readFileSync(`${output}.json`));
    assert.equal(report.cost[0].estimatedUsd, 49);
    assert.equal(report.cost[1].estimatedUsd, 118.56);
    assert.deepEqual(report.requests, []);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
