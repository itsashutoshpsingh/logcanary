"""Charts for docs/img/. Every number drawn comes from results/conditions.csv, results/runs.csv or
the raw run files."""

from __future__ import annotations

import csv
import gzip
import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from logcanary.conditions import ALL  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
IMG = ROOT / "docs" / "img"

BG, FG, MUTED, GRID = "#0C1421", "#FFFFFF", "#C9D4E2", "#1F2E45"
BLUE, GREEN, RED, YELLOW, WHITE = "#3B82F6", "#22C55E", "#EF4444", "#FACC15", "#FFFFFF"
SHIP_COLOR = {"filebeat": BLUE, "fluentbit": YELLOW, "vector": GREEN}
HATCH = {"syslog": "", "journald": "///"}  # journald bars are hatched, never faded
LS = {"syslog": "-", "journald": "--"}
SRC_TITLE = {"syslog": "File path (rsyslog, /var/log/syslog)", "journald": "Journal path (journald)"}
SHIP_NAME = {"filebeat": "Filebeat 8.19.25", "fluentbit": "Fluent Bit 5.1.5", "vector": "Vector 0.61.0"}
SRC_NAME = {"syslog": "rsyslog file", "journald": "journald"}
SHIPPERS = ("filebeat", "fluentbit", "vector")
SRCS = ("syslog", "journald")
SHIPPERS_SRCS = [(sh, src) for sh in SHIPPERS for src in SRCS]

plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG, "text.color": FG,
    "axes.labelcolor": FG, "axes.edgecolor": GRID, "xtick.color": MUTED, "ytick.color": MUTED,
    "grid.color": GRID, "axes.grid": True, "grid.linewidth": 0.8, "font.family": "Carlito",
    "font.size": 11, "axes.titlesize": 15, "axes.titleweight": "bold", "axes.labelsize": 12,
    "xtick.labelsize": 11, "ytick.labelsize": 11, "legend.fontsize": 11, "legend.frameon": False,
    "legend.labelcolor": FG, "axes.axisbelow": True, "hatch.color": BG, "hatch.linewidth": 1.2,
    "figure.titlesize": 15, "figure.titleweight": "bold",
})


def save(fig, name: str) -> str:
    IMG.mkdir(parents=True, exist_ok=True)
    fig.savefig(IMG / name, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return f"docs/img/{name}"


def load_conditions() -> list[dict]:
    with open(RESULTS / "conditions.csv") as f:
        return list(csv.DictReader(f))


def load_runs() -> list[dict]:
    with open(RESULTS / "runs.csv") as f:
        return list(csv.DictReader(f))


def fnum(x) -> float | None:
    return None if x in (None, "", "None") else float(x)


def bar_labels(ax, bars, values, fmt="{:.1f}", pad=0.6, size=11):
    for b, v in zip(bars, values, strict=False):
        if v is None:
            continue
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + pad, fmt.format(v), ha="center", va="bottom",
                color=FG, fontsize=size)


def run_dirs(cond: str) -> list[Path]:
    return sorted(p for p in (RESULTS / "runs" / cond).glob("r*") if (p / "result.json").exists())


