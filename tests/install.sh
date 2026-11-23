#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd -P)
TEST_HOME=$(mktemp -d "$ROOT/.install-test.XXXXXX")
trap 'rm -rf "$TEST_HOME"' EXIT

dests=(.claude/skills .codex/skills .cursor/skills .pi/agent/skills .agents/skills \
  .gemini/antigravity-cli/skills .gemini/config/skills)
retired_hooks=(claude-helper-gate.py gh-watch-guard.py launch-gate.py plan-pick-only.py reconcile-auto.py repo-tidy-stop)
mkdir -p "$TEST_HOME/.claude/hooks" "$TEST_HOME/.local/bin"
for hook in "${retired_hooks[@]}"; do
  ln -s "$ROOT/hooks/$hook" "$TEST_HOME/.claude/hooks/$hook"
done
ln -s "$ROOT/skills/vps-tidy/vps-tidy" "$TEST_HOME/.local/bin/vps-tidy"
for dest in "${dests[@]}"; do
  mkdir -p "$TEST_HOME/$dest"
  ln -s "$ROOT/skills/vps-tidy" "$TEST_HOME/$dest/vps-tidy"
done
printf 'user hook\n' > "$TEST_HOME/.claude/hooks/user-hook.py"

for run in 1 2; do
  env HOME="$TEST_HOME" VSTACK_INSTALL_ANYWHERE=1 VSTACK_DIR="$TEST_HOME/.local/share/vstack" "$ROOT/install"
  for dest in "${dests[@]}"; do
    skill="$TEST_HOME/$dest/valentin-mode"
    [ -L "$skill" ]
    [ "$(cd "$skill" && pwd -P)" = "$TEST_HOME/.local/state/vstack/skills/valentin-mode" ]
    [ "$(readlink -f "$skill/context.py")" = "$ROOT/skills/valentin-mode/context.py" ]
    grep -q 'hooks/run-hook' "$skill/SKILL.md"
    printf 'PASS run %s: %s/valentin-mode\n' "$run" "$dest"
  done
done

for hook in "${retired_hooks[@]}"; do
  [ ! -L "$TEST_HOME/.claude/hooks/$hook" ]
done
[ ! -L "$TEST_HOME/.local/bin/vps-tidy" ]
for dest in "${dests[@]}"; do
  [ ! -L "$TEST_HOME/$dest/vps-tidy" ]
done
[ "$(cat "$TEST_HOME/.claude/hooks/user-hook.py")" = 'user hook' ]
printf 'PASS retired links removed and unrelated hooks preserved\n'

for name in test-timeout-guard.py pstack-new-gates.py skill-update.py; do
  hook="$TEST_HOME/.claude/hooks/$name"
  [ -L "$hook" ]
  [ "$(readlink -f "$hook")" = "$ROOT/hooks/$name" ]
  printf 'PASS hook linked: .claude/hooks/%s\n' "$name"
done

rm "$TEST_HOME/.pi/agent/skills/valentin-mode"
ln -s "$TEST_HOME/missing" "$TEST_HOME/.pi/agent/skills/valentin-mode"
rm "$TEST_HOME/.claude/skills/valentin-mode"
mkdir "$TEST_HOME/.claude/skills/valentin-mode"
printf 'keep this copy\n' > "$TEST_HOME/.claude/skills/valentin-mode/SKILL.md"
# A local skill that now lives inside hypertask, and settings without retired hooks.
mkdir "$TEST_HOME/.claude/skills/ticket"
printf 'old ticket skill\n' > "$TEST_HOME/.claude/skills/ticket/SKILL.md"
ln -s "$TEST_HOME/now-gone" "$TEST_HOME/.claude/skills/hypertask-checkup"
printf '{"hooks":{"Stop":[]}}\n' > "$TEST_HOME/.claude/settings.json"
settings=$(sha256sum "$TEST_HOME/.claude/settings.json")

env HOME="$TEST_HOME" VSTACK_INSTALL_ANYWHERE=1 VSTACK_DIR="$TEST_HOME/.local/share/vstack" "$ROOT/install"
for dest in "${dests[@]}"; do
  skill="$TEST_HOME/$dest/valentin-mode"
  [ -L "$skill" ]
  [ "$(cd "$skill" && pwd -P)" = "$TEST_HOME/.local/state/vstack/skills/valentin-mode" ]
