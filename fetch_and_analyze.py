"""
Energy & FX Market Monitor — data pipeline
AD International Consulting

Downloads public market data (no API key needed), cleans it, computes the
analytics shown on the dashboard and writes them to data/data.json.

Sources
- FRED, Federal Reserve Bank of St. Louis: Brent (DCOILBRENTEU), WTI (DCOILWTICO),
  Henry Hub natural gas (DHHNGSP) spot prices, daily.
- European Central Bank: euro reference rates against USD and CNY, daily.
  USD/CNY is derived as (CNY per EUR) / (USD per EUR).
"""

import io
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

START = "2021-01-01"
OUT = Path(__file__).parent / "data" / "data.json"

FRED = {
    "brent": "DCOILBRENTEU",
    "wti": "DCOILWTICO",
    "henry_hub": "DHHNGSP",
}
ECB_URL = (
    "https://data-api.ecb.europa.eu/service/data/EXR/D.USD+CNY.EUR.SP00.A"
    f"?format=csvdata&startPeriod={START}"
)

LABELS = {
    "brent": "Brent crude (USD/bbl)",
    "wti": "WTI crude (USD/bbl)",
    "henry_hub": "Henry Hub gas (USD/MMBtu)",
    "eurusd": "EUR/USD",
    "usdcny": "USD/CNY",
}

VOL_WINDOW = 30        # trading days for realised volatility
CORR_WINDOW = 90       # trading days for correlations
HORIZON = 20           # forecast horizon, trading days (~1 month)
FC_VOL_WINDOW = 60     # volatility window used for forecast bands
BACKTEST_YEARS = 3