def read_gz_csv(p: Path) -> list[dict]:
    with gzip.open(p, "rt", newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------------------------
def fig_pipeline() -> str:
    fig, ax = plt.subplots(figsize=(11, 5.0))
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 5.0)
    ax.axis("off")

    def box(x, y, w, h, title, sub, color):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc=BG,
                                    ec=color, lw=1.6))
        ax.text(x + w / 2, y + h - 0.2, title, ha="center", va="top", fontsize=12, color=FG, weight="bold")
        ax.text(x + w / 2, y + h - 0.52, sub, ha="center", va="top", fontsize=11, color=MUTED, linespacing=1.3)

    def arrow(x1, y1, x2, y2, color=MUTED, ls="-"):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops={"arrowstyle": "->", "color": color, "lw": 1.4, "ls": ls})

    ax.add_patch(FancyBboxPatch((0.15, 0.75), 6.0, 3.95, boxstyle="round,pad=0.02,rounding_size=0.1",
                                fc="none", ec=GRID, lw=1.2, ls="--"))
    ax.text(0.3, 4.52, "Host under test: Ubuntu 24.04 container (lab-host)", fontsize=11, color=MUTED)
    box(0.35, 2.95, 1.75, 1.35, "Canary writer", "Numbered events\nvia syslog(3) and\nnative journal", WHITE)
    box(0.35, 0.95, 1.75, 1.35, "Source ledger", "SQLite: seq, true,\nmonotonic and\nhost clock", WHITE)
    box(2.45, 3.15, 1.75, 1.15, "rsyslog 8.2312", "/dev/log ->\n/var/log/syslog", MUTED)
    box(2.45, 1.75, 1.75, 1.15, "journald 255", "Native socket ->\n/var/log/journal", MUTED)
    box(4.45, 0.95, 1.55, 3.35, "Shippers", "Filebeat 8.19.25\nFluent Bit 5.1.5\nVector 0.61.0\n\nRead the same\n"
        "files, one index\neach", YELLOW)
    box(6.9, 2.75, 1.9, 1.6, "Elasticsearch", "Version 8.19.25\nIngest pipeline sets\nevent.ingested", BLUE)
    box(9.1, 2.75, 1.75, 1.6, "Reconciler", "Scrolls every doc\nof the run and\ncompares with\nthe ledger", GREEN)
    arrow(2.1, 3.75, 2.45, 3.75)
    arrow(2.1, 3.3, 2.45, 2.35)
    arrow(1.22, 2.95, 1.22, 2.3, WHITE)
    arrow(4.2, 3.75, 4.45, 3.75)
    arrow(4.2, 2.35, 4.45, 2.35)
    arrow(6.0, 3.55, 6.9, 3.55)
    arrow(8.8, 3.55, 9.1, 3.55)
    ax.plot([1.22, 1.22, 9.97, 9.97], [0.95, 0.4, 0.4, 2.35], color=GREEN, lw=1.3, ls=":")
    arrow(9.97, 2.3, 9.97, 2.75, GREEN)
    ax.text(5.6, 0.12, "Ground truth goes round the pipeline, never through it", fontsize=11, color=GREEN,
            ha="center")
    ax.text(6.4, 2.45, "Faults: bursts, shipper restart and\nSIGKILL, network partition, Elasticsearch\n"
            "stop or pause, clock jump (libfaketime),\nlog rotation, journal vacuum, daemon\nSIGKILL, disk caps",
            fontsize=11,
            color=RED, ha="left", va="top", linespacing=1.4)
    ax.set_title("Canaries written on the host are counted again in Elasticsearch, against a ledger the "
                 "pipeline never touches", loc="left")
    return save(fig, "pipeline.png")


def cond_map(rows: list[dict]) -> dict:
    return {(r["condition"], r["shipper"], r["src"]): r for r in rows}


def present(rows: list[dict], names: list[str]) -> list[str]:
    have = {r["condition"] for r in rows}
    return [n for n in names if n in have]


FAULT_ORDER = ["baseline", "burst_1k", "burst_4k", "burst_max", "shipper_restart", "shipper_crash", "partition_60",
               "partition_300", "es_down_120", "es_down_600", "es_freeze_120", "rotate_stock", "rotate_copytruncate",
               "journal_vacuum", "daemon_crash", "disk_pressure"]
SHORT = {"baseline": "steady 20/s", "burst_1k": "burst 1k/s", "burst_4k": "burst 4k/s", "burst_max": "burst max",
         "shipper_restart": "shipper restart", "shipper_crash": "shipper SIGKILL", "partition_60": "partition 60 s",
         "partition_300": "partition 300 s", "es_down_120": "ES down 120 s", "es_down_600": "ES down 10 min",
         "es_freeze_120": "ES paused 120 s", "rotate_stock": "logrotate (stock)",
         "rotate_copytruncate": "logrotate copytruncate", "journal_vacuum": "journal vacuum",
         "daemon_crash": "rsyslog+journald SIGKILL", "disk_pressure": "partition + disk caps",
         "sizes": "sizes 1-64 KB", "mangling": "multiline/unicode", "clock_fwd_2h": "clock +2 h",
         "clock_back_10m": "clock -10 min"}


SHORT = {k: v[0].upper() + v[1:] for k, v in SHORT.items()}
SHORT.update({"jammy_" + k: v + " (22.04)" for k, v in list(SHORT.items())})


