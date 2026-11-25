#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd -P)
TEST_HOME=$(mktemp -d "$ROOT/.install-test.XXXXXX")
trap 'rm -rf "$TEST_HOME"' EXIT

dests=(.claude/skills .codex/skills .cursor/skills .pi/agent/skills .agents/skills \
  .gemini/antigravity-cli/skills .gemini/config/skills)
retired_hooks=(claude-helper-gate.py gh-watch-guard.py launch-gate.py plan-pick-only.py pstack-reply.py reconcile-auto.py repo-tidy-stop)
mkdir -p "$TEST_HOME/.claude/hooks" "$TEST_HOME/.local/bin"
for hook in "${retired_hooks[@]}"; do
  ln -s "$ROOT/hooks/$hook" "$TEST_HOME/.claude/hooks/$hook"
done
printf 'user hook\n' > "$TEST_HOME/.claude/hooks/user-hook.py"

for run in 1 2; do
  env HOME="$TEST_HOME" VSTACK_INSTALL_ANYWHERE=1 VSTACK_DIR="$TEST_HOME/.local/share/vstack" "$ROOT/install"
  [ -L "$TEST_HOME/.local/bin/ci-key-set" ]
  [ "$(readlink -f "$TEST_HOME/.local/bin/ci-key-set")" = "$ROOT/tools/ci-key-set" ]
  [ -x "$TEST_HOME/.local/bin/ci-key-set" ]
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
[ "$(cat "$TEST_HOME/.claude/hooks/user-hook.py")" = 'user hook' ]
printf 'PASS retired links removed and unrelated hooks preserved\n'

for name in test-timeout-guard.py pstack-new-gates.py skill-update.py agent-lane-guard.py; do
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

for path in "$TEST_HOME/.claude/skills/hypertask" "$TEST_HOME/.codex/skills/hypertask" "$TEST_HOME/.claude/skills/hypertask-work"; do
  [ -L "$path" ]
done
[ "$(cd "$TEST_HOME/.claude/skills/hypertask" && pwd -P)" = "$ROOT/skills/hypertask" ]
[ "$(cd "$TEST_HOME/.codex/skills/hypertask" && pwd -P)" = "$ROOT/skills/hypertask" ]
cmp "$TEST_HOME/.claude/skills/hypertask/SKILL.md" "$ROOT/skills/hypertask/SKILL.md"
cmp "$TEST_HOME/.codex/skills/hypertask/references/tickets.md" "$ROOT/skills/hypertask/references/tickets.md"
cmp "$TEST_HOME/.codex/skills/hypertask/references/checkup.md" "$ROOT/skills/hypertask/references/checkup.md"
cmp "$TEST_HOME/.codex/skills/hypertask/scripts/ticket-lint" "$ROOT/skills/hypertask/scripts/ticket-lint"
[ "$(cd "$TEST_HOME/.claude/skills/hypertask-work" && pwd -P)" = "$ROOT/skills/hypertask-work" ]
[ -x "$TEST_HOME/.claude/skills/hypertask-work/reconcile" ]
printf 'PASS hypertask linked for Claude and Codex and hypertask-work scripts kept at their path\n'

[ ! -e "$TEST_HOME/.claude/skills/ticket" ] || [ -L "$TEST_HOME/.claude/skills/ticket" ]
[ ! -e "$TEST_HOME/.claude/skills/hypertask-checkup" ] && [ ! -L "$TEST_HOME/.claude/skills/hypertask-checkup" ]
retired=("$TEST_HOME"/.local/state/skill-dupes-*/.claude/skills/ticket/SKILL.md)
[ "${#retired[@]}" -eq 1 ]
[ "$(cat "${retired[0]}")" = 'old ticket skill' ]
printf 'PASS retired ticket folder moved, not deleted\n'

# VSTA-204, VSTA-207: both hooks a chat needs wherever it runs are registered once,
# globally. A re-run adds no second entry and leaves the rest of the file alone.
settings_before_install=$(sha256sum "$TEST_HOME/.claude/settings.json")
env HOME="$TEST_HOME" VSTACK_INSTALL_ANYWHERE=1 VSTACK_DIR="$TEST_HOME/.local/share/vstack" "$ROOT/install"
[ "$(sha256sum "$TEST_HOME/.claude/settings.json")" = "$settings_before_install" ]
python3 - "$TEST_HOME/.claude/settings.json" <<'PY'
import json
from pathlib import Path
import sys
data = json.loads(Path(sys.argv[1]).read_text())
reload = [hook['command'] for group in data['hooks']['UserPromptSubmit']
          for hook in group['hooks'] if 'skill-update.py' in hook.get('command', '')]
assert reload == ['"$HOME/.local/share/vstack/hooks/run-hook" '
                  '"$HOME/.claude/hooks/skill-update.py"'], reload
guard = '"$HOME/.local/share/vstack/hooks/run-hook" "$HOME/.claude/hooks/pr-cap-guard.py"'
lane = '"$HOME/.local/share/vstack/hooks/run-hook" "$HOME/.claude/hooks/agent-lane-guard.py"'
assert [(group.get('matcher'), hook['command'], hook.get('timeout'))
        for group in data['hooks']['PreToolUse']
        for hook in group['hooks']] == [('Bash', guard, 30),
                                        ('Bash', lane, 10),
                                        ('mcp__.*create_pull_request', guard, 30)], data
