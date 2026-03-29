"""
EUR/USD FX Forward Points — Bloomberg Data Fetcher

REQUIREMENTS
────────────
1. Bloomberg Terminal must be running on this machine (active session).
2. blpapi Python SDK must be installed:

     # Official Bloomberg Python API — requires a Bloomberg account to download
     # Download from: https://www.bloomberg.com/professional/support/api-library/
     # Then install the .whl file for your Python version, e.g.:
     pip install blpapi-3.x.x-cpXX-win_amd64.whl

   Alternatively via pip (requires Bloomberg network access):
     pip install --index-url=https://blpapi.bloomberg.com blpapi

3. Permissions needed on your Bloomberg account:
     - B-PIPE or Desktop API access (standard Terminal subscription includes this)
     - FX data entitlement (Curncy asset class) — included in standard FX packages
     - Historical data access (HAPI) — included in standard Terminal

TICKERS
───────
   EURUSD BGN Curncy    — EUR/USD spot mid, BGN composite source
   EURUSD1M BGN Curncy  — EUR/USD 1M forward points (in pips, e.g. 25.5 = 0.00255)
   EURUSD3M BGN Curncy  — EUR/USD 3M forward points
   EURUSD6M BGN Curncy  — EUR/USD 6M forward points
   EURUSD1Y BGN Curncy  — EUR/USD 1Y forward points

   Forward rate(T) = Spot + ForwardPoints(T) / 10000
   (Bloomberg quotes forward points in units of 1/10000 of the spot rate)

Run:
   python fetch_bloomberg.py [--start 2010-01-01] [--end today]
   → data/bloomberg_forwards.csv
"""

import argparse
import logging
from datetime import date
from pathlib import Path

import pandas as pd

# blpapi is only importable when a Bloomberg Terminal is active
try:
    import blpapi
    BLPAPI_AVAILABLE = True
except ImportError:
    BLPAPI_AVAILABLE = False

DATA_DIR = Path(__file__).parent / "data"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bloomberg tickers
# ---------------------------------------------------------------------------

TICKERS = {
    "spot":   "EURUSD BGN Curncy",
    "fwd_1M": "EURUSD1M BGN Curncy",
    "fwd_3M": "EURUSD3M BGN Curncy",
    "fwd_6M": "EURUSD6M BGN Curncy",
    "fwd_1Y": "EURUSD1Y BGN Curncy",
}

FIELD = "PX_LAST"

# Tenor in years (act/360 money market) — used in CIP formula below
TENOR_YEARS = {
    "fwd_1M": 30  / 360,
    "fwd_3M": 91  / 360,
    "fwd_6M": 182 / 360,
    "fwd_1Y": 365 / 360,
}

# ---------------------------------------------------------------------------
# Bloomberg session helpers
# ---------------------------------------------------------------------------

def _start_session(host: str = "localhost", port: int = 8194) -> "blpapi.Session":
    """Open a Bloomberg API session on the local Terminal."""
    options = blpapi.SessionOptions()
    options.setServerHost(host)
    options.setServerPort(port)
    session = blpapi.Session(options)
    if not session.start():
        raise RuntimeError(
            "Bloomberg session failed to start. "
            "Make sure the Terminal is open and logged in."
        )
    if not session.openService("//blp/refdata"):
        raise RuntimeError("Could not open Bloomberg refdata service.")
    return session


def _send_historical_request(session: "blpapi.Session",
                              tickers: list[str],
                              field: str,
                              start: str,
                              end: str) -> "blpapi.Event":
    """Send a HistoricalDataRequest and return the response events."""
    refdata = session.getService("//blp/refdata")
    request = refdata.createRequest("HistoricalDataRequest")

    for ticker in tickers:
        request.getElement("securities").appendValue(ticker)
    request.getElement("fields").appendValue(field)
    request.set("startDate", start)
    request.set("endDate", end)
    request.set("periodicitySelection", "DAILY")
    request.set("nonTradingDayFillOption", "PREVIOUS_VALUE")
    request.set("nonTradingDayFillMethod", "NIL_VALUE")

    session.sendRequest(request)