def fig_hero_loss() -> str:
    rows = load_conditions()
    cm = cond_map(rows)
    conds = present(rows, FAULT_ORDER)
    fig, axes = plt.subplots(1, 2, figsize=(15, 0.75 * len(conds) + 2.4), sharey=True)
    y = np.arange(len(conds))
    h = 0.26
    worst = max(rows, key=lambda r: fnum(r["loss_mean_pct"]) or 0)
    top = max((fnum(r["loss_ci_hi"]) or fnum(r["loss_mean_pct"]) or 0) for r in rows if r["condition"] in conds)
    xmax = min(105.0, max(10.0, top * 1.15))
    for ax, src in zip(axes, SRCS, strict=True):
        for i, sh in enumerate(SHIPPERS):
            vals, lo, hi = [], [], []
            for c in conds:
                r = cm.get((c, sh, src))
                v = fnum(r["loss_mean_pct"]) if r else None
                vals.append(v or 0)
                lo.append(max(0.0, (v or 0) - (fnum(r["loss_ci_lo"]) or v or 0)) if r else 0)
                hi.append(max(0.0, (fnum(r["loss_ci_hi"]) or v or 0) - (v or 0)) if r else 0)
            yy = y + (i - 1) * h
            ax.barh(yy, vals, h, color=SHIP_COLOR[sh], label=SHIP_NAME[sh], xerr=[lo, hi],
                    error_kw={"ecolor": MUTED, "lw": 0.8, "capsize": 1.5})
            for yv, v in zip(yy, vals, strict=True):
                ax.text(v + xmax / 130, yv, f"{v:.1f}" if v >= 0.05 else ("0" if v == 0 else f"{v:.2f}"), va="center",
                        fontsize=11, color=FG if v else MUTED)
        ax.set_title(SRC_TITLE[src], loc="left", fontsize=13)
        ax.set_xlabel("Canaries lost, % of sent (mean of repeats; whisker = 95% CI)")
        ax.set_xlim(0, xmax)
    axes[0].set_yticks(y, [SHORT[c] for c in conds])
    axes[0].invert_yaxis()
    axes[0].legend(loc="lower right")
    fig.suptitle(f"Default pipelines lost up to {float(worst['loss_mean_pct']):.0f}% of canaries "
                 f"({SHIP_NAME[worst['shipper']]}, {SHORT.get(worst['condition'], worst['condition'])}); "
                 "steady load lost none", x=0.01, ha="left")
    fig.tight_layout()
    return save(fig, "loss_by_condition.png")


def _arrival_latencies(cond: str) -> dict:
    out = defaultdict(list)
    for d in run_dirs(cond):
        led = {(r["src"], r["seq"]): int(r["ts_wall_ns"]) for r in read_gz_csv(d / "ledger.csv.gz")}
        first = {}
        for a in read_gz_csv(d / "arrivals.csv.gz"):
            k = (a["shipper"], a["src"], a["seq"])
            ing = int(a["ingested_ns"])
            if k not in first or ing < first[k]:
                first[k] = ing
        for (sh, src, seq), ing in first.items():
            out[(sh, src)].append((ing - led[(src, seq)]) / 1e6)
    return out


def fig_latency_ecdf() -> str:
    lat = _arrival_latencies("baseline")
    if not lat:
        raise FileNotFoundError("baseline")
    fig, ax = plt.subplots(figsize=(12, 6.2))
    meds = {}
    for sh in SHIPPERS:
        for src, ls in (("syslog", "-"), ("journald", "--")):
            v = np.sort(np.array(lat[(sh, src)]))
            if not len(v):
                continue
            meds[(sh, src)] = float(np.median(v))
            ax.plot(v / 1000, np.arange(1, len(v) + 1) / len(v) * 100, ls, color=SHIP_COLOR[sh], lw=2,
                    label=f"{SHIP_NAME[sh]}, {SRC_NAME[src]} (median {np.median(v) / 1000:.2f} s, n={len(v)})")
    ax.set_xscale("log")
    ax.set_xlabel("Ingest latency: indexed in Elasticsearch minus written on the host (seconds, log scale)")
    ax.set_ylabel("Canaries indexed by then (%)")
    slow = max(meds, key=meds.get)
    fast = min(meds, key=meds.get)
    ax.set_title(f"Steady load: median delay ranged from {meds[fast] / 1000:.2f} s ({SHIP_NAME[fast[0]]}) to "
                 f"{meds[slow] / 1000:.1f} s ({SHIP_NAME[slow[0]]})", loc="left")
    ax.set_xlim(left=0.01)
    ax.legend(fontsize=10.5, loc="upper left")
    return save(fig, "latency_baseline_ecdf.png")


