#!/usr/bin/env bash
# Template for a deterministic skill step.
#
# Copy this pattern for any step a skill does the same way every time.
# Two rules for every script in a skill's scripts/ folder:
#   1. Support --dry-run: print what would happen instead of doing it.
#   2. Pass `bash -n scripts/*.sh` (syntax check only, catches typos early).
#
# Usage:
#   example.sh <required-arg> [--dry-run]

set -euo pipefail

ARG="${1:?usage: example.sh <required-arg> [--dry-run]}"
shift || true

DRY_RUN="no"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN="yes"; shift ;;
    *) echo "example.sh: unknown arg: $1" >&2; exit 1 ;;
  esac
done

run() {
  if [ "$DRY_RUN" = "yes" ]; then
    printf 'DRY RUN: %s\n' "$*"
  else
    "$@"
  fi
}

# Replace this with the actual deterministic command(s) this step performs.
run echo "would act on: $ARG"
