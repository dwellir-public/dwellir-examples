import { readFileSync } from 'node:fs';

const identifier = /^[a-zA-Z0-9_-]{1,64}$/;
export const readJson = (path) => JSON.parse(readFileSync(path, 'utf8'));

function bounded(value, min, max, label) {
  if (!Number.isSafeInteger(value) || value < min || value > max) {
    throw new Error(`${label} must be an integer between ${min} and ${max}`);
  }
  return value;
}

function endpointUrl(template, protocol, env, secrets) {
  if (typeof template !== 'string') throw new Error('Endpoint URL must be a string');
  const expanded = template.replace(/\$\{([A-Z][A-Z0-9_]*)\}/g, (_, name) => {
    if (!env[name]) throw new Error(`Missing environment variable ${name}`);
    secrets.push(env[name], encodeURIComponent(env[name]));
    return env[name];
  });
  const url = new URL(expanded);
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  const allowed = url.protocol === `${protocol}s:` || (loopback && url.protocol === `${protocol}:`);
  if (!allowed || url.username || url.password || url.hash) {
    throw new Error('Use HTTPS/WSS endpoints without userinfo or fragments');
  }
  secrets.push(expanded);
  return url;
}

function configureEndpoints(entries, env, secrets, resolveUrls) {
  if (!Array.isArray(entries) || !entries.length || entries.length > 6) {
    throw new Error('Configure 1 to 6 endpoints');
  }
  const names = new Set();
  return entries.map((entry) => {
    if (typeof entry.name !== 'string' || !identifier.test(entry.name) || names.has(entry.name))
      throw new Error('Use unique endpoint names');
    if (entry.priceId && !identifier.test(entry.priceId)) throw new Error('Invalid priceId');
    names.add(entry.name);
    return {
      name: entry.name,
      priceId: entry.priceId,
      http: resolveUrls ? endpointUrl(entry.http, 'http', env, secrets) : null,
      ws: resolveUrls && entry.ws ? endpointUrl(entry.ws, 'ws', env, secrets) : null,
    };
  });
}

function validateLogFilter(filter, logEnd) {
  if (!identifier.test(filter.name) || !/^0x[0-9a-f]{40}$/i.test(filter.address))
    throw new Error('Invalid log filter');
  if (filter.topics?.some((topic) => !/^0x[0-9a-f]{64}$/i.test(topic)))
    throw new Error('Invalid topic');
  if (!Array.isArray(filter.widths) || !filter.widths.length || filter.widths.length > 12)
    throw new Error('Choose 1 to 12 widths');
  for (const width of filter.widths) bounded(width, 1, Math.min(logEnd, 100_000), 'log width');
}

function validateProbe(probe) {
  if (
    !probe ||
    !/^0x[0-9a-f]{64}$/i.test(probe.blockHash) ||
    !/^0x[0-9a-f]+$/i.test(probe.chainId)
  ) {
    throw new Error('Provide a pinned chainId and blockHash');
  }
  bounded(probe.block, 1, 1_000_000_000, 'probe.block');
  if (!/^0x[0-9a-f]{40}$/i.test(probe.account) || !/^0x[0-9a-f]{40}$/i.test(probe.contract)) {
    throw new Error('Provide probe.account and probe.contract addresses');
  }
  if (!/^0x(?:[0-9a-f]{2})*$/i.test(probe.callData)) throw new Error('Invalid callData');
  if (
    !Array.isArray(probe.archiveBlocks) ||
    !probe.archiveBlocks.length ||
    probe.archiveBlocks.length > 12
  ) {
    throw new Error('Choose 1 to 12 archive blocks');
  }
  for (const block of probe.archiveBlocks) bounded(block, 1, 1_000_000_000, 'archive block');
  bounded(probe.logEnd, 1, 1_000_000_000, 'probe.logEnd');
  if (!Array.isArray(probe.logFilters) || !probe.logFilters.length || probe.logFilters.length > 4) {
    throw new Error('Choose 1 to 4 log filters');
  }
  for (const filter of probe.logFilters) validateLogFilter(filter, probe.logEnd);
  return probe;
}

function configureSettings(settings = {}) {
  return {
    gapMs: bounded(settings.gapMs ?? 500, 500, 60_000, 'gapMs'),
    timeoutMs: bounded(settings.timeoutMs ?? 15_000, 100, 60_000, 'timeoutMs'),
    maxBytes: bounded(settings.maxBytes ?? 8_388_608, 256, 33_554_432, 'maxBytes'),
    latencyRounds: bounded(settings.latencyRounds ?? 5, 1, 100, 'latencyRounds'),
    coldRounds: bounded(settings.coldRounds ?? 3, 1, 20, 'coldRounds'),
    observationSeconds: bounded(settings.observationSeconds ?? 60, 1, 3600, 'observationSeconds'),
    pollMs: bounded(settings.pollMs ?? 15_000, 1000, 60_000, 'pollMs'),
    graceMs: bounded(settings.graceMs ?? 2000, 0, 15_000, 'graceMs'),
  };
}

function validateWorkload(calls = {}) {
  for (const [method, count] of Object.entries(calls)) {
    if (!/^[a-zA-Z][a-zA-Z0-9_]+$/.test(method)) throw new Error('Invalid monthly method');
    bounded(count, 0, 1_000_000_000_000, 'monthly call count');
  }
  return calls;
}

export function loadConfig(path, env = process.env, { resolveUrls = true } = {}) {
  const config = readJson(path);
  const secrets = [];
  return {
    endpoints: configureEndpoints(config.endpoints, env, secrets, resolveUrls),
    probe: validateProbe(config.probe),
    settings: configureSettings(config.settings),
    monthlyCalls: validateWorkload(config.monthlyCalls),
    secrets,
  };
}

export function redact(value, secrets) {
  let text = String(value ?? '');
  for (const secret of [...secrets].sort((a, b) => b.length - a.length)) {
    if (secret) text = text.replaceAll(secret, '[redacted]');
  }
  return text
    .replace(/(?:https?|wss?):\/\/[^\s"<>]+/gi, '[endpoint]')
    .replace(/[\r\n|]/g, ' ')
    .slice(0, 200);
}
