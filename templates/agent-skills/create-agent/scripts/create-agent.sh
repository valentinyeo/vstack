#!/usr/bin/env bash
# create-agent.sh — provision a skills-driven agent identity (generic core).
#
# Board-agnostic: works for any repo, no issue tracker required. Dry-run is
# the default — nothing is created, nothing is called, nothing is installed
# unless --yes is also passed.
#
# A project wired to a specific board or issue tracker (identity creation,
# webhook, a chat test against that tracker's UI) should extend this script
# with its own block behind a flag, e.g. --board <name>, gated the same way:
# dry-run by default, --yes required, a hard stop before any call that
# creates a real identity elsewhere.
#
# Never prints secrets.

set -euo pipefail

# ---------- defaults ----------
NAME=""
KIND=""                # dev | qa | cli
PROVIDER="claude"       # claude | cursor | codex
REPO=""
SKILLS_REPO="$(pwd)"
DRY_RUN="yes"

CONFIG_DIR="${AGENT_CONFIG_DIR:-$HOME/.config/agents}"
STATE_ROOT="${AGENT_STATE_ROOT:-$HOME/.local/state}"
BIN_DIR="$HOME/.local/bin"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

usage() {
  cat <<'EOF'
Usage: create-agent.sh --name "<Name>" --kind dev|qa|cli [options]

  --name NAME              Display name, e.g. "Repo Bot"        (required)
  --kind dev|qa|cli         dev/qa run a worker; cli is env-only, no chat
  --provider claude|cursor|codex   default: claude
  --repo PATH               repo the worker's cwd is set to (required for dev/qa)
  --skills-repo PATH         folder with INDEX.md               default: cwd
  --yes                      actually do it
  --dry-run                  print the plan, touch nothing       (default)
  -h, --help                 this message
EOF
}

# ---------- args ----------
while [ $# -gt 0 ]; do
  case "$1" in
    --name) NAME="$2"; shift 2 ;;
    --kind) KIND="$2"; shift 2 ;;
    --provider) PROVIDER="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    --skills-repo) SKILLS_REPO="$2"; shift 2 ;;
    --yes) DRY_RUN="no"; shift ;;
    --dry-run) DRY_RUN="yes"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -n "$NAME" ] || { echo "error: --name is required" >&2; exit 2; }
case "$KIND" in
  dev|qa|cli) ;;
  *) echo "error: --kind must be dev, qa, or cli" >&2; exit 2 ;;
esac
case "$PROVIDER" in
  claude|cursor|codex) ;;
  *) echo "error: --provider must be claude, cursor, or codex" >&2; exit 2 ;;
esac

SLUG="$(printf '%s' "$NAME" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g')"
if [ "$KIND" = "cli" ]; then DISPLAY_NAME="$NAME CLI"; else DISPLAY_NAME="$NAME"; fi

if [ "$KIND" != "cli" ] && [ -z "$REPO" ]; then
  echo "error: --repo is required for --kind $KIND" >&2
  exit 2
fi
if [ -n "$REPO" ] && [ ! -d "$REPO" ]; then
  echo "error: --repo $REPO does not exist" >&2
  exit 2
fi
INDEX_MD="$SKILLS_REPO/INDEX.md"
if [ ! -f "$INDEX_MD" ]; then
  echo "warning: $INDEX_MD not found — the mission points at a file that isn't there yet" >&2
fi

STATE_DIR="$STATE_ROOT/agent-$SLUG"
ENV_FILE="$CONFIG_DIR/$SLUG.env"
WRAPPER="$BIN_DIR/$SLUG"

echo "=== plan: $DISPLAY_NAME ($SLUG), kind=$KIND, provider=$PROVIDER ==="
[ "$DRY_RUN" = "yes" ] && echo "(dry run — nothing below is executed)"
echo

STEP=0
plan() { STEP=$((STEP + 1)); echo "[$STEP] $1"; }

if [ "$KIND" = "qa" ]; then
  MISSION="You are $DISPLAY_NAME. You verify, you never fix. Read the literal absolute path $INDEX_MD first, then only the skill(s) it points you to for verification, and follow them exactly. Say which skill you used in your first reply. Corrections go into the skill file, not into chat."
else
  MISSION="You are $DISPLAY_NAME. Step one, before anything else: open the file at the literal absolute path $INDEX_MD (a tilde will not resolve in your home) and name the skill(s) whose trigger matches this task in your first reply. Then follow the matched skill file(s) exactly, including their saved scripts. If no skill matches, say so and stop. Corrections go into the skill file, never into chat memory."
fi

