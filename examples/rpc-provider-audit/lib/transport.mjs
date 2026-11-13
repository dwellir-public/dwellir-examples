import http from 'node:http';
import https from 'node:https';
import { setTimeout as sleep } from 'node:timers/promises';
import { rpcResult } from './validate.mjs';

export function createClient(endpoint, settings) {
  const protocol = endpoint.http.protocol === 'https:' ? https : http;
  const agent = new protocol.Agent({ keepAlive: true, maxSockets: 1 });
  let last = 0;
  let calls = 0;
  async function post(body, cold = false) {
    await sleep(Math.max(0, last + settings.gapMs - Date.now()));
    last = Date.now();
    calls++;
    return new Promise((resolve) => {
      const start = performance.now();
      const chunks = [];
      let bytes = 0;
      let settled = false;
      const finish = (extra) => {
        if (settled) return;
        settled = true;
        clearTimeout(deadline);
        resolve({ ms: performance.now() - start, bytes, reused: request.reusedSocket, ...extra });
      };
      const request = protocol.request(
        endpoint.http,
        {
          method: 'POST',
          agent: cold ? false : agent,
          headers: {
            'content-type': 'application/json',
            'content-length': Buffer.byteLength(body),
          },
        },
        (response) => {
          response.on('data', (chunk) => {
            bytes += chunk.length;
            if (bytes > settings.maxBytes) {
              finish({ status: response.statusCode, failure: 'response too large' });
              response.destroy();
              return;
            }
            chunks.push(chunk);
          });
          response.on('error', () =>
            finish({ status: response.statusCode, failure: 'response interrupted' }),
          );
          response.on('end', () => {
            let parsed;
            try {
              parsed = JSON.parse(Buffer.concat(chunks).toString('utf8'));
            } catch {
              finish({ status: response.statusCode, failure: 'invalid JSON' });
              return;
            }
            finish({ status: response.statusCode, body: parsed });
          });
        },
      );
      request.on('error', () => finish({ failure: 'connection failed' }));
      const deadline = setTimeout(() => {
        finish({ failure: 'client timeout' });
        request.destroy();
      }, settings.timeoutMs);
      request.end(body);
    });
  }
  return {
    ...endpoint,
    post,
    async call(method, params = [], cold = false) {
      const response = await post(JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }), cold);
      return { ...response, ...rpcResult(response) };
    },
    count: () => calls,
    close: () => agent.destroy(),
  };
}