def fig_latency_conditions() -> str:
    rows = load_conditions()
    cm = cond_map(rows)
    conds = present(rows, FAULT_ORDER)
    keys = [(sh, src) for sh in SHIPPERS for src in SRCS]
    grid = np.full((len(keys), len(conds)), np.nan)
    for i, (sh, src) in enumerate(keys):
        for j, c in enumerate(conds):
            r = cm.get((c, sh, src))
            v = fnum(r["lat_p95_ms"]) if r else None
            grid[i, j] = v / 1000 if v is not None else np.nan
    fig, ax = plt.subplots(figsize=(1.15 * len(conds) + 4, 5.4))
    from matplotlib.colors import LinearSegmentedColormap, LogNorm

    cmap = LinearSegmentedColormap.from_list("lc", [BLUE, YELLOW, RED])
    im = ax.imshow(np.clip(grid, 0.1, None), aspect="auto", cmap=cmap, norm=LogNorm(vmin=0.1, vmax=1000))
    for i in range(len(keys)):
        for j in range(len(conds)):
            v = grid[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:.0f}" if v >= 10 else f"{v:.1f}", ha="center", va="center", fontsize=11,
                        color=BG, weight="bold")
    ax.set_xticks(range(len(conds)), [SHORT[c] for c in conds], rotation=35, ha="right")
    ax.set_yticks(range(len(keys)), [f"{SHIP_NAME[s].split(' ')[0] if s != 'fluentbit' else 'Fluent Bit'}, "
                                     f"{SRC_NAME[p]}" for s, p in keys])
    ax.grid(False)
    cb = fig.colorbar(im, ax=ax, pad=0.01)
    cb.set_label("95th percentile ingest latency (s, log scale)", color=FG)
    cb.ax.yaxis.set_tick_params(color=MUTED)
    worst = np.nanmax(grid)
    ax.set_title(f"The 95th percentile delay ran from about a second to {worst / 60:.0f} minutes behind the host",
                 loc="left")
    return save(fig, "latency_p95_heatmap.png")


def fig_duplicates() -> str:
    rows = load_conditions()
    cm = cond_map(rows)
    conds = [c for c in present(rows, FAULT_ORDER)
             if any((fnum(cm[(c, s, p)]["dup_total"]) or 0) > 0 for s in SHIPPERS for p in SRCS if (c, s, p) in cm)]
    if not conds:
        conds = present(rows, ["shipper_restart", "shipper_crash", "partition_60", "es_down_120"])
    fig, ax = plt.subplots(figsize=(max(9, 2.0 * len(conds) + 3), 6))
    x = np.arange(len(conds))
    w = 0.13
    best = (0, None)
    for i, (sh, src) in enumerate([(s, p) for s in SHIPPERS for p in SRCS]):
        vals = [fnum(cm[(c, sh, src)]["dup_mean_pct"]) if (c, sh, src) in cm else 0 for c in conds]
        for c, v in zip(conds, vals, strict=True):
            if v and v > best[0]:
                best = (v, (c, sh, src))
        b = ax.bar(x + (i - 2.5) * w, vals, w, color=SHIP_COLOR[sh], hatch=HATCH[src], edgecolor=BG, lw=0,
                   label=f"{SHIP_NAME[sh]}, {SRC_NAME[src]}")
        bar_labels(ax, [bb for bb, v in zip(b, vals, strict=True) if v], [v for v in vals if v], "{:.0f}", pad=0.5)
    ax.set_xticks(x, [SHORT[c] for c in conds], rotation=20, ha="right")
    ax.set_ylabel("Duplicate documents, % of sent (mean of repeats)")
    if best[1]:
        c, sh, src = best[1]
        ax.set_title(f"Duplicates: at most {best[0]:.1f}% ({SHIP_NAME[sh]}, {SRC_NAME[src]}, {SHORT[c]})",
                     loc="left")
    else:
        ax.set_title("No condition produced a duplicate document", loc="left")
    ax.legend(fontsize=10.5, ncol=3, loc="upper left")
    return save(fig, "duplicates.png")


def _checks_by(cond: str, key: str) -> dict:
    """{(shipper, src): {bucket: {check: n}}} summed over a condition's runs from result.json;
    bucket is the nominal size (int) or the content kind."""
    out = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for d in run_dirs(cond):
        for k, m in json.loads((d / "result.json").read_text()).items():
            sh, src = k.split("/")
            for b, c in m.get(f"checks_by_{key}", {}).items():
                for st, n in c.items():
                    out[(sh, src)][int(b) if key == "size" else b][st] += n
    return out