echo "Mission (${#MISSION} chars):"
echo "  $MISSION"
echo

plan "make config dir"
echo "    + mkdir -p $CONFIG_DIR"
[ "$DRY_RUN" != "yes" ] && mkdir -p "$CONFIG_DIR"

plan "make state dir"
echo "    + mkdir -p $STATE_DIR"
[ "$DRY_RUN" != "yes" ] && mkdir -p "$STATE_DIR"

if [ "$KIND" = "cli" ]; then
  ENV_CONTENT="$(cat <<EOF
AGENT_NAME="$DISPLAY_NAME"
AGENT_SLUG="$SLUG"
AGENT_KIND="cli"
AGENT_PROVIDER="$PROVIDER"
AGENT_MISSION="$MISSION"
EOF
)"
  plan "write $ENV_FILE (0600) — env-only identity, cannot chat"
  echo "    + printf '%s\n' \"\$ENV_CONTENT\" > $ENV_FILE && chmod 600 $ENV_FILE"
  if [ "$DRY_RUN" != "yes" ]; then
    umask 077
    printf '%s\n' "$ENV_CONTENT" > "$ENV_FILE"
    chmod 600 "$ENV_FILE"
  fi
  echo
  echo "Note: a CLI identity has no worker and no chat test. It shows up in"
  echo "logs and commit trails under its own name, nothing else."
  echo
  [ "$DRY_RUN" = "yes" ] && echo "Dry run only. Re-run with --yes to actually create $DISPLAY_NAME."
  exit 0
fi

ENV_CONTENT="$(cat <<EOF
AGENT_NAME="$DISPLAY_NAME"
AGENT_SLUG="$SLUG"
AGENT_KIND="$KIND"
AGENT_PROVIDER="$PROVIDER"
AGENT_REPO="$REPO"
AGENT_SKILLS_INDEX="$INDEX_MD"
EOF
)"
plan "write $ENV_FILE (0600)"
echo "    + printf '%s\n' \"\$ENV_CONTENT\" > $ENV_FILE && chmod 600 $ENV_FILE"
if [ "$DRY_RUN" != "yes" ]; then
  umask 077
  printf '%s\n' "$ENV_CONTENT" > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

case "$PROVIDER" in
  claude) PROVIDER_CMD='claude -p "$PROMPT"' ;;
  cursor) PROVIDER_CMD='cursor-agent -p "$PROMPT"' ;;
  codex)  PROVIDER_CMD='codex exec "$PROMPT"' ;;
esac
WRAPPER_CONTENT="$(cat <<EOF
#!/usr/bin/env bash
# $SLUG — trigger wrapper. Usage: $SLUG run "<task text>"
set -euo pipefail
cd "$REPO"
MISSION='$MISSION'
TASK="\${2:-\$1}"
PROMPT="\$MISSION

Task: \$TASK"
$PROVIDER_CMD
EOF
)"
plan "write $WRAPPER (0755) — manual/cron trigger, cwd=$REPO"
echo "    + printf '%s\n' \"\$WRAPPER_CONTENT\" > $WRAPPER && chmod 755 $WRAPPER"
if [ "$DRY_RUN" != "yes" ]; then
  printf '%s\n' "$WRAPPER_CONTENT" > "$WRAPPER"
  chmod 755 "$WRAPPER"
fi

UNIT_PATH="$SYSTEMD_USER_DIR/agent-worker-$SLUG.service"
UNIT_CONTENT="$(cat <<EOF
[Unit]
Description=$DISPLAY_NAME — one run of the skills-driven worker

[Service]
Type=oneshot
WorkingDirectory=$REPO
ExecStart=$WRAPPER run "\${TASK}"
EOF
)"
plan "write generic oneshot unit $UNIT_PATH (one process per event)"
echo "    + printf '%s\n' \"\$UNIT_CONTENT\" > $UNIT_PATH"
if [ "$DRY_RUN" != "yes" ]; then
  mkdir -p "$SYSTEMD_USER_DIR"
  printf '%s\n' "$UNIT_CONTENT" > "$UNIT_PATH"
  command -v systemctl >/dev/null 2>&1 && systemctl --user daemon-reload || true
fi

plan "chat test — send the mission + a hello prompt to the $PROVIDER CLI"
echo "    + $WRAPPER run \"Reply with OK and your name, nothing else.\""
if [ "$DRY_RUN" != "yes" ]; then
  "$WRAPPER" run "Reply with OK and your name, nothing else."
fi

echo
[ "$DRY_RUN" = "yes" ] && echo "Dry run only. Re-run with --yes to actually create $DISPLAY_NAME."
exit 0
