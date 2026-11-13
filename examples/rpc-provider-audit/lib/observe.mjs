import { setTimeout as sleep } from 'node:timers/promises';
import { blockValid, hash, hex, percentile, quantity } from './validate.mjs';
import { latencyMethods } from './probes.mjs';

async function measureMethod(client, method, params, validate, attempts, cold) {
  const samples = [];
  let failed = 0;
  let reused = 0;
  let lastFailure = '';
  for (let i = 0; i < attempts; i++) {
    const result = await client.call(method, params, cold);
    if (result.verdict === 'ok' && validate(result.value)) samples.push(result.ms);
    else {
      failed++;
      lastFailure = result.verdict === 'ok' ? 'invalid result' : result.verdict;
    }
    if (result.reused) reused++;
  }
  return {
    attempted: attempts,
    succeeded: samples.length,
    failed,
    reused,
    p50Ms: percentile(samples, 50),
    p95Ms: percentile(samples, 95),
    lastFailure,
  };
}

export async function latency(clients, probe, settings) {
  const rows = [];
  for (const client of clients) {
    const head = await client.call('eth_blockNumber');
    if (
      head.verdict !== 'ok' ||
      !quantity(head.value) ||
      !Number.isSafeInteger(Number(BigInt(head.value)))
    ) {
      rows.push({ endpoint: client.name, check: 'latency', verdict: 'no usable head' });
      continue;
    }
    const height = Number(BigInt(head.value));
    const methods = [['cold eth_blockNumber', [], quantity], ...latencyMethods(probe, height)];
    for (const [method, params, validate] of methods) {
      const cold = method.startsWith('cold ');
      rows.push({
        endpoint: client.name,
        check: method,
        ...(await measureMethod(
          client,
          method.replace('cold ', ''),
          params,
          validate,
          cold ? settings.coldRounds : settings.latencyRounds,
          cold,
        )),
      });
    }
  }
  return rows;
}

function receiveSubscription(state, message) {
  if (message.error) {
    state.error = `subscription RPC ${message.error.code}`;
    return;
  }
  if (message.jsonrpc !== '2.0' || typeof message.result !== 'string') {
    state.invalid++;
    return;
  }
  state.subscription = message.result;
  state.subscribed = true;
  state.activeAt = performance.now();
}

function receiveHeader(state, message) {
  if (
    !state.subscribed ||
    message.method !== 'eth_subscription' ||
    message.params?.subscription !== state.subscription
  ) {
    state.invalid++;
    return;
  }
  const header = message.params?.result;
  if (!quantity(header?.number) || !hash(header?.hash) || !hash(header?.parentHash)) {
    state.invalid++;
    return;
  }
  const height = Number(BigInt(header.number));
  if (!Number.isSafeInteger(height)) {
    state.invalid++;
    return;
  }
  const previous = state.seen.get(height);
  state.notifications++;
  if (previous?.hash === header.hash.toLowerCase()) state.repeats++;
  else if (previous) state.reorgs++;
  state.seen.set(height, { hash: header.hash.toLowerCase(), received: performance.now() });
}

function startStream(client) {
  const state = {
    seen: new Map(),
    subscribed: false,
    notifications: 0,
    repeats: 0,
    reorgs: 0,
    disconnects: 0,
    invalid: 0,
    error: '',
    activeAt: null,
  };
  if (!client.ws) return { state, stop() {} };
  const socket = new WebSocket(client.ws);
  socket.addEventListener('open', () =>
    socket.send(
      JSON.stringify({
        jsonrpc: '2.0',
        id: 1,
        method: 'eth_subscribe',
        params: ['newHeads'],
      }),
    ),
  );
  socket.addEventListener('message', (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      state.invalid++;
      return;
    }
    if (!message || typeof message !== 'object') {
      state.invalid++;
      return;
    }
    if (message.id === 1) receiveSubscription(state, message);
    else receiveHeader(state, message);
  });
  let stopping = false;
  socket.addEventListener('error', () => {
    state.error = 'WebSocket connection error';
  });
  socket.addEventListener('close', () => {
    if (!stopping) {
      state.disconnects++;
    }
  });
  return {
    state,
    stop() {
      stopping = true;
      socket.close();
    },
  };
}

