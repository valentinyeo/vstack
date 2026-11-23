---
name: fleet-report
description: >-
  Snapshot of every live chat on this server: valentin-mode version loaded,
  latest version, board-drain loop, and pstack-diff self-check. Show Valentin
  the list (the published report link); each failing chat fixes itself on its
  own next load.
---

# fleet-report

Prior art: pstack poteto-mode — checked per-chat autonomous loop and shipping skills; local pstack-diff already self-checks one repo, so only the cross-session fleet table lives here.

Changes no tracked files in the chats it inspects. For every git checkout with an `origin` remote it always runs `git fetch` (60 s), adds a temporary detached worktree at the remote default branch, runs pstack-diff there, and always removes that worktree. Exit 0 always (report, not gate).

## Run

```bash
python3 ~/.local/share/vstack/skills/fleet-report/fleet-report
python3 skills/fleet-report/fleet-report --json
python3 skills/fleet-report/fleet-report --html /tmp/fleet-report.html
```

Sources: mp-sessions --json and the house-rules fleet roster-live helper for live chats; Claude transcripts under ~/.claude/projects/<encoded-cwd>/<session-id>.jsonl.

Columns: loaded valentin-mode version, latest from skills/valentin-mode/version.sh, board-drain loop-state status, pstack-diff EXTRA/GAP counts (always re-run on upstream default after fetch), verdict tags (**OK**, **BEHIND**, **NO VALENTIN-MODE**, **LOOP OFF**, **FIX**, **GAPS**, **UNKNOWN**, **STALE**), and a short **ACTION** column.

**Do not fix other chats from here.** Show Valentin the list (the published report link). Each failing chat fixes itself on its own next load when it loads valentin-mode and runs pstack-diff on itself.