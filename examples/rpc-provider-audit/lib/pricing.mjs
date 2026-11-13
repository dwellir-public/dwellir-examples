const nonnegative = (n) => Number.isFinite(n) && n >= 0;
const sourceValid = (source) => typeof source === 'string' && source.startsWith('https://');
const cents = (value) => Math.round((value + Number.EPSILON) * 100) / 100;

function validatePlan(plan) {
  if (
    !sourceValid(plan.sourceUrl) ||
    !/^\d{4}-\d{2}-\d{2}$/.test(plan.checkedAt) ||
    !Number.isFinite(Date.parse(plan.checkedAt))
  )
    throw new Error('Each price needs a source URL and checkedAt date');
  if (plan.model === 'unresolved') {
    if (!plan.reason) throw new Error('Unresolved prices need a reason');
    return;
  }
  if (!['responses', 'compute-units'].includes(plan.model))
    throw new Error('Unsupported price model');
  if (![plan.monthlyUsd, plan.includedUnits, plan.overageUsdPerMillion].every(nonnegative)) {
    throw new Error('Prices and included units must be nonnegative numbers');
  }
  if (plan.model === 'compute-units') {
    if (!plan.weights || !sourceValid(plan.weightsSourceUrl))
      throw new Error('Compute-unit plans need sourced method weights');
    if (!Object.values(plan.weights).every((weight) => nonnegative(weight)))
      throw new Error('Invalid method weight');
  }
}

export function validatePrices(prices) {
  if (!prices || !Array.isArray(prices.plans)) throw new Error('Pricing file needs plans');
  const ids = new Set();
  for (const plan of prices.plans) {
    if (!plan.id || ids.has(plan.id)) throw new Error('Price IDs must be unique');
    ids.add(plan.id);
    validatePlan(plan);
  }
  return prices;
}

export function priceWorkload(plan, calls, now = new Date()) {
  if (!plan) return { verdict: 'unpriced', estimatedUsd: null, reason: 'No matching priceId' };
  const ageDays = Math.floor((now - new Date(`${plan.checkedAt}T00:00:00Z`)) / 86_400_000);
  const evidence = {
    plan: plan.name,
    sourceUrl: plan.sourceUrl,
    checkedAt: plan.checkedAt,
    ageDays,
    stale: ageDays > 30,
    scope: plan.scope,
  };
  if (ageDays < 0)
    return {
      ...evidence,
      verdict: 'unpriced',
      estimatedUsd: null,
      reason: 'Price date is in the future',
    };
  if (plan.model === 'unresolved')
    return { ...evidence, verdict: 'unpriced', estimatedUsd: null, reason: plan.reason };
  const active = Object.entries(calls).filter(([, count]) => count > 0);
  if (!active.length)
    return { ...evidence, verdict: 'unpriced', estimatedUsd: null, reason: 'No monthly workload' };
  const missing = active.filter(
    ([method]) => plan.model === 'compute-units' && !Object.hasOwn(plan.weights, method),
  );
  if (missing.length)
    return {
      ...evidence,
      verdict: 'unpriced',
      estimatedUsd: null,
      reason: `Missing method weights: ${missing.map(([method]) => method).join(', ')}`,
    };
  const breakdown = active.map(([method, count]) => ({
    method,
    calls: count,
    weight: plan.model === 'responses' ? 1 : plan.weights[method],
  }));
  const units = breakdown.reduce((total, item) => total + item.calls * item.weight, 0);
  const overageUnits = Math.max(0, units - plan.includedUnits);
  const overageUsd = cents((overageUnits / 1_000_000) * plan.overageUsdPerMillion);
  if (!Number.isSafeInteger(units))
    return {
      ...evidence,
      verdict: 'unpriced',
      estimatedUsd: null,
      reason: 'Workload exceeds safe integer range',
    };
  return {
    ...evidence,
    verdict: 'priced',
    unit: plan.model,
    breakdown,
    units,
    includedUnits: plan.includedUnits,
    subscriptionUsd: plan.monthlyUsd,
    overageUnits,
    overageUsd,
    estimatedUsd: cents(plan.monthlyUsd + overageUsd),
    rounding: 'Round overage to USD cents, then add the monthly subscription',
  };
}
