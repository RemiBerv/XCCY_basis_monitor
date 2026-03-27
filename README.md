# XCCY Basis Monitor

> **IMPORTANT — Data Limitation**
>
> The basis levels computed in this project (EURIBOR 3M minus SOFR 90D) represent the **EUR/USD interest rate differential**, not the true traded XCCY basis. The true basis requires FX forward quotes (Bloomberg FXFA or equivalent) and is significantly smaller in absolute terms — the EUR/USD 3M basis is currently around **−5 bps** in the market vs **−170 bps** computed here. This project is a **directional indicator of USD funding stress**, not a replication of traded XCCY swap spreads.

## What is the XCCY Basis?

A Cross Currency Basis Swap (XCCY) is a float-float swap between two currencies. One party pays a floating rate in currency A (e.g. EURIBOR 3M) and receives a floating rate in currency B (e.g. SOFR 3M), with an exchange of notionals at inception and maturity.

In a frictionless world, Covered Interest Parity (CIP) holds: the interest rate differential between two currencies should exactly match the cost of hedging FX risk via the forward market. In practice, CIP breaks down. The **basis** is the spread applied to the non-USD leg to make the swap value zero at inception. It measures the gap between:

- the **implied interest rate** created by the FX forward market
- the **actual interest rate** in that currency (OIS rate)

When demand for USD rises (stress episodes, monetary policy divergence, regulatory pressure), the basis on the EUR leg becomes more negative: investors pay a premium to access USD liquidity via the swap market.

## Key Market Dynamics

Three empirical regularities drive activity on a XCCY desk:

1. **Basis goes more negative during stress** — USD demand spikes push the basis down (COVID-19, GFC, SVB collapse, tariff shocks)
2. **Effect concentrates at the short end** — front-end tenors (1M, 3M) absorb most of the pressure since XCCY competes directly with FX swaps at short maturities
3. **Curve steepens during stress** — because the short end moves more aggressively than the long end, the basis curve steepens (short-end more negative than long-end)

## What This Project Builds

A Python tool that tracks EUR/USD interest rate differentials as a **proxy** for USD funding pressure:

- Computes the EUR/USD rate differential from publicly available market data (FRED, yfinance)
- Reconstructs a proxy basis curve across multiple tenors (ON, 1M, 3M, 6M, 1Y)
- Visualises the historical evolution and stress episodes
- Identifies and annotates stress windows (COVID, Ukraine, SVB, tariff shock)
- Demonstrates the short-end concentration and curve steepening dynamic empirically

### What it does correctly

The stress episode analysis and curve shape dynamics (slope, front-end concentration) remain valid as **directional observations**. The project correctly identifies *when* and *where* USD funding pressure concentrates. The absolute levels are not comparable to traded XCCY quotes.

### What it does not do

The true XCCY basis is the CIP deviation stripped from FX forward quotes — it requires interbank FX forward data (e.g. Bloomberg FXFA, Reuters, or bank contributor feeds), none of which are freely available. According to market practitioners, the EUR/USD 3M traded basis is currently around −5.5 bps and the 10Y around −9.625 bps. The −170 bps computed here reflects the policy rate differential between the ECB and the Fed, which is a separate (though related) concept.

## Project Plan

### Step 1 — Data Pipeline
- Pull SOFR (USD OIS) and ESTR (EUR OIS) from FRED across tenors
- Pull EUR/USD spot and forward points from yfinance
- Clean and align time series

### Step 2 — Basis Calculation
- Reconstruct implied USD rate from FX forward: `F/S = (1 + r_USD * T) / (1 + r_EUR * T)`
- Compute basis = implied rate - actual SOFR rate, expressed in bps
- Repeat across tenors to build the basis curve

### Step 3 — Stress Episode Analysis
- Define stress windows: COVID (Mar 2020), Ukraine (Feb 2022), SVB (Mar 2023), tariff shock (2025)
- Compute average basis level and curve slope (short-end minus long-end) inside vs outside stress windows

### Step 4 — Visualisation
- Plot 1: Historical basis at 3M and 5Y tenors with stress periods shaded
- Plot 2: Basis curve snapshot at selected stress peaks vs normal periods
- Plot 3: Slope of the basis curve over time (steepening indicator)

### Step 5 — Interpretation
- Quantify the average basis widening during each stress episode
- Confirm the short-end concentration empirically
- Summarise findings in a short commentary
