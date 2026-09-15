#!/usr/bin/env bash
# install.sh: put this template on a machine.
#
# This repo is the canonical copy. What ends up in ~/.claude/skills and
# ~/.local/bin is an installed copy, never the source of truth: edit here, then
# run this again. Re-running is safe and overwrites the installed copy.
#
# Usage:
#   ./install.sh [--dest DIR] [--bin DIR] [--dry-run] [-h|--help]
#
# Examples:
#   ./install.sh --dry-run          # show what would be copied where
#   ./install.sh                    # install for the current user
#
# Failure contract: ERROR: <what happened>. Do this next: <one step>, non-zero.

set -euo pipefail

SELF="$(readlink -f "${BASH_SOURCE[0]}")"
SRC="$(dirname "$SELF")"
DEST="$HOME/.claude/skills/create-agent"
BIN="${AGENT_BIN_DIR:-$HOME/.local/bin}"
DRY_RUN="no"

fail() { printf 'ERROR: %s. Do this next: %s\n' "$1" "$2" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dest) DEST="$2"; shift 2 ;;
    --bin) BIN="$2"; shift 2 ;;
    --dry-run) DRY_RUN="yes"; shift ;;
    -h|--help) sed -n '2,16p' "$SELF" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) fail "unknown argument $1" "run ./install.sh --help" ;;
  esac
done

for item in SKILL.md scripts adapters; do
  [ -e "$SRC/$item" ] || fail "$SRC/$item is missing" \
    "run install.sh from inside the template folder in the repo"
done

echo "source: $SRC"
echo "skill:  $DEST"
echo "bin:    $BIN/agent-board-poll -> $DEST/scripts/agent-board-poll"

if [ "$DRY_RUN" = "yes" ]; then
  echo "(dry run: nothing copied)"
  exit 0
fi

mkdir -p "$DEST" "$BIN"
rm -rf "$DEST/scripts" "$DEST/adapters"
cp -a "$SRC/SKILL.md" "$DEST/SKILL.md"
cp -a "$SRC/scripts" "$SRC/adapters" "$DEST/"
chmod 755 "$DEST/scripts/create-agent.sh" "$DEST/scripts/agent-board-poll"

# A symlink, so the installed runner and the installed skill can never drift
# apart, and so the runner still finds its adapters through readlink -f.
ln -sfn "$DEST/scripts/agent-board-poll" "$BIN/agent-board-poll"

bash "$DEST/scripts/create-agent.sh" --help >/dev/null \
  || fail "the installed create-agent.sh does not run" \
          "check bash and python3 are present, then re-run install.sh"
"$BIN/agent-board-poll" --help >/dev/null \
  || fail "the installed agent-board-poll does not run" \
          "check that $BIN is on PATH and the symlink resolves"

echo "installed. Next: run create-agent.sh --help, or agent-board-poll --once --dry-run <slug>"
