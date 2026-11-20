"""Exercise 2: compare two text models on the same simulation setup.

For every run it reads the newest log, logs/<run name>/<timestamp>/run.jsonl, and:
  * collects every memory the agents formed (add_event / add_chat / add_thought)
    with its in-game time and valence (-5 ... +5), and plots valence over time
    per agent, both models overlaid;
  * computes valence statistics (mean, standard deviation = emotional variance);
  * counts LLM calls and failed attempts, split by failure type:
        json_unmarshal  - response was not parseable JSON
        json_validation - JSON did not match the prompt's JSON schema
        validation      - JSON was valid but broke a semantic rule
                          (e.g. schedule durations that do not add up)

Usage (from the repository root):
    python analysis/ex2_compare_models.py \
        --run "Model A: gpt-6-luna=simulation/ex1_bernard_v3" \
        --run "Model B: Qwen3-14B-AWQ=simulation/ex2_model_b_qwen" \
        --from 07:00 --until 08:30 --plot analysis/ex2_valence.png --markdown analysis/ex2_report.md
"""
import argparse
import glob
import json
import os
import statistics
from collections import Counter, defaultdict

MEMORY_MSGS = {"add_event": "event", "add_chat": "chat", "add_thought": "thought"}
# Validated categorical slots 1-2 (light surface) and chart chrome from the dataviz palette.
SERIES = ["#2a78d6", "#eb6834"]
INK, INK_2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"


def latest_log(run_dir):
    name = os.path.basename(os.path.normpath(run_dir))
    files = glob.glob(os.path.join("logs", name, "*", "run.jsonl"))
    if not files:
        raise SystemExit(f"no log found for {name} under logs/{name}/")
    return max(files, key=os.path.getmtime)


