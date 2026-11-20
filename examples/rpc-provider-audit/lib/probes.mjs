import {
  agreement,
  blockValid,
  hash,
  hex,
  logFingerprint,
  quantity,
  receiptValid,
} from './validate.mjs';

function row(client, check, response, valid) {
  const verdict =
    response.verdict === 'ok' && !valid(response.value) ? 'invalid result' : response.verdict;
  return {
    endpoint: client.name,
    check,
    verdict,
    http: response.status ?? null,
    code: response.code ?? null,
    message: response.message ?? '',
    ms: Math.round(response.ms),
  };
}

export async function correctness(clients, probe) {
  const rows = [];
  const eligible = [];
  for (const client of clients) {
    const chain = await client.call('eth_chainId');
    rows.push(
      row(
        client,
        'chain identifier',
        chain,
        (value) => quantity(value) && BigInt(value) === BigInt(probe.chainId),
      ),
    );
    if (rows.at(-1).verdict !== 'ok') continue;
    const block = await client.call('eth_getBlockByNumber', [hex(probe.block), false]);
    rows.push(
      row(client, 'pinned block hash', block, (value) =>
        blockValid(value, probe.block, probe.blockHash),
      ),
    );
    if (rows.at(-1).verdict === 'ok') eligible.push(client);
  }
  return { rows, eligible };
}

export async function archive(clients, probe) {
  const rows = [];
  for (const height of probe.archiveBlocks) {
    const stateRows = [];
    const values = [];
    for (const client of clients) {
      const block = await client.call('eth_getBlockByNumber', [hex(height), false]);
      rows.push(row(client, `body at ${height}`, block, (value) => blockValid(value, height)));
      const balance = await client.call('eth_getBalance', [probe.account, hex(height)]);
      rows.push(row(client, `balance at ${height}`, balance, quantity));
      const state = await client.call('eth_call', [
        { to: probe.contract, data: probe.callData },
        hex(height),
      ]);
      const stateRow = row(
        client,
        `contract state at ${height}`,
        state,
        (value) => typeof value === 'string' && /^0x[0-9a-f]{64}$/i.test(value),
      );
      stateRows.push(stateRow);
      values.push(stateRow.verdict === 'ok' ? state.value.toLowerCase() : null);
      if (
        block.verdict === 'ok' &&
        blockValid(block.value, height) &&
        block.value.transactions.length
      ) {
        const tx = block.value.transactions[0];
        const receipt = await client.call('eth_getTransactionReceipt', [tx]);
        rows.push(
          row(client, `receipt at ${height}`, receipt, (value) =>
            receiptValid(value, tx, block.value),
          ),
        );
      } else {
        rows.push({
          endpoint: client.name,
          check: `receipt at ${height}`,
          verdict: 'not tested',
          message: 'No validated transaction',
        });
      }
      const logs = await client.call('eth_getLogs', [
        { fromBlock: hex(height), toBlock: hex(height) },
      ]);
      rows.push({
        ...row(
          client,
          `logs at ${height}`,
          logs,
          (value) => logFingerprint(value, height, height) !== null,
        ),
        count: Array.isArray(logs.value) ? logs.value.length : null,
      });
    }
    agreement(values).forEach((comparison, index) => {
      rows.push({ ...stateRows[index], comparison });
    });
  }
  return rows;
}

export async function logCaps(clients, probe) {
  const rows = [];
  for (const filter of probe.logFilters) {
    const alive = new Set(clients);
    for (const width of filter.widths) {
      const from = probe.logEnd - width + 1;
      const answers = [];
      for (const client of alive) {
        const response = await client.call('eth_getLogs', [
          {
            address: filter.address,
            ...(filter.topics ? { topics: filter.topics } : {}),
            fromBlock: hex(from),
            toBlock: hex(probe.logEnd),
          },
        ]);
        const fingerprint = logFingerprint(response.value, from, probe.logEnd, filter);
        answers.push({ client, response, fingerprint });
      }
      const comparisons = agreement(answers.map((answer) => answer.fingerprint));
      answers.forEach(({ client, response, fingerprint }, index) => {
        const result = row(
          client,
          `${filter.name}, ${width} blocks`,
          response,
          () => fingerprint !== null,
        );
        const comparison = comparisons[index];
        rows.push({
          ...result,
          comparison,
          fingerprint,
          count: fingerprint ? response.value.length : null,
          bytes: response.bytes,
          fromBlock: from,
          toBlock: probe.logEnd,
        });
        if (result.verdict !== 'ok' || comparison !== 'match') alive.delete(client);
      });
      if (!alive.size) break;
    }
  }
  return rows;
}

export async function errorShapes(clients, probe) {
  const request = (id, method, params) => ({ jsonrpc: '2.0', id, method, params });
  const cases = [
    ['unknown method', JSON.stringify(request(1, 'eth_doesNotExist', []))],
    ['invalid address', JSON.stringify(request(1, 'eth_getBalance', ['0x1234', 'latest']))],
    ['missing block', JSON.stringify(request(1, 'eth_getBlockByNumber', ['0x3b9aca00', false]))],
    ['malformed JSON', '{"jsonrpc":"2.0",'],
    ['empty batch', '[]'],
    [
      'partial batch',
      JSON.stringify([request(1, 'eth_chainId', []), request(2, 'eth_doesNotExist', [])]),
    ],
  ];
  const rows = [];
  for (const [check, body] of cases) {
    for (const client of clients) {
      const response = await client.post(body);
      const members = Array.isArray(response.body) ? response.body : [response.body];
      const shapes = members.map((member) => ({
        id: member?.id ?? null,
        code: member?.error?.code ?? null,
        message: member?.error?.message ?? '',
        result:
          member?.result === null
            ? 'null'
            : Object.hasOwn(member ?? {}, 'result')
              ? 'present'
              : 'absent',
      }));
      const batchValid =
        check !== 'partial batch' ||
        (members.length === 2 &&
          members.some(
            (member) =>
              member?.id === 1 &&
              member.jsonrpc === '2.0' &&
              member.result === probe.chainId &&
              !member.error,
          ) &&
          members.some(
            (member) =>
              member?.id === 2 &&
              member.jsonrpc === '2.0' &&
              Number.isInteger(member.error?.code) &&
              !Object.hasOwn(member, 'result'),
          ));
      rows.push({
        endpoint: client.name,
        check,
        http: response.status ?? null,
        verdict: response.failure ?? (batchValid ? 'recorded' : 'invalid batch'),
        shapes,
      });
    }
  }
  return rows;
}

export function latencyMethods(probe, head) {
  return [
    ['eth_blockNumber', [], quantity],
    ['eth_call', [{ to: probe.contract, data: probe.callData }, 'latest'], (value) => hash(value)],
    ['eth_getBalance', [probe.account, 'latest'], quantity],
    ['eth_getBlockByNumber', [hex(head), false], (value) => blockValid(value, head)],
  ];
}
