"""Live terminal view of the MMLU utility-panel repeat collection.

Read-only: parses the append-only slot journals and panel manifest, never
writes into the collection directory. A torn trailing line (writer mid-append)
is ignored rather than parsed. Terminal: `python -m router_v2.watch_utility_panel`
or with `--interval 30` for a self-clearing loop. `--http PORT` serves one
self-refreshing HTML table instead of stdout.
"""
import argparse
import html
import json
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL_DIR = ROOT / "router_v2/mmlu_utility_panel_400"
REPEAT_DIR = ROOT / "data/mmlu_utility_repeats_400"


def read_records(path):
    """Parse complete lines only; drop a torn trailing write."""
    if not path.exists():
        return []
    raw = path.read_bytes()
    cut = raw.rfind(b"\n") + 1
    rows = []
    for line in raw[:cut].split(b"\n"):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def is_valid(r):
    return r.get("status") in ("ok", "truncated", "parse_failed") and not r.get("error")


def load_json_safe(path, fallback):
    """Collector rewrites status files non-atomically; tolerate mid-write reads."""
    for _ in range(3):
        try:
            return json.loads(path.read_text())
        except (ValueError, OSError):
            time.sleep(0.05)
    return fallback


def snapshot(panel_dir, repeat_dir):
    manifest = json.loads((panel_dir / "MANIFEST.json").read_text())
    repeats = manifest["repeats"]
    panel_ids = {json.loads(l)["query_id"] for l in (panel_dir / "PANEL.jsonl").read_text().split("\n") if l.strip()}
    slots, failures, last_ts = {}, [], 0.0
    for slot in manifest["slots"]:
        rows = [r for r in read_records(repeat_dir / f"{slot}.jsonl") if r.get("query_id") in panel_ids]
        valid = {}
        for r in rows:
            if is_valid(r):
                valid.setdefault((r["query_id"], int(r["repeat_index"])), r)
        failed_rows = [r for r in rows if not is_valid(r)]
        if rows:
            last_ts = max(last_ts, max(r.get("ts", 0) for r in rows))
        status_path = repeat_dir / f"{slot}_STATUS.json"
        collector = load_json_safe(status_path, {})
        recent = [r["ts"] for k, r in valid.items() if last_ts - r.get("ts", 0) <= 900]
        running = collector.get("phase") != "FINISHED"
        rate = len(recent) / 15.0 if recent and running else 0.0
        remaining = repeats * len(panel_ids) - len(valid)
        slots[slot] = dict(
            valid=len(valid), target=repeats * len(panel_ids),
            failed_rows=len(failed_rows),
            queries_complete=len({qid for qid, _ in valid}),
            rate_per_min=round(rate, 1) if running else None,
            eta_min=round(remaining / rate) if rate > 0 else None,
            phase=collector.get("phase", "?"),
            consecutive_errors=collector.get("consecutive_errors"),
            mtime=time.strftime("%H:%M:%S", time.localtime((repeat_dir / f"{slot}.jsonl").stat().st_mtime))
            if (repeat_dir / f"{slot}.jsonl").exists() else "-",
        )
        failures.extend((slot, r) for r in failed_rows[-5:])
    complete_pairs = 0
    by_query = {s: {} for s in slots}
    for slot in slots:
        for path_r in read_records(repeat_dir / f"{slot}.jsonl"):
            if is_valid(path_r) and path_r.get("query_id") in panel_ids:
                by_query[slot].setdefault((path_r["query_id"], int(path_r["repeat_index"])), 1)
    for qid in panel_ids:
        if all(sum(1 for (q, _i) in by_query[s] if q == qid) >= repeats for s in slots):
            complete_pairs += 1
    p1 = panel_dir / "P1_PIPELINE_STATUS.json"
    pipeline = load_json_safe(p1, {}).get("phase", "-") if p1.exists() else "-"
    return dict(
        n_panel=len(panel_ids), repeats=repeats, slots=slots,
        complete_pairs=complete_pairs, pipeline=pipeline,
        last_record=time.strftime("%H:%M:%S", time.localtime(last_ts)) if last_ts else "-",
        failures=[dict(slot=s, query_id=r.get("query_id"), repeat=r.get("repeat_index"),
                       status=r.get("status"), error=(r.get("error") or "")[:80]) for s, r in failures[-6:]],
        now=time.strftime("%H:%M:%S"),
    )