assert set(data) >= {'hooks'}, data
assert data['hooks']['Stop'] == [{'hooks': [{
    'type': 'command',
    'command': '"$HOME/.local/share/vstack/hooks/run-hook" "$HOME/.claude/hooks/ask-first-guard.py"'}]}], \
    'a Stop list that started empty gains only the ask-first guard'
PY
printf 'PASS skill-update and the PR cap guard registered globally exactly once, idempotently\n'
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
guard = {'type': 'command',
         'command': '"$HOME/.local/share/vstack/hooks/run-hook" "$HOME/.claude/hooks/pr-cap-guard.py"',
         'timeout': 30}
lane = {'type': 'command',
        'command': '"$HOME/.local/share/vstack/hooks/run-hook" "$HOME/.claude/hooks/agent-lane-guard.py"',
        'timeout': 10}
ask = {'type': 'command',
       'command': '"$HOME/.local/share/vstack/hooks/run-hook" "$HOME/.claude/hooks/ask-first-guard.py"'}
assert json.loads(path.read_text()) == {'env': {'KEEP': 'yes'}, 'hooks': {
    'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': '"$HOME/.local/share/vstack/hooks/run-hook" "$HOME/.claude/hooks/skill-update.py"'}]}],
    'PreToolUse': [
        {'matcher': '*', 'hooks': [{'type': 'command', 'command': 'echo unrelated', 'timeout': 7}]},
        {'matcher': 'Bash', 'hooks': [guard, lane]},
        {'matcher': 'mcp__.*create_pull_request', 'hooks': [guard]},
    ],
    'Stop': [{'hooks': [ask]}]
}}
assert path.stat().st_mode & 0o777 == 0o600
PY
printf 'PASS retired registrations removed without changing unrelated settings\n'
# repo-tidy remains an explicit command.
[ -L "$TEST_HOME/.local/bin/repo-tidy" ]
[ "$(readlink -f "$TEST_HOME/.local/bin/repo-tidy")" = "$ROOT/skills/repo-tidy/repo-tidy" ]
[ -x "$TEST_HOME/.local/bin/repo-tidy" ]
printf 'PASS repo-tidy command linked\n'

# vps-tidy is the shared server cleaner (VSTA-7).
[ -L "$TEST_HOME/.local/bin/vps-tidy" ]
[ "$(readlink -f "$TEST_HOME/.local/bin/vps-tidy")" = "$ROOT/skills/vps-tidy/vps-tidy" ]
[ -x "$TEST_HOME/.local/bin/vps-tidy" ]
for dest in "${dests[@]}"; do
  [ -L "$TEST_HOME/$dest/vps-tidy" ]
done
printf 'PASS vps-tidy command linked\n'

for hook in pacer-guard.py; do
  [ -L "$TEST_HOME/.claude/hooks/$hook" ]
  [ "$(readlink -f "$TEST_HOME/.claude/hooks/$hook")" = "$ROOT/hooks/$hook" ]
  [ -x "$TEST_HOME/.claude/hooks/$hook" ]
  printf 'PASS hook %s is linked and executable\n' "$hook"
done

[ -L "$TEST_HOME/.claude/hooks/ask-first-guard.py" ]
[ "$(readlink -f "$TEST_HOME/.claude/hooks/ask-first-guard.py")" = "$ROOT/hooks/ask-first-guard.py" ]
printf 'PASS ask-first-guard is linked like every other hook\n'

# VSTA-289: ask-first-guard was a loose file wired by its full path. install puts it behind
# the launcher, drops that one old registration and keeps every other Stop hook.
python3 - "$TEST_HOME/.claude/settings.json" <<'PY'
import json
from pathlib import Path
import sys
path = Path(sys.argv[1])
loose = {'type': 'command', 'command': f'/usr/bin/python3 {path.parent}/hooks/ask-first-guard.py'}
other = {'type': 'command', 'command': 'echo keep me', 'timeout': 5}
path.write_text(json.dumps({'hooks': {'Stop': [
    {'hooks': [other]},
    {'hooks': [loose, other]},
]}}, indent=2) + '\n')
PY
env HOME="$TEST_HOME" VSTACK_INSTALL_ANYWHERE=1 VSTACK_DIR="$TEST_HOME/.local/share/vstack" "$ROOT/install"
settings_after_migration=$(sha256sum "$TEST_HOME/.claude/settings.json")
env HOME="$TEST_HOME" VSTACK_INSTALL_ANYWHERE=1 VSTACK_DIR="$TEST_HOME/.local/share/vstack" "$ROOT/install"
[ "$(sha256sum "$TEST_HOME/.claude/settings.json")" = "$settings_after_migration" ]
python3 - "$TEST_HOME/.claude/settings.json" <<'PY'
import json
from pathlib import Path
import sys
data = json.loads(Path(sys.argv[1]).read_text())
groups = data['hooks']['Stop']
guided = [hook['command'] for group in groups for hook in group['hooks']
          if 'ask-first-guard.py' in hook.get('command', '')]
assert guided == ['"$HOME/.local/share/vstack/hooks/run-hook" '
                  '"$HOME/.claude/hooks/ask-first-guard.py"'], guided
kept = [hook['command'] for group in groups for hook in group['hooks']
        if hook.get('command') == 'echo keep me']
assert kept == ['echo keep me', 'echo keep me'], kept
assert all(group.get('hooks') for group in groups), groups
PY
printf 'PASS the loose ask-first-guard registration becomes one launcher entry, idempotently\n'
