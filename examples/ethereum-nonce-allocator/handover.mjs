import { reconcile } from './nonces.mjs';

const result = reconcile([], { latest: 42n, pending: 42n }, 42n, 'unknown', 42n);
console.log(result);
// { action: 'ok', lowestUnresolved: null, notCounted: [], usedNeedReceipt: [], next: 42n }
