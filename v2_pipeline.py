"""
XCCY Basis Monitor V2 — True CIP Basis via IBKR FX Forwards

Replaces the proxy basis (EURIBOR − SOFR) with the true CIP deviation
computed from observed FX forward prices.

True CIP basis formula
──────────────────────
  basis(T) = [(1 + r_USD·T) · (S/F) − 1] / T  −  r_EUR(T)

  where:
    S       = EUR/USD spot (USD per EUR)
    F       = EUR/USD forward at tenor T (from CME 6E futures)
    r_USD   = SOFR compounded T-day average (from FRED, % p.a.)
    r_EUR   = ESTR overnight (from FRED, % p.a.)
    T       = tenor in years (act/360 money market convention)

  Negative basis → USD expensive vs FX-hedged EUR (consistent with
  traded quotes of ~−5 bps, not the −170 bps from rate differential).

Data source: IBKR TWS (or IB Gateway)
  - EUR/USD spot  : Forex('EURUSD') — daily midpoint
  - 6E futures    : CME quarterly contracts (Mar/Jun/Sep/Dec)
                    used as forward prices at each expiry tenor
  - Tenors mapped : 3M ≈ front quarterly, 6M ≈ 2nd, 1Y ≈ 4th

Prerequisites
─────────────
  1. TWS or IB Gateway running on this machine
     Paper trading : port 7497   (recommended for historical pulls)
     Live trading  : port 7496
  2. Enable API in TWS: File → Global Configuration → API → Settings
     ☑ Enable ActiveX and Socket Clients
     Socket port: 7497 (paper) or 7496 (live)
  3. pip install ib_insync

Run:
  python v2_pipeline.py [--port 7497] [--lookback 2]
  → data/v2_true_basis.csv
  → data/v2_vs_proxy.csv   (comparison of V1 proxy vs V2 true basis)
"""

import argparse
import logging
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from ib_insync import IB, ContFuture, Forex, Future, util

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent / "data"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)
util.logToConsole(logging.WARNING)   # suppress ib_insync chatter

# CME 6E quarterly expiry months and IMM month codes
IMM_MONTHS = {3: "H", 6: "M", 9: "U", 12: "Z"}

# Tenors: (target_days, max_futures_to_use)
# We map each tenor to the futures contract whose expiry is nearest
TENORS = {
    "3M":  91,
    "6M":  182,
    "1Y":  365,
}

# Daycount: money market act/360 for USD, act/360 for EUR (ESTR)
ACT_BASIS = 360

# ---------------------------------------------------------------------------
# IBKR helpers
# ---------------------------------------------------------------------------

def connect(port: int, client_id: int = 10) -> IB:
    ib = IB()
    log.info("Connecting to IBKR TWS on port %d ...", port)
    try:
        ib.connect("127.0.0.1", port, clientId=client_id, timeout=10)
        log.info("Connected. Account: %s", ib.managedAccounts())
        return ib
    except Exception as e:
        raise ConnectionError(
            f"Could not connect to TWS on port {port}. "
            "Make sure TWS / IB Gateway is running and API is enabled.\n"
            f"Error: {e}"
        )


def fetch_historical(ib: IB, contract, duration: str,
                     bar_size: str = "1 day",
                     what: str = "MIDPOINT") -> pd.Series:
    """Fetch daily historical bars, return a close-price Series indexed by date."""
    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr=duration,
        barSizeSetting=bar_size,
        whatToShow=what,
        useRTH=True,
        formatDate=1,
    )
    if not bars:
        return pd.Series(dtype=float)
    df = util.df(bars)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["close"]


# ---------------------------------------------------------------------------
# EUR/USD spot
# ---------------------------------------------------------------------------

def fetch_spot(ib: IB, lookback_years: int) -> pd.Series:
    log.info("Fetching EUR/USD spot ...")
    contract = Forex("EURUSD")
    ib.qualifyContracts(contract)
    duration = f"{lookback_years} Y"
    spot = fetch_historical(ib, contract, duration)
    log.info("  Spot: %d obs  %s → %s",
             len(spot), spot.index[0].date(), spot.index[-1].date())
    return spot.rename("EURUSD_spot")


# ---------------------------------------------------------------------------
# CME 6E futures
# ---------------------------------------------------------------------------

