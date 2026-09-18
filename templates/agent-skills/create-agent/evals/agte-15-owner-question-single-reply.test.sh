#!/usr/bin/env bash
# AGTE-15: https://app.hypertask.ai/detail/project-5500/15
#
# Reported incident: on a Done ticket, an owner asked a question with no
# @mention, and QA, Dev and Product Bot each posted an answer within
# minutes. The general answerer-selection order (mention, assignee, latest
# Done/Decision author, configured fallback) already shipped in 3.28.0 and
# adapter-default conf resolution predates this ticket. This file pins the
# exact reported shape end to end so it cannot silently regress:
#   - the question sits on a Done column ticket, not the "Review" column the
#     general answerer-selection eval uses
#   - none of the three agents is mentioned, assigned, or the latest
#     Done/Decision author, so the configured ANSWERER_FALLBACK decides
#   - `agent-template feedback --as product-bot` resolves the Hypertask
#     default conf directory without AGENT_CONFIG_DIR set by hand
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
pass=0
fail=0
ok() { printf 'PASS %-36s %s\n' "$1" "$2"; pass=$((pass + 1)); }
bad() { printf 'FAIL %-36s %s\n' "$1" "$2"; fail=$((fail + 1)); }

CONF_DIR="$TMP/home/.config/agents"
mkdir -p "$CONF_DIR" "$TMP/bin" "$TMP/company" "$TMP/repo" "$TMP/boards"
printf '# company pack\n' > "$TMP/company/INDEX.md"
printf 'test\n' > "$TMP/company/VERSION"
printf 'token\n' > "$TMP/token"

cat > "$TMP/bin/hypertask" <<'EOF'
#!/usr/bin/env bash
if [[ " $* " = *" comment add TEST-1 "* ]]; then
  printf '%s\n' "$*" >> "$BOARD_WRITE_LOG"
fi
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
  *'/mcp/tasks?'*) cat "$TASKS_JSON"; printf '\n200' ;;
  *'/mcp/comments?'*) cat "$COMMENTS_JSON"; printf '\n200' ;;
  *) printf '{}\n200' ;;
esac
EOF
chmod +x "$TMP/bin/"*

write_conf() {
  local slug="$1" id="$2" name="$3"
  cat > "$CONF_DIR/$slug.conf" <<EOF
AGENT_SLUG="$slug"
AGENT_ID="$id"
AGENT_NAME="$name"
AGENT_KIND="dev"
AGENT_REPO="$TMP/repo"
BOARD_ADAPTER="hypertask"
BOARD_ID="1"
TOKEN_FILE="$TMP/token"
BOARD_CLI="$TMP/boards/$slug"
WATCH_SECTIONS="*"
SKILLS_INDEX=""
MODEL_CLI="provider"
PR_REPO="example/repo"
TRIAGE="no"
CLAIM_UNASSIGNED="no"
ANSWERER_FALLBACK="product-bot"
EOF
}
write_conf qa1 agent-qa 'QA 1'
write_conf dev1 agent-dev 'Dev 1'
write_conf product-bot agent-pb 'Product Bot'

run_agent() {
  local slug="$1"
  HOME="$TMP/home" AGENT_CONFIG_DIR="$CONF_DIR" \
    XDG_STATE_HOME="$TMP/state/owner-question/$slug" COMPANY_SKILLS_DIR="$TMP/company" \
    TASKS_JSON="$TMP/tasks.json" COMMENTS_JSON="$TMP/comments.json" \
    BOARD_WRITE_LOG="$TMP/board-writes.log" \
    PATH="$TMP/bin:$PATH" "$ROOT/scripts/agent-board-poll" --once --dry-run --explain "$slug"
}

cat > "$TMP/tasks.json" <<'EOF'
{"tasks":[{"id":"task-1","ticketNumber":"TEST-1","section":"Done","title":"Owner question","description":"Ship the flag","assignees":[],"labels":[],"commentCount":1,"updatedAt":"2026-09-17T14:41:00Z"}]}
EOF
cat > "$TMP/comments.json" <<'EOF'
{"comments":[{"id":30,"createdAt":"2026-09-17T14:41:00Z","agent":null,"creator":{"displayName":"Owner"},"text":"<p>is that a feature flag?</p>"}]}
EOF

reply_count=0
winner=""
for slug in qa1 dev1 product-bot; do
  output="$(run_agent "$slug")"
  printf '%s\n' "$output" > "$TMP/$slug.out"
  if printf '%s\n' "$output" | grep -q '^    reply-only:'; then
    reply_count=$((reply_count + 1))
    winner="$slug"
  fi
done
if [ "$reply_count" -eq 1 ] && [ "$winner" = "product-bot" ] \
   && grep -qF 'owns question 30 by fallback' "$TMP/product-bot.out"; then
  ok done-column-unmentioned-question 'only product-bot answers an unmentioned owner question on a Done ticket'
else
  bad done-column-unmentioned-question "reply-only count=$reply_count winner=${winner:-none}; outputs=$TMP/*.out"
fi

# Second half of AGTE-15: `feedback --as product-bot` must resolve the
# Hypertask default conf directory (~/.config/hypertask-agents) on its own,
# the way it is actually invoked from a plain shell, not the generic
# ~/.config/agents dir this file uses for the answerer-selection check above.
FEEDBACK_HOME="$TMP/feedback-home"
FEEDBACK_CONF_DIR="$FEEDBACK_HOME/.config/hypertask-agents"
mkdir -p "$FEEDBACK_CONF_DIR" "$TMP/feedback-bin"
printf 'token\n' > "$TMP/feedback-token"
cat > "$FEEDBACK_CONF_DIR/product-bot.conf" <<EOF
AGENT_SLUG="product-bot"
AGENT_NAME="Product Bot"
AGENT_KIND="worker"
AGENT_ID="agent-pb"
BOARD_ADAPTER="hypertask"
BOARD_ID="5500"
TOKEN_FILE="$TMP/feedback-token"
BOARD_CLI="$TMP/feedback-bin/board"
MODEL_CLI="provider"
MANAGER="on"
MAINTAINER="on"
EOF
cat > "$TMP/feedback-bin/board" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  task\ create*) printf '%s\n' '{"task":{"id":"task-201","ticketNumber":"AGTE-201","projectId":5500,"uniqueIndex":201}}' ;;
esac
EOF
chmod +x "$TMP/feedback-bin/board"

feedback_output="$(env -u AGENT_CONFIG_DIR AGENT_SLUG="product-bot" HOME="$FEEDBACK_HOME" \
  XDG_STATE_HOME="$TMP/feedback-state" PATH="$TMP/feedback-bin:$PATH" \
  "$ROOT/scripts/agent-template" feedback --as product-bot --kind bug \
  --what 'Three agents answered the same owner question' \
  --got 'QA 1, Dev 1 and Product Bot each replied' \
  --expected 'exactly one agent replies')"
if printf '%s\n' "$feedback_output" | grep -q '^filed AGTE-201 '; then
  ok feedback-as-product-bot-no-env 'feedback --as product-bot resolves ~/.config/hypertask-agents without AGENT_CONFIG_DIR'
else
  bad feedback-as-product-bot-no-env "output=$feedback_output"
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