def fig_fidelity() -> str:
    sizes = _checks_by("sizes", "size")
    kinds = _checks_by("mangling", "kind")
    if not sizes and not kinds:
        raise FileNotFoundError("sizes/mangling")
    keys = [(sh, src) for sh in SHIPPERS for src in SRCS]
    fig, axes = plt.subplots(1, 2, figsize=(17, 6), gridspec_kw={"width_ratios": [7, 4]})
    from matplotlib.colors import LinearSegmentedColormap

    cmap = LinearSegmentedColormap.from_list("ok", [RED, YELLOW, GREEN])
    lowest = (101, "")
    for ax, data, title in ((axes[0], sizes, "by message size"), (axes[1], kinds, "by content")):
        buckets = sorted({b for k in data.values() for b in k}, key=lambda b: (isinstance(b, str), b))
        grid = np.full((len(keys), len(buckets)), np.nan)
        notes = [["" for _ in buckets] for _ in keys]
        for i, k in enumerate(keys):
            for j, b in enumerate(buckets):
                c = data.get(k, {}).get(b)
                if not c:
                    continue
                n = sum(c.values())
                grid[i, j] = 100 * c.get("intact", 0) / n
                top = max((x for x in c if x != "intact"), key=lambda x: c[x], default="")
                notes[i][j] = top if top and c[top] else ""
                if grid[i, j] < lowest[0]:
                    lowest = (grid[i, j], f"{b}")
        ax.imshow(grid, aspect="auto", cmap=cmap, vmin=0, vmax=100)
        for i in range(len(keys)):
            for j in range(len(buckets)):
                if not np.isnan(grid[i, j]):
                    ax.text(j, i, f"{grid[i, j]:.0f}%" + (f"\n{notes[i][j].capitalize()}" if grid[i, j] < 100 else ""),
                            ha="center", va="center", fontsize=11, color=BG, weight="bold")
        labels = [f"{b / 1024:.1f} KB".replace(".0 KB", " KB") if isinstance(b, int) else str(b).capitalize()
                  for b in buckets]
        ax.set_xticks(range(len(buckets)), labels, rotation=0)
        ax.set_yticks(range(len(keys)), [f"{SHIP_NAME[s].rsplit(' ', 1)[0]}, {SRC_NAME[p]}" for s, p in keys])
        ax.grid(False)
        ax.set_title(f"Fields intact, {title}", loc="left", fontsize=13)
    axes[0].set_xlabel("Message size written")
    axes[1].set_xlabel("Message content")
    axes[1].set_yticklabels([])
    def worst_at(data, src, bucket):
        vals = []
        for sh in SHIPPERS:
            c = data.get((sh, src), {}).get(bucket)
            if c:
                vals.append(100 * c.get("intact", 0) / sum(c.values()))
        return min(vals) if vals else float("nan")

    fig.suptitle(f"Field fidelity: at most {worst_at(sizes, 'syslog', 65536):.0f}% of 64 KB canaries arrived intact "
                 f"through rsyslog against {worst_at(sizes, 'journald', 65536):.0f}% through journald; multiline "
                 f"canaries {worst_at(kinds, 'syslog', 'multiline'):.0f}% against "
                 f"{worst_at(kinds, 'journald', 'multiline'):.0f}%", x=0.01, ha="left")
    fig.tight_layout()
    return save(fig, "fidelity.png")


def _faults_windows(meta: dict) -> list[tuple[float, float, str]]:
    t0 = meta["t_start_ns"]
    opens = {"partition": "heal", "es_stop": "es_start", "es_freeze": "es_thaw", "shipper_kill": "shipper_start"}
    out = []
    fl = meta["faults"]
    for f in fl:
        a = f["action"]
        s = (f["start_ns"] - t0) / 1e9
        if a in opens:
            end = next((g for g in fl if g["action"] == opens[a] and g["start_ns"] >= f["start_ns"]), None)
            out.append((s, ((end["end_ns"] - t0) / 1e9) if end else s + 1, a))
        elif a not in opens.values():
            out.append((s, max(s + 1.5, (f["end_ns"] - t0) / 1e9), a))
    return out


def _timeline(ax, cond: str):
    dirs = run_dirs(cond)
    if not dirs:
        return False
    d = dirs[0]
    meta = json.loads((d / "meta.json").read_text())
    t0 = meta["t_start_ns"]
    led = read_gz_csv(d / "ledger.csv.gz")
    n = {src: sum(1 for r in led if r["src"] == src) for src in SRCS}
    sent_t = np.sort(np.array([(int(r["ts_wall_ns"]) - t0) / 1e9 for r in led if r["src"] == "syslog"]))
    ax.plot(sent_t, np.arange(1, len(sent_t) + 1) / len(sent_t) * 100, color=MUTED, lw=1.4, label="Written")
    first = {}
    for a in read_gz_csv(d / "arrivals.csv.gz"):
        k = (a["shipper"], a["src"], a["seq"])
        ing = int(a["ingested_ns"])
        if k not in first or ing < first[k]:
            first[k] = ing
    xmax = sent_t[-1] if len(sent_t) else 1
    for sh in SHIPPERS:
        for src, ls in (("syslog", "-"), ("journald", "--")):
            t = np.sort(np.array([(v - t0) / 1e9 for (s, p, _), v in first.items() if s == sh and p == src]))
            if not len(t):
                continue
            xmax = max(xmax, t[-1])
            ax.plot(np.concatenate([t, [t[-1] + 5]]), np.concatenate([np.arange(1, len(t) + 1), [len(t)]]) / n[src]
                    * 100, ls, color=SHIP_COLOR[sh], lw=1.8)
    for s, e, _a in _faults_windows(meta):
        ax.axvspan(s, e, color=GRID, lw=0, zorder=0)
        ax.axvline(s, color=RED, lw=1.2)
    ax.set_xlim(0, xmax * 1.03)
    ax.set_ylim(0, 103)
    ax.set_title(f"{SHORT.get(cond, cond)} (run {meta['run'][:6]})", loc="left", fontsize=13)
    return True


