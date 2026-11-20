---
name: valentin-mode
description: >-
  Snapshot of the two board subsections vstack main had before the one-skill
  change. Used only to prove the restating lint catches them.
---

### Board rules

Board work follows the `hypertask-work` skill: own login, ticket first, true column. Get the login with `/board-identity`. Never write as Valentin; a guard blocks it. Run `/hypertask-checkup` on a new project and daily.

### Board sync

Project notes name it: `Hypertask board: <id>, label: <label>`. The lease syncs a card when its worker starts and ends. A Stop hook runs `reconcile --label <label> --apply` after each turn, at most every 10 minutes, as your own login named like your Multibot chat. It stops you only when your setup is missing. Tool failures go to failures.jsonl under ~/.local/state/reconcile-auto for the reconcile owner, Hypertask Reconciler. On `/valentin-mode`, read your record and fix it.
