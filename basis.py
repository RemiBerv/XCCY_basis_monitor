"""
XCCY Basis Monitor — Step 2: Basis Calculation

Loads raw rates from data/rates_raw.csv (produced by pipeline.py) and builds:
  1. Spliced USD and EUR term rates at each tenor
  2. Proxy XCCY basis curve (EUR rate − USD rate, in bps)
  3. Curve metrics: level (cross-tenor average) and slope (3M − 1Y)

Basis formula
─────────────
The true XCCY basis is the spread δ added to the EUR leg to make the swap
fair at inception. Under CIP it equals zero; in practice:

    basis(T) ≈ EUR_rate(T) − USD_rate(T)   [bps]

  Negative → USD expensive relative to FX-hedged EUR (stress signal)
  Positive → EUR expensive relative to USD

Tenor quality
─────────────
  3M  ★★★  EURIBOR 3M  vs  SOFR 90D / T-bill 3M  — both term rates
  ON  ★★☆  ESTR        vs  SOFR ON               — both true OIS
  1M  ★★☆  ESTR        vs  SOFR 30D              — EUR leg is overnight, not term
  6M  ★★☆  ESTR        vs  SOFR 180D / T-bill 6M — EUR leg is overnight, not term
  1Y  ★☆☆  ESTR / ECB  vs  T-bill 1Y             — EUR leg is overnight, not term

The 3M series is the most comparable to traded XCCY quotes.  The ON and 1M
series pick up policy-rate differentials as much as the basis itself.

Run:
    python basis.py
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent / "data"
RAW_FILE = DATA_DIR / "rates_raw.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Tenor definitions: (USD column, EUR column, T-bill fallback, days for BEY conv.)
# BEY = bond-equivalent yield conversion for T-bill discount rates
TENOR_DEFS = {
    "ON": dict(usd="SOFR_ON",   tbill=None,       tbill_days=0,
               eur_term=None,   eur_on="ESTR_ON"),
    "1M": dict(usd="SOFR_30D",  tbill=None,       tbill_days=0,
               eur_term=None,   eur_on="ESTR_ON"),
    "3M": dict(usd="SOFR_90D",  tbill="TBILL_3M", tbill_days=91,
               eur_term="EURIBOR_3M", eur_on="ESTR_ON"),
    "6M": dict(usd="SOFR_180D", tbill="TBILL_6M", tbill_days=182,
               eur_term=None,   eur_on="ESTR_ON"),
    "1Y": dict(usd=None,        tbill="TBILL_1Y", tbill_days=365,
               eur_term=None,   eur_on="ESTR_ON"),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def tbill_discount_to_bey(discount: pd.Series, days: int) -> pd.Series:
    """
    Convert T-bill discount rate (%) to bond-equivalent yield (%).
    BEY = d / (1 - d/100 * days/360) × 365/days × 100 ... simplified:
        d_frac = discount / 100
        bey = d_frac / (1 - d_frac * days / 360) * 100
    """
    d = discount / 100
    return (d / (1 - d * days / 360)) * 100


def build_usd_rate(df: pd.DataFrame, tenor: str) -> pd.Series:
    """
    Splice primary SOFR compounded average with T-bill fallback for pre-SOFR dates.
    Returns rate in % p.a.
    """
    cfg = TENOR_DEFS[tenor]
    primary_col = cfg["usd"]
    tbill_col   = cfg["tbill"]
    tbill_days  = cfg["tbill_days"]

    primary = (df[primary_col].copy() if primary_col and primary_col in df.columns
               else pd.Series(dtype=float, index=df.index))

    if tbill_col and tbill_col in df.columns:
        tbill_bey = tbill_discount_to_bey(df[tbill_col], tbill_days)
        spliced = primary.combine_first(tbill_bey)
    else:
        spliced = primary

    spliced.name = f"USD_{tenor}"
    return spliced


def build_eur_rate(df: pd.DataFrame, tenor: str) -> pd.Series:
    """
    Use a tenor-specific EUR term rate where available (3M: EURIBOR),
    otherwise fall back to ESTR overnight (post-Oct 2019) then ECB DFR.
    Returns rate in % p.a.
    """
    cfg = TENOR_DEFS[tenor]
    eur_term_col = cfg["eur_term"]

    # Overnight chain: ESTR → ECB DFR (pre-ESTR)
    estr = df["ESTR_ON"] if "ESTR_ON" in df.columns else pd.Series(dtype=float, index=df.index)
    ecb  = df["ECB_DFR"] if "ECB_DFR" in df.columns else pd.Series(dtype=float, index=df.index)
    eur_on = estr.combine_first(ecb)

    if eur_term_col and eur_term_col in df.columns:
        # Fill any remaining gaps in the term rate with the overnight chain
        eur = df[eur_term_col].combine_first(eur_on)
    else:
        eur = eur_on

    eur.name = f"EUR_{tenor}"
    return eur


# ---------------------------------------------------------------------------
# Basis curve
# ---------------------------------------------------------------------------

def compute_basis_curve(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute basis(T) = EUR_rate(T) − USD_rate(T) in bps for every tenor.
    Also builds spliced rate columns for inspection.
    Returns a DataFrame with:
      USD_{T}, EUR_{T}, basis_{T}  for each tenor T
      basis_level  — equal-weighted average across tenors with data
      basis_slope  — basis_3M − basis_1Y  (steepens negative during stress)
    """
    rate_cols = {}
    basis_cols = {}

    for tenor in TENOR_DEFS:
        usd = build_usd_rate(df, tenor)
        eur = build_eur_rate(df, tenor)

        rate_cols[f"USD_{tenor}"] = usd
        rate_cols[f"EUR_{tenor}"] = eur

        basis_bps = (eur - usd) * 100   # % → bps
        basis_cols[f"basis_{tenor}"] = basis_bps

        valid = basis_bps.dropna()
        if len(valid):
            log.info("%-10s  %4d obs  mean=%7.1f bps  min=%7.1f  max=%6.1f  "
                     "first=%s",
                     f"basis_{tenor}", len(valid),
                     valid.mean(), valid.min(), valid.max(),
                     valid.index[0].date())

    out = pd.DataFrame({**rate_cols, **basis_cols}, index=df.index)

    # Curve level: equal-weight average of all basis columns that have data
    basis_cols_list = [c for c in basis_cols if not out[c].isna().all()]
    out["basis_level"] = out[basis_cols_list].mean(axis=1)

    # Curve slope: short-end (3M) minus long-end (1Y), sign convention:
    #   more negative during stress as 3M front-end absorbs the pressure
    if "basis_3M" in out.columns and "basis_1Y" in out.columns:
        out["basis_slope"] = out["basis_3M"] - out["basis_1Y"]
        log.info("%-10s  slope mean=%.1f bps  (negative = inverted / stressed curve)",
                 "slope_3M-1Y", out["basis_slope"].dropna().mean())

    return out


