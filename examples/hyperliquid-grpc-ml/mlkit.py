"""Small, causal building blocks for learning from bars.

Everything here only uses data up to the current bar, so the same code runs
in a backtest and on a live stream. numpy and pandas only.
"""

from collections import deque

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Rolling statistics (pandas conventions: variance divides by n - 1)
# ---------------------------------------------------------------------------

def zscore(s, n):
    return (s - s.rolling(n).mean()) / s.rolling(n).std()


def imbalance(a, b, n):
    """(a - b) / (a + b) over the last n bars. 0 when nothing traded."""
    num = a.rolling(n).sum() - b.rolling(n).sum()
    den = a.rolling(n).sum() + b.rolling(n).sum()
    return (num / den).where(den > 0, 0.0)


def parkinson_vol(high, low, n):
    """Per-bar volatility from the high-low range, not annualized."""
    return np.sqrt((np.log(high / low) ** 2).rolling(n).mean() / (4 * np.log(2)))


def forward_log_return(close, h):
    """The label: log return over the next h bars. Unknown until h bars later."""
    return np.log(close.shift(-h) / close)


# ---------------------------------------------------------------------------
# Labels a model cannot see early
# ---------------------------------------------------------------------------

class ForwardLabels:
    """Hold each bar's inputs and hand them back h bars later with the return.

    update() returns None until the first label exists, then (x_then, ret).
    Training only on what this returns keeps the future out of the model.
    """

    def __init__(self, h):
        self.h = h
        self.queue = deque()

    def update(self, x, price):
        self.queue.append((x, price))
        if len(self.queue) <= self.h:
            return None
        x_then, price_then = self.queue.popleft()
        return x_then, float(np.log(price / price_then))


# ---------------------------------------------------------------------------
# Regression that learns one bar at a time
# ---------------------------------------------------------------------------

class RLS:
    """Recursive least squares with an intercept, exponential forgetting and ridge.

    forget=0.995 gives older bars 0.5% less weight per bar (half-life ~138
    bars). ridge shrinks the slopes toward 0 but leaves the intercept alone.
    """

    def __init__(self, n_inputs, forget=0.995, ridge=1.0):
        self.forget = forget
        self.w = np.zeros(n_inputs + 1)
        self.P = np.diag([1e6] + [1.0 / ridge] * n_inputs)

    def predict(self, x):
        return float(self.w @ np.r_[1.0, x])

    def update(self, y, x):
        """Learn from (x, y). Returns (fitted, residual) from before the update."""
        z = np.r_[1.0, x]
        fitted = float(self.w @ z)
        if y is None or not np.isfinite(y) or not np.all(np.isfinite(z)):
            return fitted, np.nan
        Pz = self.P @ z
        k = Pz / (self.forget + z @ Pz)
        self.w = self.w + k * (y - fitted)
        self.P = (self.P - np.outer(k, Pz)) / self.forget
        # Rounding makes P drift away from symmetric; over ~100k updates that
        # compounds until P and the forecasts blow up. Re-symmetrize each step.
        self.P = (self.P + self.P.T) / 2
        return fitted, y - fitted


# ---------------------------------------------------------------------------
# Scoring a forecast
# ---------------------------------------------------------------------------

def newey_west_t(f, r, lags):
    """t-statistic of b in r = a + b*f, with HAC errors for overlapping labels."""
    X = np.column_stack([np.ones_like(f), f])
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ r
    u = r - X @ beta
    Xu = X * u[:, None]
    S = Xu.T @ Xu
    for lag in range(1, lags + 1):
        w = 1 - lag / (lags + 1)
        G = Xu[lag:].T @ Xu[:-lag]
        S += w * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    return beta[1] / np.sqrt(V[1, 1])


