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
