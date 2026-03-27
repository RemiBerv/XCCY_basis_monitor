"""
XCCY Basis Monitor — Step 1: Data Pipeline

Fetches OIS rates and EUR/USD FX data from FRED and yfinance, aligns to a
common business-day calendar, and saves to data/.

Data sources (all verified to exist on FRED as of 2026):
  FRED  — OIS rates, T-bill rates, EURIBOR (monthly), EUR/USD spot
  yfinance — EUR/USD spot cross-check

Available series and their limitations
───────────────────────────────────────
USD term rates (daily):
  SOFR_ON       : overnight SOFR, from Apr 2018
  SOFR_30D      : 30-day compounded SOFR avg, from Apr 2018  ≈ 1M
  SOFR_90D      : 90-day compounded SOFR avg, from Apr 2018  ≈ 3M
  SOFR_180D     : 180-day compounded SOFR avg, from Apr 2018 ≈ 6M
  TBILL_3M      : 3M T-bill (discount basis), full history   ≈ 3M pre-2018
  TBILL_6M      : 6M T-bill (discount basis), full history   ≈ 6M pre-2018
  TBILL_1Y      : 1Y T-bill (discount basis), full history   ≈ 1Y pre-2018

EUR rates:
  ESTR_ON       : overnight ESTR, from Oct 2019
  ECB_DFR       : ECB deposit facility rate (monthly), full history — used as
                  EUR overnight proxy before ESTR
  EURIBOR_3M    : 3M EURIBOR from OECD (monthly, forward-filled to daily)

FX:
  EURUSD_SPOT   : EUR/USD spot from FRED (business day)
  EURUSD_YF     : EUR/USD spot from yfinance (cross-check)

Proxy basis:
  basis_ON  = ESTR_ON  - SOFR_ON      (both daily OIS, from Oct 2019)
  basis_3M  = EURIBOR_3M - SOFR_90D   (monthly EUR vs daily USD, from 2018)

  Positive basis → EUR rates > USD rates (EUR expensive, USD cheap).
  Negative basis → USD expensive relative to FX-hedged EUR (classic stress signal).

  The true traded XCCY basis comes from FX forward quotes (Bloomberg FXFA etc.).
  Plug those into compute_true_basis() when available.

Run:
  pip install -r requirements.txt
  cp .env.example .env   # set FRED_API_KEY
  python pipeline.py
"""

import os
import logging
from pathlib import Path

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from fredapi import Fred

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()

START_DATE = "2010-01-01"
END_DATE = pd.Timestamp.today().normalize().strftime("%Y-%m-%d")
DATA_DIR = Path(__file__).parent / "data"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FRED series catalogue  (all verified to exist on FRED)
# ---------------------------------------------------------------------------

FRED_SERIES = {
    # ── USD OIS / compounded SOFR ─────────────────────────────────────────
    "SOFR_ON":   "SOFR",          # overnight SOFR (Apr 2018–)        daily
    "SOFR_30D":  "SOFR30DAYAVG",  # 30-day compounded avg (Apr 2018–) daily ≈ 1M
    "SOFR_90D":  "SOFR90DAYAVG",  # 90-day compounded avg (Apr 2018–) daily ≈ 3M
    "SOFR_180D": "SOFR180DAYAVG", # 180-day compounded avg (Apr 2018–) daily ≈ 6M
    # ── USD T-bill (pre-SOFR proxy, discount basis) ───────────────────────
    "TBILL_3M":  "DTB3",          # 3M T-bill secondary market        daily
    "TBILL_6M":  "DTB6",          # 6M T-bill secondary market        daily
    "TBILL_1Y":  "DTB1YR",        # 1Y T-bill secondary market        daily
    # ── EUR OIS ───────────────────────────────────────────────────────────
    "ESTR_ON":   "ECBESTRVOLWGTTRMDMNRT",  # overnight ESTR (Oct 2019–) daily
    "ECB_DFR":   "ECBDFR",                # ECB deposit facility rate  monthly
    # ── EUR term rate (only 3M available from FRED) ───────────────────────
    "EURIBOR_3M": "IR3TIB01EZM156N",  # 3M EURIBOR, OECD series       monthly
    # ── FX ───────────────────────────────────────────────────────────────
    "EURUSD_SPOT": "DEXUSEU",     # EUR/USD spot (USD per EUR)        daily
}

# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def fetch_fred(api_key: str) -> pd.DataFrame:
    """Pull every series in FRED_SERIES; return wide DataFrame (daily index)."""
    fred = Fred(api_key=api_key)
    daily_frames = {}
    monthly_frames = {}

    for name, series_id in FRED_SERIES.items():
        log.info("FRED  %-14s  %s", name, series_id)
        try:
            s = fred.get_series(series_id, observation_start=START_DATE)
            s.name = name
            s.index = pd.to_datetime(s.index)
            # Detect frequency by looking at median gap between observations
            if len(s) > 1:
                gaps = s.index.to_series().diff().dt.days.median()
                if gaps > 20:           # monthly
                    monthly_frames[name] = s
                else:                   # daily / business-day
                    daily_frames[name] = s
            else:
                daily_frames[name] = s
        except Exception as exc:
            log.warning("FRED  %-14s  FAILED: %s", name, exc)

    # Business-day index
    bdays = pd.bdate_range(start=START_DATE, end=END_DATE)

    # Daily series: reindex directly
    df_daily = pd.DataFrame(daily_frames).reindex(bdays)

    # Monthly series: resample to daily by forward-filling within each month
    if monthly_frames:
        df_monthly = pd.DataFrame(monthly_frames)
        df_monthly = df_monthly.reindex(bdays).ffill(limit=31)
    else:
        df_monthly = pd.DataFrame(index=bdays)

    return pd.concat([df_daily, df_monthly], axis=1)


def fetch_yfinance() -> pd.Series:
    """Pull EUR/USD spot from yfinance as a cross-check."""
    log.info("yfinance  EURUSD=X")
    raw = yf.download("EURUSD=X", start=START_DATE, end=END_DATE,
                      progress=False, auto_adjust=True)
    spot = raw["Close"].squeeze()
    spot.name = "EURUSD_YF"
    spot.index = pd.to_datetime(spot.index)
    return spot


# ---------------------------------------------------------------------------
# Clean & align
# ---------------------------------------------------------------------------

def clean_and_align(fred_df: pd.DataFrame, yf_spot: pd.Series) -> pd.DataFrame:
    """
    Merge all series onto the business-day index already in fred_df.
    Forward-fill gaps up to 5 calendar days (covers weekends + bank holidays).
    Monthly series already forward-filled in fetch_fred().
    """
    bdays = fred_df.index
    yf_spot = yf_spot.reindex(bdays)
    df = fred_df.copy()
    df["EURUSD_YF"] = yf_spot

    # Forward-fill daily gaps (weekends, holidays) up to 5 days
    daily_cols = [c for c in df.columns if c not in ("EURIBOR_3M", "ECB_DFR")]
    df[daily_cols] = df[daily_cols].ffill(limit=5)

    log.info("Aligned dataset: %d rows × %d cols (%s → %s)",
             len(df), len(df.columns),
             df.index[0].date(), df.index[-1].date())
    return df


# ---------------------------------------------------------------------------
# Splice USD term rates  (SOFR compounded avg post-2018, T-bill pre-2018)
# ---------------------------------------------------------------------------

def build_usd_term_rate(df: pd.DataFrame, tenor: str) -> pd.Series:
    """
    Return a continuous daily USD term rate for the given tenor.

    3M: SOFR_90D (post-Apr 2018) spliced with TBILL_3M (pre-2018, discount → yield adj.)
    6M: SOFR_180D + TBILL_6M
    1M: SOFR_30D only (T-bills are 3M minimum)
    ON: SOFR_ON only

    T-bill rates are on a discount basis (360-day year). Convert to bond-equivalent
    yield: y = d / (1 - d * T/360)  where d = discount rate / 100, T = days.
    """
    def tbill_to_yield(discount_series: pd.Series, days: int) -> pd.Series:
        d = discount_series / 100
        return (d / (1 - d * days / 360)) * 100  # back to pct

    mapping = {
        "ON": ("SOFR_ON",  None,       0),
        "1M": ("SOFR_30D", None,       0),
        "3M": ("SOFR_90D", "TBILL_3M", 91),
        "6M": ("SOFR_180D","TBILL_6M", 182),
        "1Y": (None,       "TBILL_1Y", 365),
    }
    sofr_col, tbill_col, days = mapping[tenor]

    sofr = df[sofr_col] if sofr_col and sofr_col in df.columns else pd.Series(dtype=float, index=df.index)
    if tbill_col and tbill_col in df.columns:
        tbill = tbill_to_yield(df[tbill_col], days)
    else:
        tbill = pd.Series(dtype=float, index=df.index)

    spliced = sofr.combine_first(tbill)
    spliced.name = f"USD_{tenor}"
    return spliced


# ---------------------------------------------------------------------------
# Build EUR term rate  (ESTR overnight; EURIBOR_3M for 3M tenor)
# ---------------------------------------------------------------------------