done
printf 'PASS stale Pi symlink replaced\n'

copies=("$TEST_HOME"/.local/state/skill-dupes-*/.claude/skills/valentin-mode/SKILL.md)
[ "${#copies[@]}" -eq 1 ]
[ "$(cat "${copies[0]}")" = 'keep this copy' ]
printf 'PASS existing Claude copy preserved\n'

for path in "$TEST_HOME/.claude/skills/hypertask" "$TEST_HOME/.claude/skills/hypertask-work"; do
  [ -L "$path" ]
done
[ "$(cd "$TEST_HOME/.claude/skills/hypertask" && pwd -P)" = "$ROOT/skills/hypertask" ]
cmp "$TEST_HOME/.claude/skills/hypertask/SKILL.md" "$ROOT/skills/hypertask/SKILL.md"
[ "$(cd "$TEST_HOME/.claude/skills/hypertask-work" && pwd -P)" = "$ROOT/skills/hypertask-work" ]
[ -x "$TEST_HOME/.claude/skills/hypertask-work/reconcile" ]
printf 'PASS hypertask linked and hypertask-work scripts kept at their path\n'

[ ! -e "$TEST_HOME/.claude/skills/ticket" ] || [ -L "$TEST_HOME/.claude/skills/ticket" ]
[ ! -e "$TEST_HOME/.claude/skills/hypertask-checkup" ] && [ ! -L "$TEST_HOME/.claude/skills/hypertask-checkup" ]
retired=("$TEST_HOME"/.local/state/skill-dupes-*/.claude/skills/ticket/SKILL.md)
[ "${#retired[@]}" -eq 1 ]
[ "$(cat "${retired[0]}")" = 'old ticket skill' ]
printf 'PASS retired ticket folder moved, not deleted\n'

[ "$(sha256sum "$TEST_HOME/.claude/settings.json")" = "$settings" ]
printf 'PASS settings without retired hooks stay byte-for-byte unchanged\n'
python3 - "$TEST_HOME/.claude/settings.json" "${retired_hooks[@]}" <<'PY'
import json
from pathlib import Path
import sys
path = Path(sys.argv[1])
retired = [{'type': 'command', 'command': 'python3 ~/.claude/hooks/' + name} for name in sys.argv[2:]]
kept = {'type': 'command', 'command': 'echo unrelated', 'timeout': 7}
path.write_text(json.dumps({'env': {'KEEP': 'yes'}, 'hooks': {
    'UserPromptSubmit': [{'hooks': retired}],
    'PreToolUse': [{'matcher': '*', 'hooks': [retired[0], kept]}],
    'Stop': [{'hooks': []}]
}}))
path.chmod(0o600)
PY
env HOME="$TEST_HOME" VSTACK_INSTALL_ANYWHERE=1 VSTACK_DIR="$TEST_HOME/.local/share/vstack" "$ROOT/install"
python3 - "$TEST_HOME/.claude/settings.json" <<'PY'
import json
from pathlib import Path
import sys
path = Path(sys.argv[1])
assert json.loads(path.read_text()) == {'env': {'KEEP': 'yes'}, 'hooks': {
    'UserPromptSubmit': [],
    'PreToolUse': [{'matcher': '*', 'hooks': [{'type': 'command', 'command': 'echo unrelated', 'timeout': 7}]}],
    'Stop': [{'hooks': []}]
}}
assert path.stat().st_mode & 0o777 == 0o600
PY
printf 'PASS retired registrations removed without changing unrelated settings\n'
# repo-tidy remains an explicit command.
[ -L "$TEST_HOME/.local/bin/repo-tidy" ]
[ "$(readlink -f "$TEST_HOME/.local/bin/repo-tidy")" = "$ROOT/skills/repo-tidy/repo-tidy" ]
[ -x "$TEST_HOME/.local/bin/repo-tidy" ]
printf 'PASS repo-tidy command linked\n'

for hook in pacer-guard.py; do
  [ -L "$TEST_HOME/.claude/hooks/$hook" ]
  [ "$(readlink -f "$TEST_HOME/.claude/hooks/$hook")" = "$ROOT/hooks/$hook" ]
  [ -x "$TEST_HOME/.claude/hooks/$hook" ]
  printf 'PASS hook %s is linked and executable\n' "$hook"
done