def get(url: str, attempts: int = 4) -> str:
    """Download with retries: public data servers are sometimes slow from cloud runners."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; energy-fx-monitor/1.1; +https://adupassieux-arch.github.io)",
        "Accept": "text/csv,text/plain,*/*",
    }
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read().decode("utf-8")
        except Exception as e:  # network errors, HTTP errors, timeouts
            last = e
            wait = 10 * 2 ** i
            print(f"  attempt {i + 1}/{attempts} failed for {url[:80]}…: {e!r}", file=sys.stderr)
            if i < attempts - 1:
                time.sleep(wait)
    raise RuntimeError(f"Download failed after {attempts} attempts: {url}") from last


def load_fred(series_id: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(get(
        f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={START}")))
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")  # FRED uses "." for missing
    s = df.dropna().set_index("date")["value"]
    return s[s.index >= START]


def load_ecb() -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(get(ECB_URL)), usecols=["CURRENCY", "TIME_PERIOD", "OBS_VALUE"])
    df["TIME_PERIOD"] = pd.to_datetime(df["TIME_PERIOD"])
    wide = df.pivot(index="TIME_PERIOD", columns="CURRENCY", values="OBS_VALUE").dropna()
    return pd.DataFrame({
        "eurusd": wide["USD"],
        "usdcny": wide["CNY"] / wide["USD"],
    })


def pct(a, b):
    return None if (a is None or b is None or b == 0) else float(a / b - 1)


def value_at_or_before(s: pd.Series, when: pd.Timestamp):
    sub = s[s.index <= when]
    return float(sub.iloc[-1]) if len(sub) else None


def kpis(s: pd.Series, logret: pd.Series) -> dict:
    last_date = s.index[-1]
    last = float(s.iloc[-1])
    year_ago = s[s.index > last_date - pd.Timedelta(days=365)]
    ytd_base = value_at_or_before(s, pd.Timestamp(year=last_date.year - 1, month=12, day=31))
    vol = float(logret.tail(VOL_WINDOW).std() * np.sqrt(252))
    return {
        "last": last,
        "last_date": last_date.strftime("%Y-%m-%d"),
        "chg_1w": pct(last, value_at_or_before(s, last_date - pd.Timedelta(days=7))),
        "chg_1m": pct(last, value_at_or_before(s, last_date - pd.DateOffset(months=1))),
        "chg_ytd": pct(last, ytd_base),
        "chg_1y": pct(last, value_at_or_before(s, last_date - pd.DateOffset(years=1))),
        "high_52w": float(year_ago.max()),
        "low_52w": float(year_ago.min()),
        "vol_30d": vol,
    }


def random_walk_band(last: float, sigma_d: float, h: int):
    """Driftless log random walk: median = last price, bands from daily vol."""
    steps = np.arange(1, h + 1)
    sd = sigma_d * np.sqrt(steps)
    z80, z95 = 1.2816, 1.9600
    return {
        "median": [last] * h,
        "lo80": (last * np.exp(-z80 * sd)).tolist(),
        "hi80": (last * np.exp(z80 * sd)).tolist(),
        "lo95": (last * np.exp(-z95 * sd)).tolist(),
        "hi95": (last * np.exp(z95 * sd)).tolist(),
    }


def backtest(s: pd.Series, h: int = HORIZON) -> dict:
    """Rolling-origin test of the random-walk forecast at horizon h.
    Each week over the last BACKTEST_YEARS years: forecast = price today,
    80% band from trailing vol; compare with the price h trading days later."""
    lr = np.log(s).diff()
    start = s.index[-1] - pd.DateOffset(years=BACKTEST_YEARS)
    idx = [i for i in range(FC_VOL_WINDOW, len(s) - h) if s.index[i] >= start][::5]
    errs, hits = [], []
    for i in idx:
        p0, p1 = s.iloc[i], s.iloc[i + h]
        sigma = lr.iloc[i - FC_VOL_WINDOW + 1: i + 1].std()
        errs.append(abs(p1 / p0 - 1))
        band = 1.2816 * sigma * np.sqrt(h)
        hits.append(abs(np.log(p1 / p0)) <= band)
    return {
        "n_forecasts": len(idx),
        "mape": float(np.mean(errs)),
        "coverage_80": float(np.mean(hits)),
        "horizon_days": h,
        "years": BACKTEST_YEARS,
    }


def main():
    print("Downloading…")
    # If a source is unreachable, keep last week's series for it rather than failing the update.
    previous = {}
    if OUT.exists():
        prev = json.loads(OUT.read_text())
        previous = {k: pd.Series(v["v"], index=pd.to_datetime(v["d"]))
                    for k, v in prev.get("prices", {}).items()}

    def fallback(keys, err):
        missing = [k for k in keys if k not in previous]
        if missing:
            raise RuntimeError(f"No data for {missing} and no previous copy") from err
        print(f"  WARNING: kept previous data for {keys} ({err})", file=sys.stderr)
        stale.extend(keys)
        return {k: previous[k] for k in keys}

    frames, stale = {}, []
    for k, sid in FRED.items():
        try:
            frames[k] = load_fred(sid)
        except Exception as e:
            frames.update(fallback([k], e))
    try:
        fx = load_ecb()
        frames["eurusd"] = fx["eurusd"]
        frames["usdcny"] = fx["usdcny"]
    except Exception as e:
        frames.update(fallback(["eurusd", "usdcny"], e))
    if len(stale) == len(frames):
        raise RuntimeError("Every source failed; leaving the dashboard unchanged.")

    # Each series keeps its own trading calendar for its own statistics.
    series = {k: v.sort_index() for k, v in frames.items()}
    logrets = {k: np.log(v).diff().dropna() for k, v in series.items()}

    # Common calendar (dates where every market printed) for cross-asset analytics.
    panel = pd.DataFrame(series).dropna()
    rets = np.log(panel).diff().dropna()

    out = {
        "meta": {
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "start": START,
            "stale": stale,
            "labels": LABELS,
            "sources": {
                "brent": "FRED DCOILBRENTEU (U.S. EIA)",
                "wti": "FRED DCOILWTICO (U.S. EIA)",
                "henry_hub": "FRED DHHNGSP (U.S. EIA)",
                "eurusd": "ECB euro reference rate",
                "usdcny": "Derived from ECB euro reference rates (CNY/EUR ÷ USD/EUR)",
            },
            "windows": {"vol": VOL_WINDOW, "corr": CORR_WINDOW, "horizon": HORIZON,
                         "fc_vol": FC_VOL_WINDOW},
        },
        "kpis": {k: kpis(series[k], logrets[k]) for k in series},
        "prices": {k: {"d": [d.strftime("%Y-%m-%d") for d in v.index],
                       "v": [round(float(x), 4) for x in v.values]}
                   for k, v in series.items()},
    }

    # Brent–WTI spread on common Brent/WTI dates
    bw = pd.concat([series["brent"], series["wti"]], axis=1, keys=["b", "w"], sort=True).dropna()
    spread = bw["b"] - bw["w"]
    out["spread"] = {"d": [d.strftime("%Y-%m-%d") for d in spread.index],
                     "v": [round(float(x), 3) for x in spread.values],
                     "last": float(spread.iloc[-1]),
                     "avg_1y": float(spread[spread.index > spread.index[-1] - pd.Timedelta(days=365)].mean())}

    # Rolling realised volatility, annualised
    vol = {}
    for k, r in logrets.items():
        rv = (r.rolling(VOL_WINDOW).std() * np.sqrt(252)).dropna()
        vol[k] = {"d": [d.strftime("%Y-%m-%d") for d in rv.index],
                  "v": [round(float(x), 4) for x in rv.values]}
    out["volatility"] = vol

    # Correlations of daily log returns
    keys = list(series.keys())
    recent = rets.tail(CORR_WINDOW)
    out["corr_matrix"] = {
        "keys": keys,
        "recent": recent[keys].corr().round(3).values.tolist(),
        "window_start": recent.index[0].strftime("%Y-%m-%d"),
        "full_period": rets[keys].corr().round(3).values.tolist(),
    }
    pairs = [("brent", "usdcny"), ("brent", "eurusd"), ("brent", "henry_hub"), ("brent", "wti")]
    rc = {}
    for a, b in pairs:
        c = rets[a].rolling(CORR_WINDOW).corr(rets[b]).dropna()
        rc[f"{a}|{b}"] = {"d": [d.strftime("%Y-%m-%d") for d in c.index],
                          "v": [round(float(x), 3) for x in c.values]}
    out["rolling_corr"] = rc

    # One-month forecast bands + honest backtest
    fc = {}
    for k in ["brent", "eurusd", "usdcny"]:
        s = series[k]
        sigma = float(logrets[k].tail(FC_VOL_WINDOW).std())
        future = pd.bdate_range(s.index[-1] + pd.Timedelta(days=1), periods=HORIZON)
        fc[k] = {"d": [d.strftime("%Y-%m-%d") for d in future],
                 **random_walk_band(float(s.iloc[-1]), sigma, HORIZON),
                 "backtest": backtest(s)}
    out["forecast"] = fc

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(f"Wrote {OUT} ({OUT.stat().st_size/1024:.0f} KB)")
    for k, v in out["kpis"].items():
        print(f"  {k:10s} {v['last']:>10.4f} on {v['last_date']}  1m {v['chg_1m']:+.1%}  vol30 {v['vol_30d']:.1%}")


if __name__ == "__main__":
    sys.exit(main())
