#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd -P)
TEST_HOME=$(mktemp -d "$ROOT/.install-test.XXXXXX")
trap 'rm -rf "$TEST_HOME"' EXIT

dests=(.claude/skills .codex/skills .cursor/skills .pi/agent/skills .agents/skills)

for run in 1 2; do
  env HOME="$TEST_HOME" VSTACK_DIR="$TEST_HOME/.local/share/vstack" "$ROOT/install"
  for dest in "${dests[@]}"; do
    skill="$TEST_HOME/$dest/valentin-mode"
    [ -L "$skill" ]
    [ "$(cd "$skill" && pwd -P)" = "$ROOT/skills/valentin-mode" ]
    cmp "$skill/SKILL.md" "$ROOT/skills/valentin-mode/SKILL.md"
    printf 'PASS run %s: %s/valentin-mode\n' "$run" "$dest"
  done
done

rm "$TEST_HOME/.pi/agent/skills/valentin-mode"
ln -s "$TEST_HOME/missing" "$TEST_HOME/.pi/agent/skills/valentin-mode"
rm "$TEST_HOME/.claude/skills/valentin-mode"
mkdir "$TEST_HOME/.claude/skills/valentin-mode"
printf 'keep this copy\n' > "$TEST_HOME/.claude/skills/valentin-mode/SKILL.md"
# A local skill that now lives inside the hypertask skill, and a settings file
# install must never touch.
mkdir "$TEST_HOME/.claude/skills/ticket"
printf 'old ticket skill\n' > "$TEST_HOME/.claude/skills/ticket/SKILL.md"
ln -s "$TEST_HOME/now-gone" "$TEST_HOME/.claude/skills/hypertask-checkup"
printf '{"hooks":{"Stop":[]}}\n' > "$TEST_HOME/.claude/settings.json"
settings=$(sha256sum "$TEST_HOME/.claude/settings.json")

env HOME="$TEST_HOME" VSTACK_DIR="$TEST_HOME/.local/share/vstack" "$ROOT/install"
for dest in "${dests[@]}"; do
  skill="$TEST_HOME/$dest/valentin-mode"
  [ -L "$skill" ]
  [ "$(cd "$skill" && pwd -P)" = "$ROOT/skills/valentin-mode" ]
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
printf 'PASS install never edits a settings file\n'
