#!/usr/bin/env python3
"""Render docs/evidence/hpa-timeseries.csv as a committed SVG chart.

    python3 scripts/plot_hpa.py

Produces docs/evidence/hpa-replicas-vs-load.svg — the "replicas against offered load over time"
deliverable from §3.3.

Design notes, because the chart makes an argument and the form has to support it:

* THREE STACKED PANELS SHARING ONE X-AXIS, not one chart with two y-scales. Offered load (0-60 VUs),
  CPU utilisation (0-190%) and replica count (0-10) are measures of different scale; putting two of
  them on one pair of axes would let the reader infer a relationship from whatever scaling was
  chosen. Stacked panels on a common time axis show the causal chain honestly:
  load rises -> CPU rises -> replicas rise, and the horizontal distance between those events IS the
  lag being reported.
* Replicas are drawn as a STEP line. The replica count is a discrete integer that changes at an
  instant; interpolating it diagonally would draw 3.5 pods, which never existed.
* The lag is annotated directly on the chart rather than left for the reader to measure.
* No dependency on matplotlib: this writes SVG directly, so it runs anywhere the repo is checked out.

Palette: validated categorical slots 1-3 from the project's chart palette
(blue #2a78d6, orange #eb6834, aqua #1baf7a) — checked for CVD separation and lightness before use.
Each panel carries one series and a title that names it, so identity never depends on colour alone.
"""

from __future__ import annotations

import csv
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "docs" / "evidence" / "hpa-timeseries.csv"
OUT_PATH = ROOT / "docs" / "evidence" / "hpa-replicas-vs-load.svg"

# --- canvas -------------------------------------------------------------------
W = 940
PAD_L, PAD_R, PAD_T = 68, 132, 92
PANEL_H = 132
PANEL_GAP = 58
PAD_B = 82
H = PAD_T + 3 * PANEL_H + 2 * PANEL_GAP + PAD_B
PLOT_W = W - PAD_L - PAD_R

SURFACE = "#fcfcfb"
INK = "#1a1a19"
INK_2 = "#55534e"
INK_MUTED = "#84817a"
GRID = "#e8e6e1"

BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
TARGET = "#c98500"

FONT = (
    "ui-sans-serif, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
)


def load_rows() -> list[dict]:
    if not CSV_PATH.exists():
        sys.exit(f"{CSV_PATH} not found — run scripts/load-test.sh first.")
    rows = []
    with CSV_PATH.open() as fh:
        for r in csv.DictReader(fh):
            try:
                t = int(r["seconds"])
            except (KeyError, ValueError):
                continue
            rows.append(
                {
                    "t": t,
                    "replicas": int(r["replicas"]) if r.get("replicas") else None,
                    "ready": int(r["ready_replicas"]) if r.get("ready_replicas") else 0,
                    "cpu": int(r["cpu_utilisation_pct"]) if r.get("cpu_utilisation_pct") else None,
                    "vus": int(r["offered_vus"]) if r.get("offered_vus") else 0,
                }
            )
    if not rows:
        sys.exit("no usable samples in the CSV")
    return rows


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Panel:
    """One stacked panel with its own y-scale and a shared x-scale."""

    def __init__(self, index: int, y_max: float, t_max: int) -> None:
        self.top = PAD_T + index * (PANEL_H + PANEL_GAP)
        self.bottom = self.top + PANEL_H
        self.y_max = y_max if y_max > 0 else 1
        self.t_max = t_max if t_max > 0 else 1

    def x(self, t: float) -> float:
        return PAD_L + (t / self.t_max) * PLOT_W

    def y(self, value: float) -> float:
        return self.bottom - (value / self.y_max) * PANEL_H


def axis_ticks(y_max: float, count: int = 3) -> list[float]:
    """Round tick values that land on something a reader recognises."""
    raw = y_max / count
    for step in (1, 2, 5, 10, 20, 25, 50, 100, 200):
        if step >= raw:
            break
    ticks = []
    v = 0.0
    while v <= y_max + 0.01:
        ticks.append(v)
        v += step
    return ticks


