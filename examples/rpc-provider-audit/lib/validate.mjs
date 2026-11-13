import { createHash } from 'node:crypto';

export const hex = (n) => `0x${n.toString(16)}`;
export const quantity = (value) =>
  typeof value === 'string' && /^0x(?:0|[1-9a-f][0-9a-f]*)$/i.test(value);
export const hash = (value) => typeof value === 'string' && /^0x[0-9a-f]{64}$/i.test(value);
const address = (value) => typeof value === 'string' && /^0x[0-9a-f]{40}$/i.test(value);
const data = (value) => typeof value === 'string' && /^0x(?:[0-9a-f]{2})*$/i.test(value);
const object = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const rpcErrorValid = (error) =>
  object(error) && Number.isInteger(error.code) && typeof error.message === 'string';

export function rpcResult(response, id = 1) {
  if (response.failure) return { verdict: response.failure };
  const httpFailure =
    response.status < 200 || response.status >= 300 ? `HTTP ${response.status}` : null;
  const body = response.body;
  if (!object(body) || body.jsonrpc !== '2.0' || body.id !== id)
    return { verdict: httpFailure ?? 'invalid envelope' };
  const hasResult = Object.hasOwn(body, 'result');
  const hasError = Object.hasOwn(body, 'error');
  if (hasResult === hasError) return { verdict: httpFailure ?? 'invalid envelope' };
  if (hasError) {
    if (!rpcErrorValid(body.error)) {
      return { verdict: httpFailure ?? 'invalid error' };
    }
    return {
      verdict: httpFailure ?? `RPC ${body.error.code}`,
      code: body.error.code,
      message: body.error.message,
    };
  }
  if (httpFailure) return { verdict: httpFailure };
  if (body.result === null) return { verdict: 'null' };
  return { verdict: 'ok', value: body.result };
}

export function blockValid(block, height, expectedHash) {
  return (
    object(block) &&
    quantity(block.number) &&
    BigInt(block.number) === BigInt(height) &&
    hash(block.hash) &&
    (!expectedHash || block.hash.toLowerCase() === expectedHash.toLowerCase()) &&
    Array.isArray(block.transactions) &&
    block.transactions.every(hash)
  );
}

export function receiptValid(receipt, tx, block) {
  return (
    object(receipt) &&
    hash(receipt.transactionHash) &&
    receipt.transactionHash.toLowerCase() === tx.toLowerCase() &&
    hash(receipt.blockHash) &&
    receipt.blockHash.toLowerCase() === block.hash.toLowerCase() &&
    quantity(receipt.blockNumber) &&
    BigInt(receipt.blockNumber) === BigInt(block.number)
  );
}

export function logFingerprint(logs, from, to, filter = {}) {
  if (!Array.isArray(logs)) return null;
  const seen = new Set();
  const canonical = [];
  for (const log of logs) {
    if (
      !object(log) ||
      !hash(log.blockHash) ||
      !hash(log.transactionHash) ||
      !quantity(log.blockNumber) ||
      !quantity(log.logIndex) ||
      !quantity(log.transactionIndex) ||
      !address(log.address) ||
      !data(log.data) ||
      !Array.isArray(log.topics) ||
      !log.topics.every(hash) ||
      log.removed !== false
    )
      return null;
    const height = BigInt(log.blockNumber);
    if (height < BigInt(from) || height > BigInt(to)) return null;
    if (filter.address && log.address.toLowerCase() !== filter.address.toLowerCase()) return null;
    if (filter.topics?.some((topic, i) => log.topics[i]?.toLowerCase() !== topic.toLowerCase()))
      return null;
    const key = `${log.blockHash.toLowerCase()}:${BigInt(log.logIndex)}`;
    if (seen.has(key)) return null;
    seen.add(key);
    canonical.push(
      JSON.stringify([
        height.toString(),
        log.blockHash.toLowerCase(),
        log.transactionHash.toLowerCase(),
        BigInt(log.transactionIndex).toString(),
        BigInt(log.logIndex).toString(),
        log.address.toLowerCase(),
        log.topics.map((topic) => topic.toLowerCase()),
        log.data.toLowerCase(),
        false,
      ]),
    );
  }
  return createHash('sha256').update(canonical.sort().join('\n')).digest('hex');
}

export function agreement(values) {
  const valid = values.filter((value) => value !== null && value !== undefined);
  const counts = new Map();
  for (const value of valid) counts.set(value, (counts.get(value) ?? 0) + 1);
  const winner = [...counts].find(([, count]) => count >= 2 && count > valid.length / 2)?.[0];
  return values.map((value) => {
    if (value === null || value === undefined) return 'unavailable';
    if (valid.length < 2) return 'unverified';
    if (winner === undefined) return 'no quorum';
    return value === winner ? 'match' : 'disagrees';
  });
}

export function percentile(values, percent) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return Math.round(sorted[Math.ceil((percent * sorted.length) / 100) - 1]);
}