def build_eur_term_rate(df: pd.DataFrame, tenor: str) -> pd.Series:
    """
    Return a continuous daily EUR rate.

    ON/1M/6M/1Y: ESTR_ON with ECB_DFR as pre-2019 fallback.
    3M          : EURIBOR_3M (monthly → daily via ffill already done).
    """
    estr = df["ESTR_ON"] if "ESTR_ON" in df.columns else pd.Series(dtype=float, index=df.index)
    ecb  = df["ECB_DFR"] if "ECB_DFR" in df.columns else pd.Series(dtype=float, index=df.index)
    estr_full = estr.combine_first(ecb)  # ESTR from Oct 2019, ECB DFR before

    if tenor == "3M" and "EURIBOR_3M" in df.columns:
        s = df["EURIBOR_3M"].combine_first(estr_full)
    else:
        s = estr_full

    s.name = f"EUR_{tenor}"
    return s


# ---------------------------------------------------------------------------
# Proxy basis calculation
# ---------------------------------------------------------------------------

TENOR_YEARS = {"ON": 1/360, "1M": 1/12, "3M": 0.25, "6M": 0.5, "1Y": 1.0}

def compute_proxy_basis(df: pd.DataFrame) -> pd.DataFrame:
    """
    Proxy XCCY EUR/USD basis for each tenor (in bps).

        basis(T) = EUR_rate(T) - USD_rate(T)

    Negative → USD expensive vs FX-hedged EUR (classic stress signal).
    Positive → EUR expensive vs USD.

    Coverage:
      basis_ON : ESTR vs SOFR          (Oct 2019–)
      basis_3M : EURIBOR_3M vs SOFR_90D (Apr 2018–, monthly EUR)
    """
    rows = {}
    for tenor in ("ON", "1M", "3M", "6M", "1Y"):
        usd = build_usd_term_rate(df, tenor)
        eur = build_eur_term_rate(df, tenor)
        if usd.isna().all() or eur.isna().all():
            log.warning("Skipping basis_%s — no data on one leg", tenor)
            continue
        basis_bps = (eur - usd) * 100   # pct → bps
        rows[f"basis_{tenor}"] = basis_bps
        valid = basis_bps.dropna()
        log.info("basis_%-3s  %d obs  mean=%.1f bps  min=%.1f  max=%.1f",
                 tenor, len(valid), valid.mean(), valid.min(), valid.max())

    return pd.DataFrame(rows, index=df.index)


def compute_true_basis(
    spot: pd.Series,
    forward: pd.Series,
    eur_ois: pd.Series,
    usd_ois: pd.Series,
    tenor_years: float,
) -> pd.Series:
    """
    True CIP basis from FX forward quotes (in bps).

        CIP basis = implied_USD_from_FX - actual_USD_OIS

    where implied_USD_from_FX = [(F/S) * (1 + r_EUR * T) - 1] / T

    Args:
        spot, forward : EUR/USD spot and forward rates (USD per EUR)
        eur_ois       : EUR OIS rate at tenor T (%, e.g. 3.5)
        usd_ois       : USD OIS rate at tenor T (%, e.g. 5.25)
        tenor_years   : tenor in years (e.g. 0.25 for 3M)

    Returns:
        Series of CIP basis in bps
    """
    implied_usd = ((forward / spot) * (1 + eur_ois / 100 * tenor_years) - 1) / tenor_years * 100
    return (implied_usd - usd_ois) * 100


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save(df: pd.DataFrame, name: str) -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    path = DATA_DIR / f"{name}.csv"
    df.to_csv(path)
    log.info("Saved  %s  (%d rows, %d cols)", path.name, len(df), len(df.columns))
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "FRED_API_KEY not set. Copy .env.example → .env and add your key.\n"
            "Free key: https://fred.stlouisfed.org/docs/api/api_key.html"
        )

    # 1. Fetch
    fred_df = fetch_fred(api_key)
    yf_spot = fetch_yfinance()

    # 2. Clean & align
    aligned = clean_and_align(fred_df, yf_spot)
    save(aligned, "rates_raw")

    # 3. Proxy basis
    basis = compute_proxy_basis(aligned)
    if not basis.empty:
        save(basis, "basis_proxy")
        log.info("\n--- Summary (bps) ---\n%s", basis.describe().round(1).to_string())
    else:
        log.error("Basis DataFrame is empty — no data on either leg.")

    log.info("Pipeline complete. Files in %s/", DATA_DIR)
    return aligned, basis


if __name__ == "__main__":
    main()