def build_6e_expiries(lookback_years: int) -> list[dict]:
    """
    Generate CME 6E quarterly expiry calendar.
    Returns list of dicts: {lastTradeDateOrContractMonth, expiry_date}
    Expiry = 3rd Wednesday of the expiry month (IMM rule).
    """
    today = date.today()
    start_year = today.year - lookback_years - 1
    contracts = []
    for year in range(start_year, today.year + 2):
        for month in [3, 6, 9, 12]:
            # IMM date: 3rd Wednesday
            d = date(year, month, 1)
            wednesdays = [d + timedelta(days=i)
                          for i in range(31) if (d + timedelta(days=i)).weekday() == 2]
            expiry = wednesdays[2]   # 3rd Wednesday
            if expiry < date(today.year - lookback_years, 1, 1):
                continue
            code = f"{year}{month:02d}"
            contracts.append({"code": code, "expiry": expiry})
    return contracts


def fetch_6e_series(ib: IB, lookback_years: int) -> pd.DataFrame:
    """
    Fetch daily close prices for each CME 6E quarterly contract.
    Stitches them into a DataFrame indexed by date with expiry as columns.
    Keeps only dates when each contract was "live" (< 1 year from expiry).
    """
    expiries = build_6e_expiries(lookback_years)
    log.info("Fetching %d CME 6E futures contracts ...", len(expiries))

    all_series = {}
    for cfg in expiries:
        contract = Future(
            symbol="EUR",
            lastTradeDateOrContractMonth=cfg["code"],
            exchange="CME",
            currency="USD",
            multiplier="125000",
        )
        try:
            details = ib.qualifyContracts(contract)
            if not details:
                continue
        except Exception:
            continue

        duration = f"{min(lookback_years + 1, 2)} Y"
        try:
            series = fetch_historical(ib, contract, duration)
        except Exception as e:
            log.warning("  %s: failed (%s)", cfg["code"], e)
            continue

        if series.empty:
            continue

        # Trim to dates within ~1 year before expiry (contract is front/2nd month)
        expiry_dt = pd.Timestamp(cfg["expiry"])
        series = series[series.index <= expiry_dt + timedelta(days=5)]
        cutoff = expiry_dt - timedelta(days=365)
        series = series[series.index >= cutoff]

        if not series.empty:
            all_series[cfg["expiry"]] = series
            log.info("  6E %s: %d obs  %s → %s",
                     cfg["code"], len(series),
                     series.index[0].date(), series.index[-1].date())

        time.sleep(0.3)   # respect IBKR pacing (50 req / 10s)

    if not all_series:
        raise RuntimeError("No 6E futures data retrieved. Check TWS connection.")

    df = pd.DataFrame(all_series)
    df.columns = pd.to_datetime(df.columns)
    df.index = pd.to_datetime(df.index)
    return df


# ---------------------------------------------------------------------------
# Forward rate extraction
# ---------------------------------------------------------------------------

def extract_forward(futures_df: pd.DataFrame, spot: pd.Series,
                    target_days: int) -> pd.Series:
    """
    For each date, find the futures contract whose expiry is closest to
    date + target_days, and return its price as the forward rate.

    Also returns the actual T (in years, act/360) for that expiry.
    """
    expiries = pd.to_datetime(futures_df.columns)
    fwd_prices = []
    actual_T = []

    for dt in futures_df.index:
        target_expiry = dt + timedelta(days=target_days)
        diffs = np.abs((expiries - target_expiry).days)
        best = expiries[diffs.argmin()]

        # Only use if expiry is within 45 days of target tenor
        if diffs.min() > 45:
            fwd_prices.append(np.nan)
            actual_T.append(np.nan)
            continue

        price = futures_df.loc[dt, best]
        if pd.isna(price):
            fwd_prices.append(np.nan)
            actual_T.append(np.nan)
        else:
            fwd_prices.append(price)
            t = (best - dt).days / ACT_BASIS
            actual_T.append(t)

    idx = futures_df.index
    return (pd.Series(fwd_prices, index=idx),
            pd.Series(actual_T, index=idx))


# ---------------------------------------------------------------------------
# CIP basis computation
# ---------------------------------------------------------------------------

