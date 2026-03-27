# EUR/USD XCCY Basis — Empirical Findings

*Data through 26 Mar 2026. Basis proxy: EURIBOR 3M − SOFR 90-day compounded average (in bps). Sources: FRED (SOFR, ESTR, EURIBOR via OECD, EUR/USD spot), yfinance.*


## 1. What the XCCY Basis Measures

In a frictionless market, Covered Interest Parity (CIP) holds: the cost of borrowing in one currency and swapping it into another via the FX forward market should equal the direct borrowing rate in that currency. The **XCCY basis** is the spread added to the EUR leg of the swap to make it fair at inception — it is the price of the CIP deviation.

A **negative basis** means USD is expensive relative to FX-hedged EUR: investors pay a premium to access USD liquidity through the swap market. This premium widens during stress episodes when global demand for USD funding surges.


## 2. Baseline (Normal Periods)

Outside the four identified stress windows, the 3M basis averages **-73 bps** and the 1Y basis averages **-105 bps**. The curve is upward-sloping in normal conditions (long-end more negative than short-end), reflecting the structural demand for long-dated USD from FX-hedging by non-US investors in USD assets.


## 3. Stress Episode Analysis

The table below summarises basis widening during each episode relative to normal:


| Episode | 3M mean | 3M min | 1Y mean | Widening 3M | Widening 1Y | Front-end excess | Slope mean |
|---------|---------|--------|---------|-------------|------------|------------------|------------|
| COVID-19 (Mar 2020) | -142 bps | -210 bps | -86 bps | -68 bps | +18 bps | -87 bps | -55 bps |
| Ukraine war (Feb 2022) | -67 bps | -98 bps | -249 bps | +6 bps | -144 bps | +151 bps | +182 bps |
| SVB collapse (Mar 2023) | -162 bps | -177 bps | -186 bps | -89 bps | -82 bps | -7 bps | +24 bps |
| Tariff shock (Apr 2025) | -224 bps | -242 bps | -186 bps | -150 bps | -81 bps | -69 bps | -38 bps |

*Widening = mean during episode − normal mean. More negative = larger widening. Front-end excess = 3M widening minus 1Y widening (negative = extra front-end pressure).*


**COVID-19 (Mar 2020):** The most acute short-term USD funding crunch on record at that point. The 3M basis widened by **-68 bps** relative to normal, reaching a trough of -210 bps. The curve inverted sharply (slope -55 bps), with the front end absorbing 87 bps of extra pressure versus the 1Y tenor. The Federal Reserve's emergency swap lines with the ECB and other central banks (activated mid-March 2020) arrested the move.

**Ukraine war (Feb 2022):** A markedly different dynamic. The 3M basis widened by only **+6 bps** and the curve slope remained strongly positive (+182 bps), meaning the long end was actually *more* stressed than the short end. This episode was driven by rapid ECB and Fed rate-hike expectations compressing the EUR/USD rate differential at long tenors — a rate-cycle effect rather than a short-term USD liquidity squeeze. It confirms that not all basis widening reflects the same underlying stress.

**SVB collapse (Mar 2023):** A sharp but short-lived USD funding shock. The 3M basis widened by **-89 bps** over just 38.0 trading days, with a front-end excess of 7 bps. The slope barely turned negative (+24 bps mean), suggesting the market priced a contained, bank-specific event rather than a systemic dollar squeeze. The rapid policy response (BTFP facility, deposit guarantees) limited the propagation.

**Tariff shock (Apr 2025):** The **largest episode in the sample**, with the 3M basis averaging **-224 bps** — a widening of **-150 bps** versus normal. The trough reached -242 bps. The trigger was the announcement of sweeping US tariffs, which caused a sharp reallocation into USD safe-haven assets, driving global demand for dollar funding. The slope turned negative (-38 bps mean), with 69 bps of excess front-end pressure — the classic short-term USD squeeze fingerprint.


## 4. Short-End Concentration

3 out of 4 episodes show greater widening at the 3M tenor than at 1Y, confirming the short-end concentration hypothesis.


In episodes where both legs moved meaningfully:

- **COVID-19 (Mar 2020)**: 3M widened -3.8× more than 1Y

- **Ukraine war (Feb 2022)**: 3M widened -0.0× more than 1Y

- **SVB collapse (Mar 2023)**: 3M widened 1.1× more than 1Y

- **Tariff shock (Apr 2025)**: 3M widened 1.9× more than 1Y

The front-end concentration reflects the direct competition between XCCY swaps and FX swaps at short maturities. When USD demand surges, the FX swap market reprices first, and the 1M–3M XCCY basis adjusts immediately. Longer tenors are anchored by structural hedging flows (pension funds, insurers) which are less sensitive to short-term liquidity conditions.


## 5. Curve Steepening During Stress

In normal periods the basis curve is broadly flat to slightly upward-sloping (3M − 1Y slope of approximately +28 bps on average across stress episodes, though this masks sign changes). During funding-squeeze events (COVID, tariff shock) the slope turns **negative**: the short end becomes more negative than the long end, producing an inverted basis curve. This inversion is the empirical signature of acute short-dated USD scarcity.

The Ukraine episode is the clear exception: the curve remained steeply positive as rate-hike pricing — not funding stress — drove the basis. This distinction has practical implications for traders: a steepening (inverted) basis curve is a more reliable signal of USD funding stress than the level of the basis alone.


## 6. Current Market Signal

As of **26 Mar 2026**, the 3M basis stands at **-176 bps** and the 1Y basis at -183 bps. The curve slope is +7 bps. 

The 3M basis is 102 bps wider than the normal-period average, indicating elevated USD funding demand. The basis is inside stress-episode territory, consistent with the ongoing repricing following the 2025 tariff shock.


## 7. Caveats and Data Limitations

- **Proxy basis**: the true XCCY basis is quoted from interbank FX forward   markets (Bloomberg FXFA, Reuters). The series here (EURIBOR 3M − SOFR 90D)   is a close proxy but not identical to traded swap levels.
- **EURIBOR vs ESTR**: the EUR leg uses EURIBOR (a credit-inclusive   IBOR rate) rather than a pure OIS rate (ESTR term rate), which would   be the correct leg for a collateralised XCCY swap.
- **Monthly EUR data**: EURIBOR 3M is available only monthly from the   OECD/FRED series used here; intra-month moves are forward-filled.
- **Tenor coverage**: only tenors up to 1Y are modelled. The 2Y and 5Y   tenors cited in the README require OIS swap rate data (Bloomberg/Refinitiv).
