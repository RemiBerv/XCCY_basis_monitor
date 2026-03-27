"""
XCCY Basis Monitor — Steps 3 & 4: Stress Analysis + Visualisation

Loads data/basis_curve.csv and produces three publication-quality charts:

  Plot 1 — Historical basis (3M and 1Y) with stress windows shaded
  Plot 2 — Basis curve snapshots: stress peaks vs normal periods
  Plot 3 — Curve slope (basis_3M − basis_1Y) over time

Stress windows
──────────────
  COVID-19     : 2020-02-20 → 2020-05-29
  Ukraine war  : 2022-02-24 → 2022-06-30
  SVB collapse : 2023-03-08 → 2023-04-28
  Tariff shock : 2025-04-01 → 2025-06-30

Run:
  python visualise.py
  → saves charts/ *.png  (300 dpi)
"""

import logging
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DATA_DIR   = Path(__file__).parent / "data"
CHARTS_DIR = Path(__file__).parent / "charts"
CURVE_FILE = DATA_DIR / "basis_curve.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Stress episodes: label → (start, end, peak-date for snapshot)
STRESS = {
    "COVID-19\n(Mar 2020)": {
        "start": "2020-02-20", "end": "2020-05-29",
        "peak":  "2020-03-20",
        "color": "#d62728",
    },
    "Ukraine\n(Feb 2022)": {
        "start": "2022-02-24", "end": "2022-06-30",
        "peak":  "2022-03-01",
        "color": "#ff7f0e",
    },
    "SVB\n(Mar 2023)": {
        "start": "2023-03-08", "end": "2023-04-28",
        "peak":  "2023-03-17",
        "color": "#9467bd",
    },
    "Tariff shock\n(Apr 2025)": {
        "start": "2025-04-01", "end": "2025-06-30",
        "peak":  "2025-04-07",
        "color": "#8c564b",
    },
}

# Normal reference dates for the snapshot plot
NORMAL_DATES = {
    "Normal (Jan 2020)": "2020-01-15",
    "Normal (Jan 2017)": "2017-01-15",
}

TENOR_ORDER  = ["ON", "1M", "3M", "6M", "1Y"]
TENOR_LABELS = {"ON": "O/N", "1M": "1M", "3M": "3M", "6M": "6M", "1Y": "1Y"}
TENOR_X      = [0, 1, 3, 6, 12]   # approximate months on x-axis

# House style
STYLE = {
    "fig_facecolor":  "#0d1117",
    "ax_facecolor":   "#161b22",
    "grid_color":     "#30363d",
    "text_color":     "#e6edf3",
    "zero_color":     "#58a6ff",
    "stress_alpha":   0.18,
    "line_3M":        "#58a6ff",   # blue
    "line_1Y":        "#3fb950",   # green
    "line_slope":     "#f78166",   # red-orange
    "line_normal":    "#8b949e",   # grey
}

plt.rcParams.update({
    "figure.facecolor":  STYLE["fig_facecolor"],
    "axes.facecolor":    STYLE["ax_facecolor"],
    "axes.edgecolor":    STYLE["grid_color"],
    "axes.labelcolor":   STYLE["text_color"],
    "xtick.color":       STYLE["text_color"],
    "ytick.color":       STYLE["text_color"],
    "text.color":        STYLE["text_color"],
    "grid.color":        STYLE["grid_color"],
    "grid.linewidth":    0.5,
    "legend.facecolor":  "#21262d",
    "legend.edgecolor":  STYLE["grid_color"],
    "font.family":       "sans-serif",
    "font.size":         10,
})

# ---------------------------------------------------------------------------
# Stress statistics
# ---------------------------------------------------------------------------