def compute_cip_basis(spot: pd.Series,
                      forward: pd.Series,
                      t_years: pd.Series,
                      r_usd: pd.Series,
                      r_eur: pd.Series) -> pd.Series:
    """
    True CIP basis in bps:
        basis = [(1 + r_USD·T) · (S/F) − 1] / T  −  r_EUR

    All rates in decimal (e.g. 0.036 for 3.6%).
    Returns basis in bps.
    """
    r_usd_dec = r_usd / 100
    r_eur_dec = r_eur / 100

    implied_eur = ((1 + r_usd_dec * t_years) * (spot / forward) - 1) / t_years
    basis_dec = implied_eur - r_eur_dec
    return basis_dec * 10_000   # → bps


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(port: int, lookback_years: int):
    DATA_DIR.mkdir(exist_ok=True)

    # 1. Connect
    ib = connect(port)

    try:
        # 2. Spot
        spot = fetch_spot(ib, lookback_years)

        # 3. Futures
        futures_df = fetch_6e_series(ib, lookback_years)

    finally:
        ib.disconnect()
        log.info("Disconnected from TWS.")

    # 4. Load USD and EUR OIS rates from V1 pipeline
    raw_file = DATA_DIR / "rates_raw.csv"
    if not raw_file.exists():
        raise FileNotFoundError(
            "data/rates_raw.csv not found — run pipeline.py first."
        )
    rates = pd.read_csv(raw_file, index_col=0, parse_dates=True)

    # SOFR compounded averages (% p.a.)
    sofr = {
        "3M": rates["SOFR_90D"].combine_first(rates["TBILL_3M"]),
        "6M": rates["SOFR_180D"].combine_first(rates["TBILL_6M"]),
        "1Y": rates["TBILL_1Y"],
    }
    # EUR OIS: ESTR → ECB DFR
    estr = rates["ESTR_ON"].combine_first(rates["ECB_DFR"])

    # 5. Align all series to a common business-day index
    common_idx = (spot.index
                  .intersection(futures_df.index)
                  .intersection(estr.dropna().index))
    spot     = spot.reindex(common_idx).ffill()
    estr_a   = estr.reindex(common_idx).ffill()
    futures_a = futures_df.reindex(common_idx).ffill()

    # 6. Compute true CIP basis at each tenor
    out_rows = {"EURUSD_spot": spot}
    for tenor, days in TENORS.items():
        fwd, t_yrs = extract_forward(futures_a, spot, days)
        r_usd = sofr[tenor].reindex(common_idx).ffill()

        basis = compute_cip_basis(spot, fwd, t_yrs, r_usd, estr_a)
        basis.name = f"cip_basis_{tenor}"

        out_rows[f"fwd_{tenor}"]        = fwd
        out_rows[f"T_actual_{tenor}"]   = t_yrs
        out_rows[f"r_USD_{tenor}"]      = r_usd
        out_rows[f"r_EUR_implied_{tenor}"] = (
            (1 + r_usd / 100 * t_yrs) * (spot / fwd) - 1
        ) / t_yrs * 100
        out_rows[f"cip_basis_{tenor}"]  = basis

        valid = basis.dropna()
        if len(valid):
            log.info("cip_basis_%-4s  %d obs  mean=%+.2f bps  min=%+.2f  max=%+.2f  first=%s",
                     tenor, len(valid),
                     valid.mean(), valid.min(), valid.max(),
                     valid.index[0].date())

    result = pd.DataFrame(out_rows)

    # 7. Save
    out_path = DATA_DIR / "v2_true_basis.csv"
    result.to_csv(out_path)
    log.info("Saved %s (%d rows, %d cols)", out_path.name, len(result), len(result.columns))

    # 8. Comparison: V1 proxy vs V2 true basis
    proxy_file = DATA_DIR / "basis_proxy.csv"
    if proxy_file.exists():
        proxy = pd.read_csv(proxy_file, index_col=0, parse_dates=True)
        cip_cols    = [c for c in result.columns if c.startswith("cip_basis_")]
        proxy_cols  = [f"basis_{t}" for t in TENORS if f"basis_{t}" in proxy.columns]
        comparison  = result[cip_cols].join(
            proxy[proxy_cols].add_suffix("_proxy"),
            how="inner"
        ).dropna()
        comp_path   = DATA_DIR / "v2_vs_proxy.csv"
        comparison.to_csv(comp_path)
        log.info("Saved %s (%d rows)", comp_path.name, len(comparison))
        log.info("\n--- V2 (true CIP) vs V1 (rate differential) ---\n%s",
                 comparison.describe().round(2).to_string())

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="XCCY V2 — True CIP basis via IBKR")
    parser.add_argument("--port", type=int, default=7497,
                        help="TWS/Gateway port (7497=paper, 7496=live)")
    parser.add_argument("--lookback", type=int, default=2,
                        help="Years of historical data to fetch (default 2)")
    args = parser.parse_args()
    main(port=args.port, lookback_years=args.lookback)