def score(forecast, close, horizons=(1, 5, 15), fwd=None, delay=0):
    """Grade a forecast against the h-bar log returns that followed it.

    Pass fwd(h) instead of close to score against some other forward move,
    such as a spread. delay=1 starts each return one bar later, as if you
    could only trade on the bar after the forecast. An edge that disappears
    with delay=1 usually comes from bid-ask bounce in the last trade price.

    ic   correlation of forecast and return (information coefficient)
    hit  share of bars where forecast and return have the same sign (flat returns skipped)
    t    Newey-West t of the slope with h - 1 lags, so overlap does not inflate it
    n    pairs scored
    """
    rows = []
    for h in horizons:
        r = (fwd(h) if fwd else forward_log_return(close, h)).shift(-delay)
        ok = forecast.notna() & r.notna() & (forecast != 0)
        f, y = forecast[ok].to_numpy(), r[ok].to_numpy()
        rows.append({
            "h": h,
            "ic": np.corrcoef(f, y)[0, 1],
            "hit": np.mean(np.sign(f[y != 0]) == np.sign(y[y != 0])),
            "t": newey_west_t(f, y, max(h - 1, 0)),
            "n": len(f),
        })
    return pd.DataFrame(rows).set_index("h")


# ---------------------------------------------------------------------------
# Kalman filter for a drifting hedge ratio
# ---------------------------------------------------------------------------

class KalmanBeta:
    """Track y = alpha + beta * x with alpha and beta as random walks.

    delta sets how fast the coefficients may drift; obs_var is the noise
    around the line. The defaults suit log prices divided by their first
    value, sampled every minute: tune them so z has a std near 1. update() returns the spread (this bar's surprise) and
    its z-score, both from the estimate made before seeing this bar.
    """

    def __init__(self, delta=1e-8, obs_var=1e-7, init_var=1e-2):
        self.theta = np.zeros(2)
        self.P = init_var * np.eye(2)
        self.Q = delta / (1 - delta) * np.eye(2)
        self.R = obs_var

    def update(self, y, x):
        z = np.array([1.0, x])
        self.P = self.P + self.Q
        spread = y - z @ self.theta
        S = z @ self.P @ z + self.R
        K = self.P @ z / S
        self.theta = self.theta + K * spread
        self.P = self.P - np.outer(K, z) @ self.P
        return {"alpha": self.theta[0], "beta": self.theta[1], "spread": spread, "z": spread / np.sqrt(S)}


# ---------------------------------------------------------------------------
# Principal components and walk-forward regression on them
# ---------------------------------------------------------------------------

def pca(X, k):
    """Exact PCA of a (rows x inputs) array. Columns are standardized first.

    Each component's largest loading is made positive, so a component keeps
    its sign from one refit to the next.
    """
    mu, sd = X.mean(0), X.std(0, ddof=1)
    Z = (X - mu) / sd
    vals, vecs = np.linalg.eigh(np.cov(Z, rowvar=False))
    order = np.argsort(vals)[::-1][:k]
    vals, vecs = vals[order], vecs[:, order]
    vecs *= np.sign(vecs[np.abs(vecs).argmax(0), np.arange(k)])
    return {"mu": mu, "sd": sd, "loadings": vecs, "explained": vals / np.trace(np.cov(Z, rowvar=False))}


def walk_forward_pcr(X, close, h, window=720, k=3, refit=60):
    """Forecast the h-bar return from the first k components of X.

    Every `refit` bars, fit the components and an OLS on them using the last
    `window` bars whose labels are already known (they end h bars before
    now), then freeze both until the next refit. Each stretch is forecast by
    a fit that only saw the bars before it.
    """
    X = X.dropna()
    y = forward_log_return(close, h).reindex(X.index)
    A, Y = X.to_numpy(), y.to_numpy()
    out = pd.Series(np.nan, index=X.index)
    fits = []
    for t in range(window + h, len(A), refit):
        train = slice(t - h - window, t - h)
        ok = np.isfinite(Y[train])
        p = pca(A[train][ok], k)
        scores = ((A[train][ok] - p["mu"]) / p["sd"]) @ p["loadings"]
        D = np.column_stack([np.ones(len(scores)), scores])
        coef, *_ = np.linalg.lstsq(D, Y[train][ok], rcond=None)
        ahead = slice(t, min(t + refit, len(A)))
        s_ahead = ((A[ahead] - p["mu"]) / p["sd"]) @ p["loadings"]
        out.iloc[ahead] = coef[0] + s_ahead @ coef[1:]
        fits.append({"time": X.index[t], "explained": p["explained"], "coef": coef[1:]})
    return out, fits