def compute_stress_stats(curve: pd.DataFrame) -> pd.DataFrame:
    """
    For each stress window compute mean basis_3M and mean slope inside vs outside.
    """
    rows = []
    in_stress = pd.Series(False, index=curve.index)

    for label, cfg in STRESS.items():
        mask = (curve.index >= cfg["start"]) & (curve.index <= cfg["end"])
        in_stress |= mask
        w = curve.loc[mask, ["basis_3M", "basis_slope"]].dropna()
        if w.empty:
            continue
        rows.append({
            "episode":        label.replace("\n", " "),
            "n_days":         len(w),
            "basis_3M_mean":  w["basis_3M"].mean(),
            "basis_3M_min":   w["basis_3M"].min(),
            "slope_mean":     w["basis_slope"].mean(),
            "slope_min":      w["basis_slope"].min(),
        })

    outside = curve.loc[~in_stress, ["basis_3M", "basis_slope"]].dropna()
    rows.append({
        "episode":        "Normal (outside stress)",
        "n_days":         len(outside),
        "basis_3M_mean":  outside["basis_3M"].mean(),
        "basis_3M_min":   outside["basis_3M"].min(),
        "slope_mean":     outside["basis_slope"].mean(),
        "slope_min":      outside["basis_slope"].min(),
    })

    stats = pd.DataFrame(rows).set_index("episode")
    return stats


def shade_stress(ax: plt.Axes, curve: pd.DataFrame) -> None:
    """Add shaded stress bands and top-edge labels to an axes."""
    ylim = ax.get_ylim()
    for label, cfg in STRESS.items():
        s = pd.Timestamp(cfg["start"])
        e = pd.Timestamp(cfg["end"])
        if e < curve.index[0] or s > curve.index[-1]:
            continue
        ax.axvspan(s, e, alpha=STYLE["stress_alpha"],
                   color=cfg["color"], zorder=0, linewidth=0)
        mid = s + (e - s) / 2
        ax.text(mid, ylim[1] * 0.97, label.split("\n")[0],
                ha="center", va="top", fontsize=7.5,
                color=cfg["color"], alpha=0.9)
    ax.set_ylim(ylim)


# ---------------------------------------------------------------------------
# Plot 1: Historical basis (3M and 1Y)
# ---------------------------------------------------------------------------

def plot_historical(curve: pd.DataFrame) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(13, 5))

    b3m = curve["basis_3M"].dropna()
    b1y = curve["basis_1Y"].dropna()

    ax.plot(b3m.index, b3m.values, lw=1.4, color=STYLE["line_3M"],
            label="3M basis (EURIBOR − SOFR 90D / T-bill)", zorder=3)
    ax.plot(b1y.index, b1y.values, lw=1.1, color=STYLE["line_1Y"],
            alpha=0.85, label="1Y basis (ESTR − T-bill 1Y)", zorder=2)

    ax.axhline(0, color=STYLE["zero_color"], lw=0.8, ls="--",
               alpha=0.6, zorder=1)

    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%+.0f"))
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.grid(True, axis="y", zorder=0)

    shade_stress(ax, curve)

    ax.set_title("EUR/USD XCCY Basis — Historical (3M and 1Y)",
                 fontsize=13, pad=12, fontweight="bold")
    ax.set_ylabel("Basis (bps)", fontsize=10)
    ax.legend(loc="lower left", fontsize=9)

    ax.annotate("Negative = USD expensive\nvs FX-hedged EUR",
                xy=(0.01, 0.04), xycoords="axes fraction",
                fontsize=8, color=STYLE["text_color"], alpha=0.65)

    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Plot 2: Basis curve snapshots
# ---------------------------------------------------------------------------