def _parse_response(session: "blpapi.Session") -> dict[str, pd.Series]:
    """
    Collect response events and parse into {column_name: pd.Series} keyed
    by the column names in TICKERS (spot, fwd_1M, etc.).
    """
    # Reverse map: Bloomberg ticker → our column name
    reverse = {v: k for k, v in TICKERS.items()}
    results = {}

    while True:
        event = session.nextEvent(500)
        for msg in event:
            if msg.hasElement("securityData"):
                sec_data  = msg.getElement("securityData")
                ticker    = sec_data.getElementAsString("security")
                col       = reverse.get(ticker, ticker)
                field_data = sec_data.getElement("fieldData")

                dates  = []
                values = []
                for i in range(field_data.numValues()):
                    point = field_data.getValue(i)
                    dates.append(pd.Timestamp(point.getElementAsDatetime("date")))
                    values.append(point.getElementAsFloat(FIELD))

                results[col] = pd.Series(values, index=dates, name=col)

        if event.eventType() == blpapi.Event.RESPONSE:
            break

    return results


# ---------------------------------------------------------------------------
# Main fetch function
# ---------------------------------------------------------------------------

def fetch(start: str, end: str) -> pd.DataFrame:
    """
    Fetch EUR/USD spot and forward points from Bloomberg.
    Returns a DataFrame with columns: date, spot, fwd_1M, fwd_3M, fwd_6M, fwd_1Y.
    Forward points are stored raw (pips); forward rates are NOT pre-computed here
    so that the raw Bloomberg data is preserved exactly.
    """
    if not BLPAPI_AVAILABLE:
        raise ImportError(
            "blpapi is not installed. See the docstring at the top of this file "
            "for installation instructions."
        )

    log.info("Connecting to Bloomberg ...")
    session = _start_session()

    try:
        tickers = list(TICKERS.values())
        log.info("Requesting %d tickers: %s → %s", len(tickers), start, end)
        _send_historical_request(session, tickers, FIELD, start, end)
        raw = _parse_response(session)
    finally:
        session.stop()
        log.info("Bloomberg session closed.")

    # Align to a common business-day index
    df = pd.DataFrame(raw)
    df.index.name = "date"
    df = df.sort_index()

    log.info("Fetched %d rows × %d cols  (%s → %s)",
             len(df), len(df.columns),
             df.index[0].date(), df.index[-1].date())
    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(start: str, end: str):
    DATA_DIR.mkdir(exist_ok=True)

    df = fetch(start, end)

    out_path = DATA_DIR / "bloomberg_forwards.csv"
    df.to_csv(out_path)
    log.info("Saved %s", out_path.name)
    print(df.tail(10).round(5).to_string())


# ---------------------------------------------------------------------------
# TRUE CIP BASIS — how to use this data once available
# ---------------------------------------------------------------------------
#
# Once bloomberg_forwards.csv is produced, the true CIP basis is:
#
#   import pandas as pd
#   import numpy as np
#
#   df   = pd.read_csv("data/bloomberg_forwards.csv", index_col=0, parse_dates=True)
#   sofr = pd.read_csv("data/rates_raw.csv", index_col=0, parse_dates=True)
#
#   TENORS = {"fwd_3M": 91/360, "fwd_6M": 182/360, "fwd_1Y": 365/360}
#   SOFR_COL = {"fwd_3M": "SOFR_90D", "fwd_6M": "SOFR_180D", "fwd_1Y": "TBILL_1Y"}
#   ESTR_COL = "ESTR_ON"
#
#   for col, T in TENORS.items():
#       # Forward rate from points: F = S + points/10000
#       F      = df["spot"] + df[col] / 10_000
#       S      = df["spot"]
#       r_USD  = sofr[SOFR_COL[col]] / 100          # % → decimal
#       r_EUR  = sofr[ESTR_COL] / 100
#
#       # True CIP basis (bps)
#       basis  = ((1 + r_USD * T) * (S / F) - 1) / T - r_EUR
#       df[f"cip_basis_{col[4:]}"] = basis * 10_000  # decimal → bps
#
#   # This will give ~-5 bps at 3M (matching Michael's screen)
#   # vs ~-170 bps from the rate differential proxy
#
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch EUR/USD FX forward points from Bloomberg"
    )
    parser.add_argument("--start", default="2010-01-01",
                        help="Start date YYYY-MM-DD (default 2010-01-01)")
    parser.add_argument("--end",   default=date.today().strftime("%Y-%m-%d"),
                        help="End date YYYY-MM-DD (default today)")
    args = parser.parse_args()
    main(args.start, args.end)
