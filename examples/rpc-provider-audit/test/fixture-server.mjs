import { createServer } from 'node:http';
import { createHash } from 'node:crypto';
import { once } from 'node:events';

export const hash = (letter) => `0x${letter.repeat(64)}`;
const block = (height, pinned) => ({
  number: `0x${height.toString(16)}`,
  hash: pinned ?? hash('a'),
  parentHash: hash('f'),
  transactions: [hash('b')],
});
const result = (id, value) => ({ jsonrpc: '2.0', id, result: value });
const error = (id, code, message) => ({ jsonrpc: '2.0', id, error: { code, message } });
function frame(value) {
  const bytes = Buffer.from(JSON.stringify(value));
  const header = Buffer.alloc(bytes.length < 126 ? 2 : 4);
  header[0] = 0x81;
  if (bytes.length < 126) header[1] = bytes.length;
  else {
    header[1] = 126;
    header.writeUInt16BE(bytes.length, 2);
  }
  return Buffer.concat([header, bytes]);
}

export async function fixtureServer(pinnedHash) {
  const sockets = new Set();
  const methods = [];
  const server = createServer(async (request, response) => {
    let body = '';
    for await (const chunk of request) body += chunk;
    let payload;
    try {
      payload = JSON.parse(body);
    } catch {
      response.end(JSON.stringify(error(null, -32700, 'Parse error')));
      return;
    }
    const pruned = request.url.startsWith('/pruned');
    const answer = ({ id, method, params = [] }) => {
      methods.push(method);
      if (method === 'eth_chainId') return result(id, '0x1');
      if (method === 'eth_blockNumber') return result(id, '0x65');
      if (method === 'eth_getBlockByNumber') {
        const height = Number(BigInt(params[0]));
        return result(
          id,
          height === 1_000_000_000
            ? null
            : block(height, height === 15537394 ? pinnedHash : undefined),
        );
      }
      if (method === 'eth_getBalance' || method === 'eth_call') {
        if (pruned && params[1] !== 'latest')
          return error(id, -32000, 'Historical state unavailable');
        if (params[0] === '0x1234') return error(id, -32602, 'Invalid params');
        return result(id, method === 'eth_call' ? hash('1') : '0x123');
      }
      if (method === 'eth_getTransactionReceipt')
        return result(id, {
          transactionHash: params[0],
          blockHash: pinnedHash,
          blockNumber: '0xed14f2',
        });
      if (method === 'eth_getLogs') {
        const filter = params[0];
        const width = Number(BigInt(filter.toBlock) - BigInt(filter.fromBlock)) + 1;
        if (width > 500) {
          response.statusCode = pruned ? 429 : 400;
          return error(id, -32005, `Range exceeds 500 blocks; key=${request.url.split('/').at(-1)}`);
        }
        return result(id, [
          {
            blockNumber: filter.toBlock,
            blockHash: hash('a'),
            transactionHash: hash('b'),
            transactionIndex: '0x0',
            logIndex: '0x0',
            address: filter.address ?? `0x${'c'.repeat(40)}`,
            topics: filter.topics ?? [],
            data: '0x1234',
            removed: false,
          },
        ]);
      }
      return error(id, -32601, 'Method not found');
    };
    const output = Array.isArray(payload)
      ? payload.length
        ? payload.map(answer).reverse()
        : error(null, -32600, 'Invalid request')
      : answer(payload);
    response.setHeader('content-type', 'application/json');
    response.end(JSON.stringify(output));
  });
  server.on('upgrade', (request, socket) => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
    const accept = createHash('sha1')
      .update(`${request.headers['sec-websocket-key']}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`)
      .digest('base64');
    socket.write(
      `HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`,
    );
    let subscribed = false;
    socket.on('data', (chunk) => {
      if ((chunk[0] & 15) === 8) {
        socket.end(Buffer.from([0x88, 0]));
        return;
      }
      if (subscribed) return;
      subscribed = true;
      if (request.url.startsWith('/no-subscription')) {
        socket.write(frame(error(1, -32601, 'Subscription unavailable')));
        return;
      }
      socket.write(frame(result(1, 'fixture-subscription')));
      socket.write(
        frame({
          jsonrpc: '2.0',
          method: 'eth_subscription',
          params: {
            subscription: 'fixture-subscription',
            result: block(100),
          },
        }),
      );
    });
    socket.on('error', () => {});
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  return {
    port: server.address().port,
    methods,
    close() {
      for (const socket of sockets) socket.destroy();
      server.closeAllConnections();
      server.close();
    },
  };
}