def read_log(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def hhmm(sim_time):
    return sim_time[11:16]


def minutes(sim_time):
    return int(sim_time[11:13]) * 60 + int(sim_time[14:16]) + int(sim_time[17:19]) / 60


def analyse(log_path, t_from, t_until):
    memories = []
    calls = Counter()
    retry_reasons = Counter()
    retry_prompts = Counter()
    calls_with_retry = set()
    http_fail = 0
    for r in read_log(log_path):
        msg = r.get("msg")
        if msg in MEMORY_MSGS and r.get("sim_time") and r.get("valence") is not None:
            t = hhmm(r["sim_time"])
            if t_from <= t <= t_until:
                memories.append({"persona": r.get("persona"), "kind": MEMORY_MSGS[msg],
                                 "min": minutes(r["sim_time"]), "valence": int(r["valence"]),
                                 "text": r.get("embedding_key", "")})
        elif msg == "llm_call_start":
            calls["calls"] += 1
        elif msg == "llm_call_ok":
            calls["ok"] += 1
        elif msg == "llm_retry":
            reason = r.get("reason", "unknown")
            retry_reasons[reason] += 1
            retry_prompts[(r.get("prompt_name"), reason)] += 1
            calls_with_retry.add(r.get("llm_id"))
        elif msg == "llm_call_fail":
            calls["failed_calls"] += 1
            if "attempt" in r:  # HTTP/transport error: no llm_retry was logged for this attempt
                http_fail += 1
    retries = sum(retry_reasons.values())
    attempts = calls["ok"] + retries + http_fail
    json_fail = retry_reasons["json_unmarshal"] + retry_reasons["json_validation"]
    failures = {
        "llm_calls": calls["calls"],
        "attempts": attempts,
        "failed_attempts": retries + http_fail,
        "json_unmarshal": retry_reasons["json_unmarshal"],
        "json_validation": retry_reasons["json_validation"],
        "semantic_validation": retry_reasons["validation"],
        "http_errors": http_fail,
        "calls_needing_retry": len(calls_with_retry),
        "calls_failed_permanently": calls["failed_calls"],
        "json_failure_rate": json_fail / attempts if attempts else 0,
        "any_failure_rate": (retries + http_fail) / attempts if attempts else 0,
        "calls_retried_rate": len(calls_with_retry) / calls["calls"] if calls["calls"] else 0,
    }
    return memories, failures, retry_prompts


def valence_stats(memories):
    by_persona = defaultdict(list)
    for m in memories:
        by_persona[m["persona"]].append(m["valence"])
    rows = {}
    for p, vs in sorted(by_persona.items()):
        rows[p] = vs
    rows["All agents"] = [m["valence"] for m in memories]
    out = {}
    for p, vs in rows.items():
        out[p] = {
            "n": len(vs),
            "mean": statistics.mean(vs) if vs else None,
            "sd": statistics.pstdev(vs) if len(vs) > 1 else 0.0,
            "min": min(vs) if vs else None,
            "max": max(vs) if vs else None,
            "negative": sum(v < 0 for v in vs),
        }
    return out


def rolling(xs, k=5):
    out = []
    for i in range(len(xs)):
        w = xs[max(0, i - k + 1): i + 1]
        out.append(sum(w) / len(w))
    return out


def plot(runs, t_from, t_until, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter, MultipleLocator

    personas = sorted({m["persona"] for _, mems, _ in runs for m in mems})
    fig, axes = plt.subplots(len(personas), 1, figsize=(9, 2.6 * len(personas) + 0.8), sharex=True, sharey=True)
    fig.patch.set_facecolor(SURFACE)
    if len(personas) == 1:
        axes = [axes]
    lo, hi = minutes(f"0000-00-00T{t_from}:00"), minutes(f"0000-00-00T{t_until}:00")
    offsets = [-0.12, 0.12]  # nudge the two models apart vertically so integer valences do not hide each other

    for ax, persona in zip(axes, personas):
        ax.set_facecolor(SURFACE)
        ax.axhline(0, color=AXIS, lw=1, zorder=1)
        ends = []
        for i, (label, mems, _) in enumerate(runs):
            pts = sorted((m["min"], m["valence"]) for m in mems if m["persona"] == persona)
            if not pts:
                continue
            xs, ys = zip(*pts)
            color = SERIES[i]
            ax.scatter(xs, [y + offsets[i] for y in ys], s=22, color=color, alpha=0.55,
                       edgecolors=SURFACE, linewidths=1, zorder=3)
            rm = rolling(list(ys))
            ax.plot(xs, rm, color=color, lw=2, zorder=4, solid_capstyle="round")
            ends.append([rm[-1], label.split(":")[0]])
        # Direct labels in a column right of the data; push apart when they would overlap.
        ends.sort()
        for j in range(1, len(ends)):
            if ends[j][0] - ends[j - 1][0] < 1.4:
                mid = (ends[j][0] + ends[j - 1][0]) / 2
                ends[j - 1][0], ends[j][0] = mid - 0.7, mid + 0.7
        for y, text in ends:
            ax.text(hi + 2, y, text, va="center", fontsize=8.5, color=INK_2)
        ax.set_title(persona, loc="left", fontsize=10.5, color=INK, pad=4)
        ax.set_ylim(-5.5, 5.5)
        ax.yaxis.set_major_locator(MultipleLocator(5))
        ax.yaxis.set_minor_locator(MultipleLocator(1))
        ax.grid(axis="y", which="major", color=GRID, lw=0.8)
        ax.tick_params(which="both", colors=MUTED, labelsize=8.5, length=0)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.set_xlim(lo, hi + 12)

    axes[-1].xaxis.set_major_locator(MultipleLocator(15))
    axes[-1].xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(v // 60):02d}:{int(v % 60):02d}"))
    axes[-1].set_xlabel("In-game time", color=MUTED, fontsize=9)
    fig.supylabel("Valence of new memory (−5 to +5)", color=MUTED, fontsize=9)
    handles = [plt.Line2D([], [], color=SERIES[i], lw=2, marker="o", markersize=5, label=label)
               for i, (label, _, _) in enumerate(runs)]
    fig.suptitle("Valence of each new memory over time (dots) with 5-memory rolling mean (line)",
                 x=0.01, y=0.995, ha="left", fontsize=11, color=INK)
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.005, 0.965), ncol=len(runs),
               frameon=False, fontsize=9, labelcolor=INK_2)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def pct(x):
    return f"{100 * x:.1f}%"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="append", required=True, help='"LABEL=simulation/<run folder>" (repeat)')
    ap.add_argument("--from", dest="t_from", default="00:00", help="first in-game time to include, HH:MM")
    ap.add_argument("--until", default="23:59", help="last in-game time to include, HH:MM")
    ap.add_argument("--plot", help="write the valence trajectory plot to this PNG")
    ap.add_argument("--markdown", help="write the report to this Markdown file")
    args = ap.parse_args()

    runs, report = [], []
    for spec in args.run:
        label, run_dir = spec.split("=", 1)
        log = latest_log(run_dir)
        mems, fails, prompts = analyse(log, args.t_from, args.until)
        runs.append((label, mems, fails))
        report.append((label, log, valence_stats(mems), fails, prompts))

    out = [f"# Model comparison ({args.t_from}–{args.until} in-game)", ""]
    for label, log, _, _, _ in report:
        out.append(f"- **{label}**: `{log}`")
    out += ["", "## Valence of new memories", "",
            "| Agent | " + " | ".join(f"{l} n | mean | SD | min–max | # negative" for l, *_ in report) + " |",
            "|---|" + "---|---|---|---|---|" * len(report)]
    agents = list(dict.fromkeys(a for _, _, vs, _, _ in report for a in vs))
    for a in agents:
        cells = []
        for _, _, vs, _, _ in report:
            s = vs.get(a)
            cells += ([str(s["n"]), f"{s['mean']:+.2f}", f"{s['sd']:.2f}", f"{s['min']}–{s['max']}", str(s["negative"])]
                      if s else ["–"] * 5)
        out.append(f"| {a} | " + " | ".join(cells) + " |")

    keys = [("llm_calls", "LLM calls"), ("attempts", "Attempts (incl. retries)"),
            ("json_unmarshal", "Unparseable JSON"), ("json_validation", "JSON schema violations"),
            ("semantic_validation", "Semantic validation failures"), ("http_errors", "HTTP errors"),
            ("failed_attempts", "Failed attempts (total)"), ("calls_needing_retry", "Calls needing ≥1 retry"),
            ("calls_failed_permanently", "Calls failed after all retries")]
    out += ["", "## LLM call failures", "", "| | " + " | ".join(l for l, *_ in report) + " |",
            "|---|" + "---|" * len(report)]
    for k, name in keys:
        out.append(f"| {name} | " + " | ".join(str(f[k]) for *_, f, _ in report) + " |")
    for k, name in [("json_failure_rate", "JSON failure rate (per attempt)"),
                    ("any_failure_rate", "Any failure rate (per attempt)"),
                    ("calls_retried_rate", "Share of calls needing a retry")]:
        out.append(f"| {name} | " + " | ".join(pct(f[k]) for *_, f, _ in report) + " |")

    out += ["", "## Failed attempts by prompt", ""]
    for label, _, _, _, prompts in report:
        out.append(f"**{label}**")
        out.append("")
        out += [f"- {p} ({reason}): {n}" for (p, reason), n in prompts.most_common(8)] or ["- none"]
        out.append("")

    text = "\n".join(out) + "\n"
    print(text)
    if args.plot:
        plot(runs, args.t_from, args.until, args.plot)
        print(f"(plot written to {args.plot})")
    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"(report written to {args.markdown})")


if __name__ == "__main__":
    main()
