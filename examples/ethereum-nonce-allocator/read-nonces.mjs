import { readNonces } from './nonces.mjs';

async function requireEthereumMainnet(url) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    signal: AbortSignal.timeout(10_000),
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'eth_chainId', params: [] }),
  });
  if (!response.ok) throw new Error('Chain identity request failed');
  const body = await response.json();
  if (body?.jsonrpc !== '2.0' || body.id !== 1 || body.error || body.result !== '0x1') {
    throw new Error('Expected Ethereum mainnet');
  }
}

async function main() {
  if (!process.env.DWELLIR_API_KEY) throw new Error('Set DWELLIR_API_KEY');
  if (!process.env.SENDER) throw new Error('Set SENDER to a 20-byte address');
  const url = `https://api-ethereum-mainnet.n.dwellir.com/${process.env.DWELLIR_API_KEY}`;
  await requireEthereumMainnet(url);
  const view = await readNonces(url, process.env.SENDER);
  console.log(view);
}

main().catch(() => {
  console.error('Nonce read failed. Check DWELLIR_API_KEY, SENDER, network access, and the mainnet response.');
  process.exitCode = 1;
});
