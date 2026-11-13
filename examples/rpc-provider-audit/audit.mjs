import { writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { loadConfig, readJson, redact } from './lib/config.mjs';
import { createClient } from './lib/transport.mjs';
import { correctness, archive, logCaps, errorShapes } from './lib/probes.mjs';
import { latency, observe } from './lib/observe.mjs';
import { priceWorkload, validatePrices } from './lib/pricing.mjs';
import { renderReport } from './lib/report.mjs';

const args = process.argv.slice(2);
if (args[0] === '--help') {
  console.log(
    'Usage: node audit.mjs [config.json] [prices.json] [report-prefix]\nUse --cost-only before the paths for offline workload pricing.',
  );
  process.exit(0);
}
const costOnly = args[0] === '--cost-only';
if (costOnly) args.shift();
let clients = [];
let config;
try {
  const [configPath = 'config.json', pricePath = 'prices.json', output = 'report'] = args;
  if (args.length > 3) throw new Error('Expected config, prices and output prefix');
  config = loadConfig(resolve(configPath), process.env, { resolveUrls: !costOnly });
  const prices = validatePrices(readJson(resolve(pricePath)));
  const cost = config.endpoints.map((endpoint) => ({
    endpoint: endpoint.name,
    ...priceWorkload(
      prices.plans.find((plan) => plan.id === endpoint.priceId),
      config.monthlyCalls,
    ),
  }));
  const report = {
    recordedAt: new Date().toISOString(),
    settings: config.settings,
    conditions: {
      chainId: config.probe.chainId,
      pinnedBlock: config.probe.block,
      pinnedHash: config.probe.blockHash,
      archiveBlocks: config.probe.archiveBlocks,
      logFilters: config.probe.logFilters,
      logEnd: config.probe.logEnd,
      monthlyCalls: config.monthlyCalls,
    },
    cost,
    correctness: [],
    archive: [],
    logs: [],
    errors: [],
    latency: [],
    freshness: [],
    websocket: [],
    requests: [],
  };
  if (!costOnly) {
    if (typeof WebSocket !== 'function')
      throw new Error('Use Node.js 22.15 or newer for built-in WebSocket support');
    clients = config.endpoints.map((endpoint) => createClient(endpoint, config.settings));
    const checked = await correctness(clients, config.probe);
    report.correctness = checked.rows;
    const eligible = checked.eligible;
    report.archive = await archive(eligible, config.probe);
    report.logs = await logCaps(eligible, config.probe);
    report.errors = await errorShapes(eligible, config.probe);
    report.latency = await latency(eligible, config.probe, config.settings);
    Object.assign(report, await observe(eligible, config.settings));
    report.requests = clients.map((client) => ({ endpoint: client.name, calls: client.count() }));
  }
  const safe = JSON.parse(
    JSON.stringify(report, (_, value) =>
      typeof value === 'string' ? redact(value, config.secrets) : value,
    ),
  );
  // Source URLs contain no credentials and belong in the report's pricing evidence.
  safe.cost.forEach((row, i) => {
    const source = cost[i].sourceUrl;
    row.sourceUrl =
      source && !config.secrets.some((secret) => secret && source.includes(secret))
        ? source
        : undefined;
  });
  writeFileSync(`${output}.json`, `${JSON.stringify(safe, null, 2)}\n`, { mode: 0o600 });
  writeFileSync(`${output}.md`, renderReport(safe), { mode: 0o600 });
  console.log('Wrote the JSON and Markdown reports. Review failures before choosing a provider.');
} catch (error) {
  console.error(
    config
      ? redact(error.message, config.secrets)
      : 'Invalid configuration. Check the file, environment variables and README.',
  );
  process.exitCode = 1;
} finally {
  clients.forEach((client) => client.close());
}