def plot_curve_snapshots(curve: pd.DataFrame) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(9, 5))

    basis_cols = [f"basis_{t}" for t in TENOR_ORDER
                  if f"basis_{t}" in curve.columns]
    x = TENOR_X[:len(basis_cols)]

    # Normal periods — grey
    for label, date in NORMAL_DATES.items():
        ts = pd.Timestamp(date)
        idx = curve.index.get_indexer([ts], method="nearest")[0]
        row = curve[basis_cols].iloc[idx]
        ax.plot(x, row.values, lw=1.5, ls="--", color=STYLE["line_normal"],
                alpha=0.6, marker="o", ms=5, label=label, zorder=2)

    # Stress peaks
    cmap = plt.cm.tab10
    for i, (label, cfg) in enumerate(STRESS.items()):
        # Find date of most negative basis_3M within window
        mask = (curve.index >= cfg["start"]) & (curve.index <= cfg["end"])
        window = curve.loc[mask, basis_cols].dropna(how="all")
        if window.empty:
            continue
        peak_idx = window["basis_3M"].idxmin() if "basis_3M" in window.columns else window.index[0]
        row = window.loc[peak_idx, basis_cols]
        lbl = label.replace("\n", " ") + f"\n({pd.Timestamp(peak_idx).strftime('%b %Y')})"
        ax.plot(x, row.values, lw=2, color=cfg["color"],
                marker="o", ms=6, label=lbl, zorder=3)

    ax.axhline(0, color=STYLE["zero_color"], lw=0.8, ls="--", alpha=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels([TENOR_LABELS[t] for t in TENOR_ORDER[:len(x)]], fontsize=10)
    ax.set_xlabel("Tenor", fontsize=10)
    ax.set_ylabel("Basis (bps)", fontsize=10)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%+.0f"))
    ax.grid(True, zorder=0)

    ax.set_title("EUR/USD Basis Curve — Stress Peaks vs Normal",
                 fontsize=13, pad=12, fontweight="bold")
    ax.legend(loc="lower right", fontsize=8.5)

    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Plot 3: Basis curve slope over time
# ---------------------------------------------------------------------------

def plot_slope(curve: pd.DataFrame) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(13, 4))

    slope = curve["basis_slope"].dropna()
    ax.plot(slope.index, slope.values, lw=1.3, color=STYLE["line_slope"],
            label="Slope = basis_3M − basis_1Y", zorder=3)
    ax.fill_between(slope.index, slope.values, 0,
                    where=(slope.values < 0),
                    color=STYLE["line_slope"], alpha=0.15, zorder=2)
    ax.axhline(0, color=STYLE["zero_color"], lw=0.8, ls="--",
               alpha=0.6, zorder=1)

    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%+.0f"))
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.grid(True, axis="y", zorder=0)

    shade_stress(ax, curve)

    ax.set_title("EUR/USD Basis Curve Slope (3M − 1Y) — Steepening Indicator",
                 fontsize=13, pad=12, fontweight="bold")
    ax.set_ylabel("Slope (bps)", fontsize=10)
    ax.legend(loc="upper left", fontsize=9)

    ax.annotate(
        "Negative slope = curve inverted\n(front-end more negative than long-end)\n→ USD funding stress concentrated at short tenors",
        xy=(0.01, 0.07), xycoords="axes fraction",
        fontsize=8, color=STYLE["text_color"], alpha=0.65,
    )

    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not CURVE_FILE.exists():
        raise FileNotFoundError(
            f"{CURVE_FILE} not found. Run basis.py first."
        )

    log.info("Loading %s", CURVE_FILE.name)
    curve = pd.read_csv(CURVE_FILE, index_col=0, parse_dates=True)

    CHARTS_DIR.mkdir(exist_ok=True)

    # --- Stress statistics ---
    stats = compute_stress_stats(curve)
    log.info("\n--- Stress Episode Statistics ---\n%s",
             stats.round(1).to_string())

    stats_path = DATA_DIR / "stress_stats.csv"
    stats.to_csv(stats_path)
    log.info("Saved %s", stats_path.name)

    # --- Plot 1 ---
    fig1 = plot_historical(curve)
    p1 = CHARTS_DIR / "01_historical_basis.png"
    fig1.savefig(p1, dpi=300, bbox_inches="tight",
                 facecolor=STYLE["fig_facecolor"])
    log.info("Saved %s", p1.name)

    # --- Plot 2 ---
    fig2 = plot_curve_snapshots(curve)
    p2 = CHARTS_DIR / "02_curve_snapshots.png"
    fig2.savefig(p2, dpi=300, bbox_inches="tight",
                 facecolor=STYLE["fig_facecolor"])
    log.info("Saved %s", p2.name)

    # --- Plot 3 ---
    fig3 = plot_slope(curve)
    p3 = CHARTS_DIR / "03_slope.png"
    fig3.savefig(p3, dpi=300, bbox_inches="tight",
                 facecolor=STYLE["fig_facecolor"])
    log.info("Saved %s", p3.name)

    plt.show()
    log.info("Done.")


if __name__ == "__main__":
    main()