function streamSummary(state, samples, configured) {
  if (!configured) return { verdict: 'not tested', missing: null, reason: 'No WebSocket URL' };
  if (!state.subscribed)
    return {
      verdict: 'unverified',
      missing: null,
      reason: state.error || 'No subscription acknowledgement',
    };
  const heights = [...state.seen.keys()];
  const eligible = samples.filter((sample) => sample.at >= state.activeAt);
  const lower = heights.length ? Math.min(...heights) : eligible[0]?.height;
  const upper = Math.max(-1, ...heights, ...eligible.map((sample) => sample.height));
  if (lower === undefined || upper < lower)
    return { verdict: 'unverified', missing: null, reason: 'No comparable heads' };
  const width = upper - lower + 1;
  if (width > 100_000)
    return { verdict: 'unverified', missing: null, reason: 'Implausible head span' };
  let missing = 0;
  for (let height = lower; height <= upper; height++) if (!state.seen.has(height)) missing++;
  const conflicts = eligible.filter(
    (sample) => state.seen.has(sample.height) && state.seen.get(sample.height).hash !== sample.hash,
  ).length;
  return {
    verdict:
      state.error || state.invalid || state.disconnects || missing || conflicts
        ? 'investigate'
        : 'observed',
    from: lower,
    to: upper,
    missing,
    conflicts,
    notifications: state.notifications,
    repeats: state.repeats,
    reorgs: state.reorgs,
    invalid: state.invalid,
    disconnects: state.disconnects,
    reason: state.error,
  };
}

async function sampleHead(client, row, history) {
  const head = await client.call('eth_blockNumber');
  if (
    head.verdict !== 'ok' ||
    !quantity(head.value) ||
    !Number.isSafeInteger(Number(BigInt(head.value)))
  ) {
    row.failed++;
    return null;
  }
  const height = Number(BigInt(head.value));
  const block = await client.call('eth_getBlockByNumber', [hex(height), false]);
  if (block.verdict !== 'ok' || !blockValid(block.value, height)) {
    row.unservable++;
    return null;
  }
  const previous = history.at(-1);
  if (previous && height < previous.height) row.backwards++;
  const sample = { height, hash: block.value.hash.toLowerCase(), at: performance.now() };
  history.push(sample);
  row.samples++;
  return sample;
}

export async function observe(clients, settings) {
  if (!clients.length) return { freshness: [], websocket: [] };
  const streams = clients.map(startStream);
  const samples = clients.map(() => []);
  const rows = clients.map((client) => ({
    endpoint: client.name,
    check: 'HTTP head',
    samples: 0,
    failed: 0,
    unservable: 0,
    backwards: 0,
    sameHeightConflicts: 0,
    maxRelativeLag: null,
  }));
  const end = performance.now() + settings.observationSeconds * 1000;
  let round = 0;
  try {
    while (performance.now() < end) {
      const started = performance.now();
      const seen = [];
      for (let offset = 0; offset < clients.length; offset++) {
        const index = (offset + round) % clients.length;
        const client = clients[index];
        const row = rows[index];
        const sample = await sampleHead(client, row, samples[index]);
        if (sample) seen.push({ index, ...sample });
      }
      for (const sample of seen) {
        const row = rows[sample.index];
        row.maxRelativeLag = Math.max(
          row.maxRelativeLag ?? 0,
          ...seen.map((other) => other.height - sample.height),
        );
        if (seen.some((other) => other.height === sample.height && other.hash !== sample.hash))
          row.sameHeightConflicts++;
      }
      round++;
      await sleep(Math.max(0, Math.min(end, started + settings.pollMs) - performance.now()));
    }
    await sleep(settings.graceMs);
  } finally {
    streams.forEach((stream) => stream.stop());
  }
  return {
    freshness: rows,
    websocket: clients.map((client, index) => ({
      endpoint: client.name,
      check: 'newHeads',
      ...streamSummary(streams[index].state, samples[index], Boolean(client.ws)),
    })),
  };
}