def render_text(s):
    lines = [f"MMLU utility panel 400  |  {s['now']}  |  repeats={s['repeats']}  |  pipeline={s['pipeline']}",
             ""]
    header = f"{'slot':10} {'valid/target':>13} {'queries':>9} {'failed':>7} {'rate/min':>9} {'eta':>9} {'phase':>9} {'err':>4} {'last write':>11}"
    lines.append(header)
    lines.append("-" * len(header))
    for slot, v in s["slots"].items():
        eta = f"{v['eta_min']}m" if v["eta_min"] is not None else "-"
        rate = f"{v['rate_per_min']}" if v["rate_per_min"] is not None else "-"
        lines.append(f"{slot:10} {v['valid']:>6}/{v['target']:<6} {v['queries_complete']:>9} {v['failed_rows']:>7} "
                     f"{rate:>9} {eta:>9} {v['phase']:>9} {v['consecutive_errors'] if v['consecutive_errors'] is not None else '-':>4} {v['mtime']:>11}")
    lines.append("")
    lines.append(f"complete pairs (both slots x {s['repeats']}): {s['complete_pairs']}/{s['n_panel']}")
    lines.append(f"last record ts: {s['last_record']}")
    if s["failures"]:
        lines.append("recent failures:")
        for f in s["failures"]:
            lines.append(f"  [{f['slot']}] {f['query_id']} r{f['repeat']} {f['status']}: {f['error']}")
    else:
        lines.append("recent failures: none")
    return "\n".join(lines)


def render_html(s):
    rows = "".join(
        f"<tr><td>{k}</td><td>{v['valid']}/{v['target']}</td><td>{v['queries_complete']}</td>"
        f"<td>{v['failed_rows']}</td><td>{'-' if v['rate_per_min'] is None else v['rate_per_min']}</td>"
        f"<td>{'-' if v['eta_min'] is None else str(v['eta_min']) + 'm'}</td><td>{v['phase']}</td>"
        f"<td>{v['consecutive_errors']}</td><td>{v['mtime']}</td></tr>"
        for k, v in s["slots"].items())
    fails = "".join(f"<tr><td>{html.escape(f['slot'])}</td><td>{f['query_id']}</td><td>r{f['repeat']}</td>"
                    f"<td>{html.escape(str(f['status']))}</td><td>{html.escape(f['error'] or '')}</td></tr>"
                    for f in s["failures"]) or "<tr><td colspan=5>none</td></tr>"
    return f"""<!doctype html><html><head><meta charset=utf-8><meta http-equiv=refresh content=15>
<title>utility panel 400</title><style>body{{font-family:monospace;margin:2em;background:#111;color:#ddd}}
table{{border-collapse:collapse;margin:1em 0}}td,th{{border:1px solid #444;padding:4px 12px;text-align:right}}
td:first-child,th:first-child{{text-align:left}}</style></head><body>
<h2>MMLU utility panel 400 — {s['now']} (auto 15s)</h2>
<table><tr><th>slot</th><th>valid/target</th><th>queries</th><th>failed</th><th>rate/min</th><th>eta</th><th>phase</th><th>err</th><th>last write</th></tr>{rows}</table>
<p>complete pairs (both slots × {s['repeats']}): <b>{s['complete_pairs']}/{s['n_panel']}</b> · pipeline: {s['pipeline']} · last record: {s['last_record']}</p>
<table><tr><th>slot</th><th>query</th><th>rep</th><th>status</th><th>error</th></tr>{fails}</table>
</body></html>"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--panel-dir", default=str(PANEL_DIR))
    ap.add_argument("--repeat-dir", default=str(REPEAT_DIR))
    ap.add_argument("--interval", type=int, default=0, help="refresh seconds; 0 prints once")
    ap.add_argument("--http", type=int, default=0, help="serve the page on this port instead of stdout")
    args = ap.parse_args()
    panel_dir, repeat_dir = Path(args.panel_dir), Path(args.repeat_dir)
    if args.http:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = render_html(snapshot(panel_dir, repeat_dir)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        ThreadingHTTPServer(("0.0.0.0", args.http), Handler).serve_forever()
    while True:
        out = render_text(snapshot(panel_dir, repeat_dir))
        print("\033[2J\033[H" + out if args.interval else out, flush=True)
        if not args.interval:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
