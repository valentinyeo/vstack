#!/usr/bin/env bash
# Product bug-triage checks use a fixture board and a recording CLI only.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TRIAGE="$ROOT/scripts/bug-triage.py"
FIXTURE="$(dirname "$0")/fixtures/bug-triage-board.json"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
LOG="$TMP/board-writes.jsonl"
STATE="$TMP/state.json"

cat > "$TMP/board" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
python3 - "$BOARD_WRITE_LOG" "$@" <<'PYEOF'
import json, sys
with open(sys.argv[1], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[2:]) + "\n")
PYEOF
EOF
chmod +x "$TMP/board"

ok() { printf 'PASS %-34s %s\n' "$1" "$2"; }
bad() { printf 'FAIL %-34s %s\n' "$1" "$2" >&2; exit 1; }

run_triage() {
  BOARD_WRITE_LOG="$LOG" python3 "$TRIAGE" --board 42 --input "$FIXTURE" \
    --state "$STATE" --board-cli "$TMP/board" --agent-id agent-product --now "$1"
}

first="$(run_triage 2026-09-18T12:00:00Z)"
if OUTPUT="$first" LOG="$LOG" python3 <<'PYEOF'
import json, os
rows = [json.loads(line) for line in open(os.environ["LOG"], encoding="utf-8")]
result = json.loads(os.environ["OUTPUT"].splitlines()[-1])
assert result["ranked"][:4] == ["BUG-3", "BUG-2", "BUG-7", "BUG-4"]
priority = [row for row in rows if row[:2] == ["task", "update"] and "--priority" in row]
assert [row[2] for row in priority] == ["BUG-3", "BUG-7", "BUG-4", "BUG-6"]
assert [row[-1] for row in priority] == ["Urgent", "High", "High", "Low"]
assert not any("BUG-9" in row or "BUG-10" in row for row in rows)
PYEOF
then
  ok priorities-and-order 'due dates and owner Urgent lead the scored queue; protected tickets are untouched'
else
  bad priorities-and-order "output=$first writes=$(cat "$LOG")"
fi

if LOG="$LOG" python3 <<'PYEOF'
import json, os
rows = [json.loads(line) for line in open(os.environ["LOG"], encoding="utf-8")]
assert ["task", "link", "BUG-8", "BUG-7", "--type", "duplicate"] in rows
assert ["task", "update", "BUG-8", "--status", "Archive"] in rows
body = next(row[-1] for row in rows if row[:3] == ["comment", "add", "BUG-8"])
assert "BUG-7" in body and "https://app.hypertask.ai/detail/project-42/7" in body
PYEOF
then
  ok duplicate-merge 'the newer duplicate links to the older ticket and is archived'
else
  bad duplicate-merge "writes=$(cat "$LOG")"
fi

if LOG="$LOG" CHECK="$ROOT/adapters/hypertask/plain-language/check-comment.py" python3 <<'PYEOF'
import json, os, re, subprocess
rows = [json.loads(line) for line in open(os.environ["LOG"], encoding="utf-8")]
comments = [row[-1] for row in rows if row[:2] == ["comment", "add"]]
question = [row[-1] for row in rows if row[:3] == ["comment", "add", "BUG-6"]]
summary = [row[-1] for row in rows if row[:3] == ["comment", "add", "BUG-1"]]
assert len(question) == 1 and question[0].count("Question:") == 1
assert len(summary) == 1 and summary[0].count("Question:") <= 1
assert "Top five:" in summary[0] and "Moved:" in summary[0]
assert len(re.sub(r"<[^>]+>", " ", summary[0]).split()) <= 80
assert all(subprocess.run(["python3", os.environ["CHECK"]], input=body, text=True).returncode == 0 for body in comments)
PYEOF
then
  ok questions-and-summary 'one clarification and one compact daily top-five summary are posted'
else
  bad questions-and-summary "writes=$(cat "$LOG")"
fi

before="$(wc -l < "$LOG")"
second="$(run_triage 2026-09-18T14:00:00Z)"
after="$(wc -l < "$LOG")"
if [ "$before" = "$after" ] && [[ "$second" == *'four-hour interval'* ]]; then
  ok four-hour-cadence 'a tick inside four hours performs no board writes'
else
  bad four-hour-cadence "before=$before after=$after output=$second"
fi

run_triage 2026-09-18T16:00:00Z >/dev/null
summary_count="$(LOG="$LOG" python3 - <<'PYEOF'
import json, os
rows = [json.loads(line) for line in open(os.environ["LOG"], encoding="utf-8")]
print(sum(row[:3] == ["comment", "add", "BUG-1"] for row in rows))
PYEOF
)"
question_count="$(LOG="$LOG" python3 - <<'PYEOF'
import json, os
rows = [json.loads(line) for line in open(os.environ["LOG"], encoding="utf-8")]
print(sum(row[:3] == ["comment", "add", "BUG-6"] for row in rows))
PYEOF
)"
if [ "$summary_count" = 1 ] && [ "$question_count" = 1 ]; then
  ok daily-deduplication 'later four-hour runs do not repeat the daily summary or clarification'
else
  bad daily-deduplication "summaries=$summary_count questions=$question_count"
fi
