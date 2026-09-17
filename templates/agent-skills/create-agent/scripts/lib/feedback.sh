#!/usr/bin/env bash
# Shared feedback discovery text and managed host/project note writer.

FEEDBACK_BOARD_URL="${FEEDBACK_BOARD_URL:-https://app.hypertask.ai/detail/project-5500}"
FEEDBACK_COMMAND='agent-template feedback --kind bug|change|idea --what "<summary>" --got "<current behavior or context>" --expected "<desired behavior>"'

feedback_print_discovery() {
  printf '%s\n' \
    'Toolkit feedback:' \
    "  bugs, change requests and ideas go to $FEEDBACK_BOARD_URL" \
    "  via \`$FEEDBACK_COMMAND\`"
}

feedback_managed_block() {
  local version="$1"
  cat <<EOF
<!-- agent-template:begin -->
Agent template version: $version
Feedback command: \`$FEEDBACK_COMMAND\`
Feedback board: $FEEDBACK_BOARD_URL
Updates: run \`agent-template update\` to get the latest.
<!-- agent-template:end -->
EOF
}

feedback_update_note() { # feedback_update_note <path> <version> <create yes|no>
  local path="$1" version="$2" create="${3:-no}" block
  if [ ! -f "$path" ] && [ "$create" != "yes" ]; then
    return 2
  fi
  mkdir -p "$(dirname "$path")"
  block="$(feedback_managed_block "$version")"
  BLOCK="$block" python3 - "$path" <<'PYEOF'
import os
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
begin = b"<!-- agent-template:begin -->"
end = b"<!-- agent-template:end -->"
block = os.environ["BLOCK"].encode() + b"\n"
data = path.read_bytes() if path.exists() else b""
start = data.find(begin)
if start >= 0:
    finish = data.find(end, start + len(begin))
    if finish < 0:
        raise SystemExit("managed feedback block has a begin marker but no end marker in %s" % path)
    finish += len(end)
    if data[finish:finish + 2] == b"\r\n":
        finish += 2
    elif data[finish:finish + 1] == b"\n":
        finish += 1
    updated = data[:start] + block + data[finish:]
else:
    separator = b"" if not data or data.endswith((b"\n", b"\r")) else b"\n"
    updated = data + separator + block
if updated != data:
    path.write_bytes(updated)
PYEOF
}

feedback_update_host_notes() { # feedback_update_host_notes <version> <skip yes|no>
  local version="$1" skip="${2:-no}" claude="$HOME/.claude/CLAUDE.md" codex="$HOME/.codex/AGENTS.md"
  if [ "$skip" = "yes" ]; then
    echo "host notes: skipped (--no-host-notes)"
    return 0
  fi
  feedback_update_note "$claude" "$version" yes
  echo "host note: $claude"
  if [ -f "$codex" ]; then
    feedback_update_note "$codex" "$version" no
    echo "host note: $codex"
  fi
}

# AGTE-12: a comment that judges a ticket for a human (need_info question,
# decline decision) must pass the same pospeak/unslop/i-have-adhd shape the
# board wrapper already enforces, so Valentin never sees a raw model draft.
# The rewrite prompt itself is not duplicated here: outbound-text-gate.sh's
# own _rewrite_plain_comment (the board wrapper's copy) is sourced and reused,
# so the verbatim rule text has exactly one home.
feedback_gate_human_comment() { # feedback_gate_human_comment <plain-language-dir> <cli> <draft>
  local dir="$1" cli="$2" draft="$3" reasons rewritten final_reasons
  local check="$dir/check-comment.py"
  [ -r "$check" ] || { printf '%s' "$draft"; return 0; }
  if reasons="$(printf '%s' "$draft" | python3 "$check" 2>&1)"; then
    printf '%s' "$draft"
    return 0
  fi
  final_reasons="$reasons"
  # shellcheck disable=SC1091
  . "$dir/outbound-text-gate.sh"
  POSPEAK_SKILL="$dir/pospeak.md"
  UNSLOP_SKILL="$dir/unslop.md"
  ADHD_SKILL="$dir/i-have-adhd.md"
  if rewritten="$(AGENT_COMMENT_REWRITE_CLI="$cli" _rewrite_plain_comment "$draft" "$reasons")" \
      && final_reasons="$(printf '%s' "$rewritten" | python3 "$check" 2>&1)"; then
    printf '%s' "$rewritten"
    return 0
  fi
  printf 'plain-language-held: draft follows\n%s\nplain-language-held: reasons follow\n%s\n' \
    "$draft" "$final_reasons" >&2
  return 1
}
