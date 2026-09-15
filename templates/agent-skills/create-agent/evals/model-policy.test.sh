#!/usr/bin/env bash
# Behavioural checks for provider-aware model routing. Everything is local:
# fake board reads and fake model CLIs make it impossible for an eval to spend.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
pass=0
fail=0
ok() { printf 'PASS %-34s %s\n' "$1" "$2"; pass=$((pass + 1)); }
bad() { printf 'FAIL %-34s %s\n' "$1" "$2"; fail=$((fail + 1)); }

mkdir -p "$TMP/home/.config/agents" "$TMP/company" "$TMP/repo" "$TMP/bin"
printf '# company pack\n' > "$TMP/company/INDEX.md"
printf 'test\n' > "$TMP/company/VERSION"
printf 'token\n' > "$TMP/token"

cat > "$TMP/board" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat > "$TMP/bin/hypertask" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat > "$TMP/bin/gh" <<'EOF'
#!/usr/bin/env bash
printf '[]\n'
EOF
cat > "$TMP/bin/curl" <<'EOF'
#!/usr/bin/env bash
url="${!#}"
case "$url" in
  *'/mcp/tasks?'*) cat "$BOARD_JSON"; printf '\n200' ;;
  *'/mcp/comments?'*) printf '%s\n200' '{"comments":[]}' ;;
  *) printf '%s\n200' '{}' ;;
esac
EOF
for model_cli in cursor-agent claude; do
  cat > "$TMP/bin/$model_cli" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MODEL_CAPTURE"
EOF
done
chmod +x "$TMP/board" "$TMP/bin/"*

write_board() {
  local ref="$1" labels="$2"
  cat > "$TMP/board.json" <<EOF
{"tasks":[{"id":"task-$ref","ticketNumber":"$ref","section":"Bugs","title":"Model policy test","description":"Exercise provider routing","assignees":[{"agent":{"id":"agent-1"}}],"labels":$labels,"commentCount":0}]}
EOF
}

write_conf() {
  local model_cli="$1" triage="$2" state="$3"
  mkdir -p "$state/overrides"
  cat > "$TMP/home/.config/agents/test.conf" <<EOF
AGENT_ID="agent-1"
AGENT_NAME="Test Dev"
AGENT_KIND="dev"
AGENT_REPO="$TMP/repo"
BOARD_ADAPTER="hypertask"
BOARD_ID="1"
TOKEN_FILE="$TMP/token"
BOARD_CLI="$TMP/board"
WATCH_SECTIONS="Bugs"
SKILLS_INDEX=""
MODEL_CLI="$model_cli"
PR_REPO="example/repo"
TRIAGE="$triage"
MODEL_OVERRIDE_DIR="$state/overrides"
EOF
}

run_poll() {
  local state="$1" capture="$2"; shift 2
  env HOME="$TMP/home" AGENT_CONFIG_DIR="$TMP/home/.config/agents" \
    XDG_STATE_HOME="$state" COMPANY_SKILLS_DIR="$TMP/company" \
    BOARD_JSON="$TMP/board.json" MODEL_CAPTURE="$capture" \
    PATH="$TMP/bin:$PATH" "$ROOT/scripts/agent-board-poll" "$@" test
}

# A hard ticket must visibly switch away from a Cursor default before spending.
state="$TMP/state-hard"; capture="$TMP/capture-hard"
write_board TEST-1 '[{"name":"hard"}]'
write_conf 'cursor-agent -p --output-format text --model cursor-grok-4.6-high-fast -f --trust' yes "$state"
dry_out="$(run_poll "$state" "$capture" --once --dry-run 2>"$TMP/hard.err")"
if grep -qF 'would run on provider claude, model opus (effort high)' <<< "$dry_out"; then
  ok hard-cursor-switches-provider "dry run selects claude:opus with high effort"
else
  bad hard-cursor-switches-provider "dry run did not show provider claude: $dry_out"
fi

# A bad conf is loud once and can launch only the Cursor policy default.
state="$TMP/state-conf"; capture="$TMP/capture-conf"
write_board TEST-2 '[]'
write_conf 'cursor-agent -p --output-format text --model claude-opus-5-thinking-high -f --trust' no "$state"
run_poll "$state" "$capture" --once >"$TMP/conf.out" 2>"$TMP/conf.err" || true
if [ "$(grep -c "model policy rejected 'cursor-agent:claude-opus-5-thinking-high' from conf" "$TMP/conf.err" || true)" -eq 1 ] \
   && grep -qF -- '--model cursor-grok-4.6-high-fast' "$capture" \
   && ! grep -qF -- '--model claude-' "$capture"; then
  ok cursor-claude-conf-rejected "one error; launch falls back to Cursor Grok"
else
  bad cursor-claude-conf-rejected "stderr=$(cat "$TMP/conf.err"); launch=$(cat "$capture" 2>/dev/null || true)"
fi

# A provider-qualified bad override is rejected, logged, and never launched.
state="$TMP/state-override"; capture="$TMP/capture-override"
write_board TEST-3 '[]'
write_conf 'cursor-agent -p --output-format text --model cursor-grok-4.6-high-fast -f --trust' no "$state"
printf 'cursor-agent:claude-opus-5-thinking-high\n' > "$state/overrides/TEST-3"
run_poll "$state" "$capture" --once >"$TMP/override.out" 2>"$TMP/override.err" || true
log="$state/agent-board-poll/test.log"
if grep -qF "model policy rejected 'cursor-agent:claude-opus-5-thinking-high' from override" "$TMP/override.err" \
   && grep -qF "model policy rejected 'cursor-agent:claude-opus-5-thinking-high' from override" "$log" \
   && grep -qF -- '--model cursor-grok-4.6-high-fast' "$capture" \
   && ! grep -qF -- '--model claude-' "$capture"; then
  ok cursor-claude-override-rejected "rejected, logged, and launch stays on Cursor Grok"
else
  bad cursor-claude-override-rejected "stderr=$(cat "$TMP/override.err"); log=$(cat "$log" 2>/dev/null || true)"
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
