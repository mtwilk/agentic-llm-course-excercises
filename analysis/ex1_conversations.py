"""Exercise 1: extract and summarise an agent's conversations from simulation runs.

Reads each run's memory files
    simulation/<run>/personas/<name>/bootstrap_memory/associative_memory/nodes.json
Chat memories (type "chat") hold the full dialogue as [speaker, utterance] pairs.
Each conversation is stored once per participant, with that participant's own
valence rating (-5 very negative ... +5 very positive), so the script merges
the copies and reports how each side rated it.

Usage (from the repository root):
    python analysis/ex1_conversations.py simulation/ex1_bernard_v1 simulation/ex1_bernard_v2 simulation/ex1_bernard_v3
    python analysis/ex1_conversations.py simulation/ex1_bernard_v1 --markdown out.md
Options:
    --persona NAME    agent to focus on (default: "Bernard Lowe")
    --until HH:MM     ignore memories created after this in-game time (e.g. 08:30)
    --markdown FILE   also write the full report as Markdown
"""
import argparse
import json
import os
import statistics
from collections import defaultdict


def load_nodes(run_dir):
    """Return {persona_name: [node, ...]} for one run folder."""
    personas_dir = os.path.join(run_dir, "personas")
    out = {}
    for name in sorted(os.listdir(personas_dir)):
        path = os.path.join(personas_dir, name, "bootstrap_memory", "associative_memory", "nodes.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                out[name] = list(json.load(f).values())
    return out


def load_scratch(run_dir, persona):
    path = os.path.join(run_dir, "personas", persona, "bootstrap_memory", "scratch.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def collect_conversations(nodes_by_persona, persona, until=None):
    """Merge the per-participant copies of every conversation involving `persona`."""
    convs = {}
    for owner, nodes in nodes_by_persona.items():
        for n in nodes:
            if n.get("type") != "chat":
                continue
            if until and n["created"][11:16] > until:
                continue
            lines = [tuple(u) for u in n.get("filling") or []]
            speakers = {s for s, _ in lines} | {n["subject"], n["object"]}
            if persona not in speakers:
                continue
            key = (n["created"][:16], frozenset(speakers), lines[0] if lines else None)
            c = convs.setdefault(key, {
                "created": n["created"],
                "participants": sorted(speakers),
                "lines": lines,
                "summaries": {},
                "valence": {},
                "importance": {},
            })
            c["summaries"][owner] = n.get("description", "")
            c["valence"][owner] = n.get("valence")
            c["importance"][owner] = n.get("poignancy")
    return sorted(convs.values(), key=lambda c: c["created"])


def persona_memories(nodes_by_persona, persona, kind, until=None):
    return [n for n in nodes_by_persona.get(persona, [])
            if n.get("type") == kind and not (until and n["created"][11:16] > until)]


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 2) if xs else None


def summarise(run_dir, persona, until):
    nodes = load_nodes(run_dir)
    convs = collect_conversations(nodes, persona, until)
    scratch = load_scratch(run_dir, persona)
    others = [p for p in nodes if p != persona]

    own_lines = [u for c in convs for s, u in c["lines"] if s == persona]
    stats = {
        "run": os.path.basename(os.path.normpath(run_dir)),
        "conversations": len(convs),
        "utterances_by_persona": len(own_lines),
        "avg_words_per_utterance": round(statistics.mean(len(u.split()) for u in own_lines), 1) if own_lines else None,
        "mean_valence_by_persona": mean(c["valence"].get(persona) for c in convs),
    }
    for o in others:
        stats[f"mean_valence_by_{o.split()[0]}"] = mean(c["valence"].get(o) for c in convs if o in c["valence"])
    stats["mean_valence_all_events_seen_by_persona"] = mean(n.get("valence") for n in persona_memories(nodes, persona, "event", until))

    thoughts = persona_memories(nodes, persona, "thought", until)
    return scratch, convs, stats, thoughts


def render(run_dir, persona, scratch, convs, stats, thoughts):
    out = [f"# {stats['run']}", "",
           f"**innate:** {scratch.get('innate', '')}", "",
           f"**learned:** {scratch.get('learned', '')}", "",
           "## Summary", ""]
    out += [f"- {k}: {v}" for k, v in stats.items() if k != "run"]
    out += ["", f"## Conversations involving {persona} ({len(convs)})", ""]
    for i, c in enumerate(convs, 1):
        val = ", ".join(f"{p.split()[0]} {v:+d}" for p, v in c["valence"].items() if v is not None)
        summary = c["summaries"].get(persona) or next(iter(c["summaries"].values()), "")
        out += [f"### {i}. {c['created'][11:16]} | {' & '.join(c['participants'])}",
                f"*Summary:* {summary}  ", f"*Valence:* {val}", ""]
        out += [f"> **{s.split()[0]}:** {u}  " for s, u in c["lines"]]
        out.append("")
    out += [f"## {persona}'s thoughts ({len(thoughts)})", ""]
    out += [f"- {t['created'][11:16]} (valence {t.get('valence')}): {t.get('description', '')}" for t in thoughts]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", help="run folders, e.g. simulation/ex1_bernard_v1")
    ap.add_argument("--persona", default="Bernard Lowe")
    ap.add_argument("--until", help="ignore memories after this in-game time, HH:MM")
    ap.add_argument("--markdown", help="write the full report to this Markdown file")
    args = ap.parse_args()

    reports, table = [], []
    for run in args.runs:
        scratch, convs, stats, thoughts = summarise(run, args.persona, args.until)
        reports.append(render(run, args.persona, scratch, convs, stats, thoughts))
        table.append(stats)

    full = "\n---\n\n".join(reports)
    if len(table) > 1:
        keys = list(dict.fromkeys(k for s in table for k in s))
        cmp_ = ["# Comparison", "", "| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
        cmp_ += ["| " + " | ".join(str(s.get(k, "")) for k in keys) + " |" for s in table]
        full = "\n".join(cmp_) + "\n\n---\n\n" + full

    print(full)
    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as f:
            f.write(full)
        print(f"(written to {args.markdown})")


if __name__ == "__main__":
    main()
