#!/usr/bin/env bash
set -euo pipefail

OUT="${TMPDIR:-/tmp}/horizon_ai_news_precompute_latest.json"
python3 "$HOME/.hermes/scripts/horizon_ai_news_context.py" \
  --hours 36 \
  --horizon-timeout 660 \
  --rss-timeout 120 \
  > "$OUT"

python3 - "$OUT" <<'PY'
import json, pathlib, re, sys
p = pathlib.Path(sys.argv[1])
data = json.loads(p.read_text())
h = data.get('horizon', {})
r = data.get('rss', {})
run = h.get('run', {}) or {}
summary = h.get('summary_markdown') or ''
selected = None
m = re.search(r'From\s+(\d+)\s+items,\s+(\d+)\s+important', summary)
if m:
    selected = f"{m.group(2)}/{m.group(1)}"
print("✅ Horizon AI news precompute complete")
print(f"generated_at={data.get('generated_at')}")
print(f"github_auth={h.get('github_auth')}")
print(f"horizon_ok={run.get('ok')} timeout={run.get('timeout')} returncode={run.get('returncode')}")
print(f"horizon_selected={selected}")
print(f"summary_path={h.get('summary_path')}")
print(f"summary_date={h.get('summary_date')} stale={h.get('summary_is_stale')} age_days={h.get('summary_age_days')}")
if run.get('timeout') or not run.get('ok'):
    if run.get('stdout_tail'):
        print("--- horizon_stdout_tail ---")
        print(run.get('stdout_tail'))
    if run.get('stderr_tail'):
        print("--- horizon_stderr_tail ---")
        print(run.get('stderr_tail'))
print(f"rss_ok={r.get('run', {}).get('ok')}")
print(f"rss_counts={r.get('json', {}).get('counts')}")
PY
