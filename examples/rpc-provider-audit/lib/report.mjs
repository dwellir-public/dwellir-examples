function cell(value) {
  if (value === null || value === undefined) return 'n/a';
  return String(value)
    .replaceAll('|', '/')
    .replace(/[\r\n]/g, ' ');
}
function table(columns, rows) {
  return [
    `| ${columns.map(([name]) => name).join(' | ')} |`,
    `| ${columns.map(() => '---').join(' | ')} |`,
    ...rows.map((row) => `| ${columns.map(([, key]) => cell(row[key])).join(' | ')} |`),
  ].join('\n');
}

export function renderReport(report) {
  const parts = [
    '# RPC provider audit',
    '',
    `Recorded ${report.recordedAt}.`,
    '',
    'Read capability failures before latency. A match is agreement, not proof of correctness.',
    '',
    `HTTP spacing: ${report.settings.gapMs} ms per endpoint. Timeout: ${report.settings.timeoutMs} ms.`,
    `Observation window: ${report.settings.observationSeconds} seconds, plus ${report.settings.graceMs} ms grace.`,
    '',
    '## Monthly workload cost',
    '',
    table(
      [
        ['Endpoint', 'endpoint'],
        ['Plan', 'plan'],
        ['USD/month estimate', 'cost'],
        ['Scope or reason', 'note'],
      ],
      report.cost.map((row) => ({
        ...row,
        cost: row.estimatedUsd === null ? 'unpriced' : `$${row.estimatedUsd.toFixed(2)}`,
        note: row.reason ?? row.scope,
      })),
    ),
    '',
    'Subscription plus metered overage. Taxes, support, capacity add-ons and unlisted products are excluded.',
    'One response per configured HTTP call. Add retries and backfill splits to the monthly mix; WebSocket messages need a separate quote.',
    'These are workload calculations, not usage-counter readings or complete invoice quotes.',
    '',
    '## Price sources',
    '',
    ...report.cost
      .filter((row) => row.sourceUrl)
      .map(
        (row) =>
          `- ${row.endpoint}: ${row.sourceUrl}, checked ${row.checkedAt}${row.stale ? ' (older than 30 days; refresh before buying)' : ''}.`,
      ),
  ];
  const columns = [
    ['Endpoint', 'endpoint'],
    ['Check', 'check'],
    ['Result', 'verdict'],
    ['HTTP', 'http'],
    ['RPC', 'code'],
    ['Agreement', 'comparison'],
    ['Count', 'count'],
    ['ms', 'ms'],
    ['Message', 'message'],
  ];
  for (const key of ['correctness', 'archive', 'logs']) {
    parts.push('', `## ${key[0].toUpperCase()}${key.slice(1)}`, '', table(columns, report[key]));
  }
  parts.push(
    '',
    '## Error shapes',
    '',
    table(
      [
        ['Endpoint', 'endpoint'],
        ['Case', 'check'],
        ['HTTP', 'http'],
        ['Result', 'verdict'],
        ['Members', 'members'],
      ],
      report.errors.map((row) => ({ ...row, members: JSON.stringify(row.shapes) })),
    ),
  );
  parts.push(
    '',
    '## Latency',
    '',
    'Percentiles use successful, validated responses only. Reused counts show actual socket reuse.',
    '',
    table(
      [
        ['Endpoint', 'endpoint'],
        ['Method', 'check'],
        ['Attempted', 'attempted'],
        ['OK', 'succeeded'],
        ['Failed', 'failed'],
        ['Reused', 'reused'],
        ['p50 ms', 'p50Ms'],
        ['p95 ms', 'p95Ms'],
        ['Last failure', 'lastFailure'],
      ],
      report.latency,
    ),
  );
  parts.push(
    '',
    '## Freshness',
    '',
    'Lag is relative to the highest validated head in the polling round, not the chain tip.',
    '',
    table(
      [
        ['Endpoint', 'endpoint'],
        ['Samples', 'samples'],
        ['Failed', 'failed'],
        ['Unservable', 'unservable'],
        ['Went back', 'backwards'],
        ['Hash conflicts', 'sameHeightConflicts'],
        ['Max relative lag', 'maxRelativeLag'],
      ],
      report.freshness,
    ),
  );
  parts.push(
    '',
    '## WebSocket gaps',
    '',
    table(
      [
        ['Endpoint', 'endpoint'],
        ['Result', 'verdict'],
        ['From', 'from'],
        ['Through', 'to'],
        ['Missing', 'missing'],
        ['Hash conflicts', 'conflicts'],
        ['Repeats', 'repeats'],
        ['Reorgs', 'reorgs'],
        ['Disconnects', 'disconnects'],
        ['Note', 'reason'],
      ],
      report.websocket,
    ),
  );
  parts.push(
    '',
    'A missing URL or failed subscription is untested/unverified, never zero gaps.',
    'The gap range includes the last HTTP height, after a grace period. It starts at the first notification, or the first comparable HTTP sample.',
    'Disconnects require investigation. Streams do not reconnect or backfill in this audit.',
    '',
    '## HTTP request counts',
    '',
    ...report.requests.map((row) => `- ${row.endpoint}: ${row.calls}`),
    '',
  );
  return parts.join('\n');
}