def fig_timelines() -> str:
    conds = present(load_conditions(), ["shipper_restart", "shipper_crash", "partition_60", "es_down_120",
                                        "es_freeze_120", "daemon_crash", "rotate_copytruncate", "disk_pressure",
                                        "burst_4k"])
    cols = 3
    rws = (len(conds) + cols - 1) // cols
    fig, axes = plt.subplots(rws, cols, figsize=(17, 4.4 * rws), squeeze=False)
    for ax, c in zip(axes.flat, conds, strict=False):
        _timeline(ax, c)
    for ax in list(axes.flat)[len(conds):]:
        ax.axis("off")
    for ax in axes[:, 0]:
        ax.set_ylabel("Canaries indexed (%)")
    for ax in axes[-1, :]:
        ax.set_xlabel("Seconds since the writer started")
    from matplotlib.lines import Line2D

    handles = [Line2D([], [], color=SHIP_COLOR[s], lw=2, label=SHIP_NAME[s]) for s in SHIPPERS] + [
        Line2D([], [], color=FG, ls="-", label="File path (rsyslog)"),
        Line2D([], [], color=FG, ls="--", label="Journal path (journald)"),
        Line2D([], [], color=MUTED, label="Written on the host"),
        matplotlib.patches.Patch(color=GRID, label="Fault active (red line: start)")]
    fig.legend(handles=handles, loc="lower center", ncol=4, bbox_to_anchor=(0.5, -0.04))
    fig.suptitle("Timelines: a line that ends below 100% never caught up; the gap is lost canaries",
                 x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    return save(fig, "timelines.png")


def fig_clock() -> str:
    conds = present(load_conditions(), ["clock_fwd_2h", "clock_back_10m"])
    if not conds:
        raise FileNotFoundError("clock")
    fig, axes = plt.subplots(1, len(conds), figsize=(8.5 * len(conds), 6), squeeze=False)
    follow: dict = {}
    for ax, cond in zip(axes[0], conds, strict=True):
        d = run_dirs(cond)[0]
        meta = json.loads((d / "meta.json").read_text())
        t0 = meta["t_start_ns"]
        led = {(r["src"], r["seq"]): int(r["ts_wall_ns"]) for r in read_gz_csv(d / "ledger.csv.gz")}
        pts = defaultdict(list)
        for a in read_gz_csv(d / "arrivals.csv.gz"):
            if not a["ts_event_ns"]:
                continue
            true = led[(a["src"], a["seq"])]
            pts[(a["shipper"], a["src"])].append(((true - t0) / 1e9, (int(a["ts_event_ns"]) - true) / 6e10))
        for i, sh in enumerate(SHIPPERS):
            for src, mk in (("syslog", "o"), ("journald", "x")):
                p = np.array(sorted(pts[(sh, src)]))
                if len(p):
                    ax.plot(p[::7, 0], p[::7, 1] + (i - 1) * 1.5 * (1 if "fwd" in cond else 0.1), mk, ms=2.5,
                            color=SHIP_COLOR[sh], label=f"{SHIP_NAME[sh]}, {SRC_NAME[src]}")
        wins = _faults_windows(meta)
        if len(wins) >= 2:  # the jump is in force between the first and the second clock action
            lo_t, hi_t = wins[0][1] + 2, wins[1][0] - 2
            offset_min = meta["faults"][0]["kwargs"]["offset_s"] / 60
            for k, p in pts.items():
                inside = [d for t, d in p if lo_t <= t <= hi_t]
                if inside:  # a pair with no canary inside the window (all lost) is not judged
                    follow[k] = follow.get(k, True) and np.median(inside) / offset_min > 0.5
            ax.axvspan(wins[0][0], wins[1][0], color=GRID, lw=0, zorder=0)
        ax.set_xlabel("Seconds since the writer started (true time)")
        ax.set_ylabel("Event time in the SIEM minus true write time (minutes)")
        ax.set_title(SHORT[cond] + " on the host", loc="left", fontsize=13)
    axes[0][0].legend(fontsize=10.5, loc="center left")
    followed = sorted(k for k, v in follow.items() if v)
    missed = [f"{SHIP_NAME[sh].rsplit(' ', 1)[0]} on {SRC_NAME[src]}" for sh, src in SHIPPERS_SRCS
              if (sh, src) in follow and not follow[(sh, src)]]
    fig.suptitle(f"Clock jumps: the SIEM's event time followed the host clock on {len(followed)} of {len(follow)} "
                 "shipper and path pairs" + (f"; not on {', '.join(missed)}" if missed else ""), x=0.01, ha="left")
    fig.tight_layout()
    return save(fig, "clock_skew.png")


def fig_bursts() -> str:
    rows = load_conditions()
    cm = cond_map(rows)
    conds = present(rows, ["baseline", "burst_1k", "burst_4k", "burst_max"])
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.6), sharey=True)
    x = np.arange(len(conds))
    w = 0.22
    for ax, src in zip(axes, SRCS, strict=True):
        disk = []
        for c in conds:
            r = cm.get((c, "filebeat", src))
            disk.append(100 * (fnum(r["lost_before_disk_total"]) or 0) / fnum(r["sent_total"]) if r else 0)
        b = ax.bar(x - 1.5 * w, disk, w, color=RED, label="Never written to disk by the host")
        bar_labels(ax, b, disk, "{:.0f}", pad=0.8)
        for i, sh in enumerate(SHIPPERS):
            vals = [fnum(cm[(c, sh, src)]["loss_mean_pct"]) if (c, sh, src) in cm else 0 for c in conds]
            b = ax.bar(x + (i - 0.5) * w, vals, w, color=SHIP_COLOR[sh], label=f"Missing in ES via {SHIP_NAME[sh]}")
            bar_labels(ax, b, vals, "{:.0f}", pad=0.8)
        ax.set_xticks(x, [SHORT[c] for c in conds])
        ax.set_title(SRC_TITLE[src], loc="left", fontsize=13)
        ax.set_ylim(0, 105)
    axes[0].set_ylabel("Canaries lost, % of sent (mean of repeats)")
    axes[1].legend(loc="upper left")
    host = max((100 * (fnum(cm[(c, "filebeat", p)]["lost_before_disk_total"]) or 0) / fnum(cm[(c, "filebeat", p)]
                ["sent_total"]) for c in conds for p in SRCS if (c, "filebeat", p) in cm), default=0)
    worst = max((r for r in rows if r["condition"] in conds), key=lambda r: fnum(r["loss_mean_pct"]) or 0)
    lead = (f"the host wrote {'every' if host == 0 else f'all but {host:.1f}% of'} canary to disk, but "
            f"{SHIP_NAME[worst['shipper']]} lost {fnum(worst['loss_mean_pct']):.0f}% ({SRC_NAME[worst['src']]}, "
            f"{SHORT[worst['condition']]})")
    fig.suptitle(f"Bursts: {lead}", x=0.01, ha="left")
    fig.tight_layout()
    return save(fig, "bursts.png")


