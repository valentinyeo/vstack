#!/usr/bin/env bash
# AGTE-12: need_info and decline comments in agent-template-feedback are a
# judgment call read by Valentin, so they must pass the same
# pospeak/unslop/i-have-adhd shape the board wrapper already enforces on
# Question and Decision comments, with a rewrite pass before a hold.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
PLAIN_LANGUAGE_DIR="$ROOT/adapters/hypertask/plain-language"
# shellcheck disable=SC1091
. "$ROOT/scripts/lib/feedback.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fails=0
ok() { printf 'PASS %-34s %s\n' "$1" "$2"; }
bad() { printf 'FAIL %-34s %s\n' "$1" "$2"; fails=$((fails + 1)); }

# A draft that already clears the mechanical check posts byte-for-byte.
CLEAN="<p><strong>Need info: the report is missing a reproducible case.</strong></p><p>Can you share one?</p>"
out="$(feedback_gate_human_comment "$PLAIN_LANGUAGE_DIR" "" "$CLEAN" 2>/dev/null)"
if [ "$out" = "$CLEAN" ]; then
  ok clean-draft-passthrough 'a draft that already passes the check is posted unchanged'
else
  bad clean-draft-passthrough "expected unchanged draft, got: $out"
fi

# A draft that fails (no leading bold sentence, no closing question or Next:)
# and has no rewrite CLI configured is held, not posted.
DIRTY="<p>this ticket references src/adapter.sh and ends flat</p>"
if out="$(feedback_gate_human_comment "$PLAIN_LANGUAGE_DIR" "" "$DIRTY" 2>"$TMP/reasons")"; then
  bad dirty-draft-held-without-cli "expected a failure, got output: $out"
else
  if grep -q 'plain-language-held' "$TMP/reasons"; then
    ok dirty-draft-held-without-cli 'no rewrite CLI: draft and reasons are logged, nothing is returned to post'
  else
    bad dirty-draft-held-without-cli 'held failure did not log the draft and reasons'
  fi
fi

# A stub rewrite CLI that returns a compliant draft is used and re-checked.
STUB="$TMP/stub-cli"
cat > "$STUB" <<'EOF'
#!/usr/bin/env bash
printf '<p><strong>Fixed: the draft now reads plainly.</strong></p><p>Next: nothing else needed.</p>'
EOF
chmod +x "$STUB"
out="$(feedback_gate_human_comment "$PLAIN_LANGUAGE_DIR" "$STUB" "$DIRTY" 2>/dev/null)"
if printf '%s' "$out" | grep -qF 'Fixed: the draft now reads plainly.'; then
  ok rewrite-cli-used 'a configured rewrite CLI replaces a draft that fails the mechanical check'
else
  bad rewrite-cli-used "expected the rewritten draft, got: $out"
fi

# The rewrite prompt carries the pospeak rule text verbatim (not a paraphrase
# or a second copy), because the gate sources outbound-text-gate.sh's own
# rewrite function instead of keeping its own prompt.
CAPTURE="$TMP/capture.txt"
CAPTURE_STUB="$TMP/capture-stub"
CAPTURE="$CAPTURE" python3 - "$CAPTURE_STUB" <<'PYEOF'
import os
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
path.write_text(
    "#!/usr/bin/env bash\n"
    "cat > \"%s\" <<< \"$1\"\n"
    "printf '<p><strong>Fixed: the draft now reads plainly.</strong></p><p>Next: nothing else needed.</p>'\n"
    % os.environ["CAPTURE"]
)
path.chmod(0o755)
PYEOF
feedback_gate_human_comment "$PLAIN_LANGUAGE_DIR" "$CAPTURE_STUB" "$DIRTY" >/dev/null
if grep -qF 'product owner, not a senior dev' "$CAPTURE"; then
  ok verbatim-pospeak-in-prompt 'the rewrite prompt carries pospeak.md verbatim, sourced from its one copy'
else
  bad verbatim-pospeak-in-prompt 'the rewrite prompt is missing the pospeak.md rule text'
fi

# A stub rewrite CLI that still returns a non-compliant draft holds again.
BADSTUB="$TMP/bad-stub-cli"
cat > "$BADSTUB" <<'EOF'
#!/usr/bin/env bash
printf 'still not html and still no ask'
EOF
chmod +x "$BADSTUB"
if out="$(feedback_gate_human_comment "$PLAIN_LANGUAGE_DIR" "$BADSTUB" "$DIRTY" 2>"$TMP/reasons2")"; then
  bad rewrite-still-failing-held "expected a failure, got output: $out"
else
  if grep -q 'plain-language-held' "$TMP/reasons2"; then
    ok rewrite-still-failing-held 'a rewrite that still fails the check holds instead of posting'
  else
    bad rewrite-still-failing-held 'second failure did not log the draft and reasons'
  fi
fi

printf '\n%d human-comment-gate behavioural check(s) failed\n' "$fails"
[ "$fails" -eq 0 ]