def build() -> str:
    rows = load_rows()
    t_max = max(r["t"] for r in rows)

    vus_max = max(max(r["vus"] for r in rows), 1)
    cpu_max = max([r["cpu"] for r in rows if r["cpu"] is not None] or [1])
    rep_max = max([r["replicas"] for r in rows if r["replicas"] is not None] or [1])

    # Headroom so the peak is not welded to the panel's top edge.
    p_load = Panel(0, vus_max * 1.15, t_max)
    p_cpu = Panel(1, max(cpu_max * 1.15, 70), t_max)
    p_rep = Panel(2, rep_max + 1, t_max)

    start_replicas = next((r["replicas"] for r in rows if r["replicas"] is not None), 2)
    ramp_t = 30  # k6 begins ramping here; see load/k6-script.js
    first_scale = next(
        (r for r in rows if r["replicas"] is not None and r["replicas"] > start_replicas), None
    )
    first_ready = next((r for r in rows if r["ready"] > start_replicas), None)
    peak_replicas = rep_max
    peak_cpu = cpu_max

    out: list[str] = []
    add = out.append

    add(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="{FONT}" role="img" '
        f'aria-label="Backend replicas against offered load over time during a k6 load test">'
    )
    add(f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>')

    # --- titles ---------------------------------------------------------------
    add(
        f'<text x="{PAD_L}" y="26" font-size="16" font-weight="650" fill="{INK}">'
        f"HPA scale-out: replicas follow offered load, with a measurable lag</text>"
    )
    add(
        f'<text x="{PAD_L}" y="44" font-size="12" fill="{INK_2}">'
        f"CivicPulse backend · kind cluster · HPA target 60% CPU · "
        f"{start_replicas}&#8202;&#8594;&#8202;{peak_replicas} replicas · "
        f"peak CPU {peak_cpu}%</text>"
    )

    panels = [
        (p_load, "Offered load", "VUs", BLUE, [(r["t"], r["vus"]) for r in rows], False),
        (
            p_cpu,
            "CPU utilisation",
            "% of request",
            ORANGE,
            [(r["t"], r["cpu"]) for r in rows if r["cpu"] is not None],
            False,
        ),
        (
            p_rep,
            "Backend replicas",
            "pods",
            AQUA,
            [(r["t"], r["replicas"]) for r in rows if r["replicas"] is not None],
            True,
        ),
    ]

    for panel, label, unit, colour, series, step in panels:
        # --- grid + y axis (recessive) ---
        for tick in axis_ticks(panel.y_max):
            y = panel.y(tick)
            if y < panel.top - 1:
                continue
            add(
                f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{PAD_L + PLOT_W}" y2="{y:.1f}" '
                f'stroke="{GRID}" stroke-width="1"/>'
            )
            add(
                f'<text x="{PAD_L - 10}" y="{y + 4:.1f}" font-size="11" fill="{INK_MUTED}" '
                f'text-anchor="end">{tick:g}</text>'
            )

        # --- panel label: the title names the series, so no legend box is needed ---
        add(
            f'<text x="{PAD_L}" y="{panel.top - 14}" font-size="13" font-weight="600" '
            f'fill="{INK}">{esc(label)}</text>'
        )
        add(
            f'<text x="{PAD_L + PLOT_W + 12}" y="{panel.top + 4}" font-size="11" '
            f'fill="{INK_MUTED}">{esc(unit)}</text>'
        )

        # --- the 60% HPA target, on the CPU panel only ---
        if label == "CPU utilisation":
            y60 = panel.y(60)
            add(
                f'<line x1="{PAD_L}" y1="{y60:.1f}" x2="{PAD_L + PLOT_W}" y2="{y60:.1f}" '
                f'stroke="{TARGET}" stroke-width="2" stroke-dasharray="5 4"/>'
            )
            add(
                f'<text x="{PAD_L + PLOT_W + 12}" y="{y60 + 4:.1f}" font-size="11" '
                f'font-weight="600" fill="{TARGET}">target 60%</text>'
            )

        # --- the series ---
        if not series:
            continue
        if step:
            # Step line: a replica count changes at an instant. A diagonal would draw
            # fractional pods that never existed.
            d = [f"M {panel.x(series[0][0]):.1f} {panel.y(series[0][1]):.1f}"]
            for i in range(1, len(series)):
                t, v = series[i]
                prev_v = series[i - 1][1]
                d.append(f"L {panel.x(t):.1f} {panel.y(prev_v):.1f}")
                d.append(f"L {panel.x(t):.1f} {panel.y(v):.1f}")
            path = " ".join(d)
        else:
            path = "M " + " L ".join(
                f"{panel.x(t):.1f} {panel.y(v):.1f}" for t, v in series
            )
        add(
            f'<path d="{path}" fill="none" stroke="{colour}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
        )

        # --- selective direct labels: the peak only, never a number on every point ---
        peak_t, peak_v = max(series, key=lambda p: p[1])
        add(
            f'<circle cx="{panel.x(peak_t):.1f}" cy="{panel.y(peak_v):.1f}" r="4" '
            f'fill="{colour}" stroke="{SURFACE}" stroke-width="2"/>'
        )
        add(
            f'<text x="{panel.x(peak_t) + 9:.1f}" y="{panel.y(peak_v) + 4:.1f}" font-size="11" '
            f'font-weight="600" fill="{INK}">{peak_v:g}{"%" if unit.startswith("%") else ""}</text>'
        )

    # --- the lag annotation: the point of the whole chart ---------------------
    if first_scale:
        x_ramp = p_load.x(ramp_t)
        x_scale = p_rep.x(first_scale["t"])
        lag = first_scale["t"] - ramp_t

        # Vertical guides tying the same instant across all three panels.
        for x, colour, dash in ((x_ramp, INK_MUTED, "3 3"), (x_scale, AQUA, "3 3")):
            add(
                f'<line x1="{x:.1f}" y1="{PAD_T - 6}" x2="{x:.1f}" y2="{p_rep.bottom}" '
                f'stroke="{colour}" stroke-width="1.5" stroke-dasharray="{dash}"/>'
            )

        # The span between them, drawn in the replica panel where the effect lands.
        y_span = p_rep.top - 38
        add(
            f'<line x1="{x_ramp:.1f}" y1="{y_span}" x2="{x_scale:.1f}" y2="{y_span}" '
            f'stroke="{INK_2}" stroke-width="1.5"/>'
        )
        for x in (x_ramp, x_scale):
            add(
                f'<line x1="{x:.1f}" y1="{y_span - 4}" x2="{x:.1f}" y2="{y_span + 4}" '
                f'stroke="{INK_2}" stroke-width="1.5"/>'
            )
        mid = (x_ramp + x_scale) / 2
        add(
            f'<text x="{mid:.1f}" y="{y_span - 7}" font-size="11.5" font-weight="650" '
            f'fill="{INK}" text-anchor="middle">lag {lag}s</text>'
        )

        add(
            f'<text x="{x_ramp + 5:.1f}" y="{PAD_T - 30}" font-size="10.5" fill="{INK_MUTED}">'
            f"load rises (t={ramp_t}s)</text>"
        )

        note = f"first new pod Ready t={first_ready['t']}s" if first_ready else ""
        add(
            f'<text x="{PAD_L}" y="{H - 14}" font-size="11" fill="{INK_2}">'
            f"HPA changed the replica count at t={first_scale['t']}s"
            f"{' · ' + esc(note) if note else ''}"
            f" — the gap is metrics staleness plus the controller sync period, not pod startup</text>"
        )

    # --- shared x axis --------------------------------------------------------
    add(
        f'<line x1="{PAD_L}" y1="{p_rep.bottom}" x2="{PAD_L + PLOT_W}" y2="{p_rep.bottom}" '
        f'stroke="{INK_MUTED}" stroke-width="1"/>'
    )
    tick_every = 60 if t_max > 240 else 30
    t = 0
    while t <= t_max:
        x = p_rep.x(t)
        add(
            f'<line x1="{x:.1f}" y1="{p_rep.bottom}" x2="{x:.1f}" y2="{p_rep.bottom + 5}" '
            f'stroke="{INK_MUTED}" stroke-width="1"/>'
        )
        add(
            f'<text x="{x:.1f}" y="{p_rep.bottom + 19}" font-size="11" fill="{INK_MUTED}" '
            f'text-anchor="middle">{t // 60}:{t % 60:02d}</text>'
        )
        t += tick_every
    add(
        f'<text x="{PAD_L + PLOT_W / 2:.1f}" y="{p_rep.bottom + 36}" font-size="11.5" '
        f'fill="{INK_2}" text-anchor="middle">elapsed time (m:ss)</text>'
    )

    add("</svg>")
    return "\n".join(out)


def main() -> int:
    OUT_PATH.write_text(build())
    print(f"wrote {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