def fig_alerts() -> str:
    runs = load_runs()
    lossy = [r for r in runs if int(r["lost"]) > 0]
    comps = ["Shipper log", "Host daemon log", "Shipper counter", "Shipper crashed\n(restart count)", "SIEM"]
    keys = sorted({(r["condition"], r["shipper"], r["src"]) for r in lossy},
                  key=lambda k: (list(ALL).index(k[0]), SHIPPERS.index(k[1]), SRCS.index(k[2])))
    if not keys:
        raise FileNotFoundError("no lossy runs")
    grid = np.zeros((len(keys), len(comps)))
    for i, k in enumerate(keys):
        rs = [r for r in lossy if (r["condition"], r["shipper"], r["src"]) == k]
        n = len(rs)
        grid[i, 0] = sum(r["alert_shipper"] == "loss" for r in rs) / n
        grid[i, 1] = sum(r["alert_host"] == "loss" for r in rs) / n
        grid[i, 2] = sum(fnum(r["shipper_counted_loss"]) > 0 for r in rs) / n
        grid[i, 3] = sum((fnum(r["shipper_crashes"]) or 0) > 0 for r in rs) / n
        grid[i, 4] = 0.0  # nothing in the default pipeline sends a loss signal to Elasticsearch
    from matplotlib.colors import LinearSegmentedColormap

    cmap = LinearSegmentedColormap.from_list("al", [RED, YELLOW, GREEN])
    fig, ax = plt.subplots(figsize=(11, 0.45 * len(keys) + 2.4))
    ax.imshow(grid, aspect="auto", cmap=cmap, vmin=0, vmax=1)
    for i in range(len(keys)):
        for j in range(len(comps)):
            ax.text(j, i, f"{grid[i, j] * 100:.0f}%", ha="center", va="center", fontsize=11, color=BG,
                    weight="bold")
    ax.set_xticks(range(len(comps)), comps)
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(keys)), [f"{SHORT.get(c, c)} | {SHIP_NAME[s].rsplit(' ', 1)[0]} | {SRC_NAME[p]}"
                                     for c, s, p in keys])
    ax.grid(False)
    silent = sum(r["silent"] == "True" for r in lossy)
    ax.set_title(f"Who said anything? In {silent} of {len(lossy)} lossy streams no log line anywhere mentioned "
                 "lost events;\ncells: share of lossy runs where each signal appeared", loc="left",
                 pad=36)
    return save(fig, "alerts.png")