# ---------------------------------------------------------------------------
# Diagnostics: snapshot at key dates
# ---------------------------------------------------------------------------

SNAPSHOTS = {
    "Pre-GFC normal (2010-06-01)":   "2010-06-01",
    "EUR sovereign crisis (2012-07-01)": "2012-07-01",
    "COVID shock (2020-03-20)":      "2020-03-20",
    "Ukraine / hike cycle (2022-03-01)": "2022-03-01",
    "SVB collapse (2023-03-17)":     "2023-03-17",
    "Today":                          None,          # filled dynamically
}

def print_snapshots(curve: pd.DataFrame) -> None:
    basis_cols = [c for c in curve.columns if c.startswith("basis_")]
    log.info("\n--- Basis curve snapshots (bps) ---")
    header = f"{'Date':<35}" + "".join(f"{c:>12}" for c in basis_cols)
    log.info(header)
    for label, date in SNAPSHOTS.items():
        if date is None:
            row = curve[basis_cols].dropna(how="all").iloc[-1]
            label = f"Latest ({row.name.date()})"
        else:
            ts = pd.Timestamp(date)
            # Find nearest available date
            idx = curve.index.get_indexer([ts], method="nearest")[0]
            row = curve[basis_cols].iloc[idx]
            label = f"{label} ({curve.index[idx].date()})"
        vals = "".join(f"{v:>12.1f}" if pd.notna(v) else f"{'—':>12}" for v in row)
        log.info(f"{label:<35}{vals}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> pd.DataFrame:
    if not RAW_FILE.exists():
        raise FileNotFoundError(
            f"{RAW_FILE} not found. Run pipeline.py first."
        )

    log.info("Loading %s", RAW_FILE.name)
    df = pd.read_csv(RAW_FILE, index_col=0, parse_dates=True)
    log.info("Loaded %d rows × %d cols", len(df), len(df.columns))

    # Build basis curve
    curve = compute_basis_curve(df)

    # Print snapshots
    print_snapshots(curve)

    # Save
    out_path = DATA_DIR / "basis_curve.csv"
    curve.to_csv(out_path)
    log.info("Saved %s (%d rows, %d cols)", out_path.name, len(curve), len(curve.columns))

    return curve


if __name__ == "__main__":
    main()