def fig_tuned() -> str:
    rows = load_conditions()
    cm = cond_map(rows)
    base = present(rows, ["shipper_restart", "shipper_crash", "partition_60", "es_down_120", "disk_pressure"])
    base = [c for c in base if c + "_tuned" in {r["condition"] for r in rows}]
    if not base:
        raise FileNotFoundError("tuned")
    fig, axes = plt.subplots(1, 3, figsize=(18, 6), sharey=True)
    x = np.arange(len(base))
    w = 0.2
    for ax, sh in zip(axes, SHIPPERS, strict=True):
        for i, (suffix, src) in enumerate((("", "syslog"), ("_tuned", "syslog"), ("", "journald"),
                                           ("_tuned", "journald"))):
            vals = [fnum(cm[(c + suffix, sh, src)]["loss_mean_pct"]) if (c + suffix, sh, src) in cm else 0
                    for c in base]
            color = RED if not suffix else GREEN
            b = ax.bar(x + (i - 1.5) * w, vals, w, color=color, hatch=HATCH[src], edgecolor=BG, lw=0,
                       label=f"{'Default' if not suffix else 'Tuned'}, {SRC_NAME[src]}")
            bar_labels(ax, b, vals, "{:.0f}", pad=0.8)
        ax.set_xticks(x, [SHORT[c] for c in base], rotation=25, ha="right")
        ax.set_title(SHIP_NAME[sh], loc="left", fontsize=13)
        ax.set_ylim(0, 105)
    axes[0].set_ylabel("Canaries lost, % of sent (mean of repeats)")
    axes[0].legend(fontsize=10.5)
    fig.suptitle("Default against tuned shipper settings (offset DB, unlimited retries, disk buffers, "
                 "end-to-end acknowledgements)", x=0.01, ha="left")
    fig.tight_layout()
    return save(fig, "default_vs_tuned.png")


def fig_blind() -> str:
    rows = load_conditions()
    cm = cond_map(rows)
    conds = present(rows, FAULT_ORDER + ["clock_fwd_2h", "clock_back_10m"])
    fig, ax = plt.subplots(figsize=(17, 6.2))
    x = np.arange(len(conds))
    w = 0.13
    worst = (0, None)
    for i, (sh, src) in enumerate([(s, p) for s in SHIPPERS for p in SRCS]):
        lost = [fnum(cm[(c, sh, src)]["loss_mean_pct"]) or 0 if (c, sh, src) in cm else 0 for c in conds]
        blind = [fnum(cm[(c, sh, src)]["blind_mean_pct"]) or 0 if (c, sh, src) in cm else 0 for c in conds]
        late = [max(0.0, b - lo) for b, lo in zip(blind, lost, strict=True)]
        xx = x + (i - 2.5) * w
        ax.bar(xx, lost, w, color=SHIP_COLOR[sh], hatch=HATCH[src], edgecolor=BG, lw=0)
        ax.bar(xx, late, w, bottom=lost, color=RED, hatch=HATCH[src], edgecolor=BG, lw=0)
        for c, b in zip(conds, blind, strict=True):
            if b > worst[0]:
                worst = (b, c)
    ax.set_xticks(x, [SHORT.get(c, c) for c in conds], rotation=35, ha="right")
    ax.set_ylabel("Sent canaries a 5 minute rule never sees (%)")
    from matplotlib.patches import Patch

    ax.legend(handles=[Patch(color=SHIP_COLOR[s], label=f"Lost ({SHIP_NAME[s]})") for s in SHIPPERS] +
              [Patch(color=RED, label="Arrived, but too late or stamped outside the rule's window"),
               Patch(facecolor=MUTED, hatch="///", edgecolor=BG, label="Hatched: journal path")],
              fontsize=10.5, loc="upper left")
    if worst[1]:
        ax.set_title(f"Blind spots for a scheduled rule (every 5 min, looking back 6 min): up to {worst[0]:.0f}% "
                     f"under {SHORT.get(worst[1], worst[1])}", loc="left")
    return save(fig, "rule_blind_spots.png")


def main() -> list[str]:
    out = [fig_pipeline()]
    for fn in (fig_hero_loss, fig_latency_ecdf, fig_latency_conditions, fig_duplicates, fig_fidelity,
               fig_timelines, fig_clock, fig_bursts, fig_alerts, fig_tuned, fig_blind):
        try:
            out.append(fn())
        except FileNotFoundError as e:  # a condition not run yet
            print(f"skip {fn.__name__}: {e}")
    print("\n".join(o for o in out if o))
    return out


