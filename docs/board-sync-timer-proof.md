# Board sync timer proof

Goal: keep each chat's board syncing after its watcher or chat exits.

Only Hypertask Reconciler was armed, on board 13556 with label Hypertask Reconciler.
The service used its own named token file. No token was printed.
A temporary service-only `RECONCILE_AUTO_DRY=1` override prevented board writes.
The installed reconcile logged `--apply dropped, nothing moves` and `sync: ok`.

`systemctl --user start board-sync@hypertask-reconciler.service` exited 0.
`systemctl --user list-timers --all board-sync@hypertask-reconciler.timer` and the loop-state record:

```text
NEXT                         LEFT LAST                         PASSED UNIT                                  ACTIVATES
Mon 2026-11-23 22:10:39 CET 16min Mon 2026-11-23 21:53:38 CET 27s ago board-sync@hypertask-reconciler.timer board-sync@hypertask-reconciler.service

1 timers listed.
Result=success
ExecMainStatus=0
ActiveState=inactive
{
  "name": "Hypertask Reconciler",
  "board": 13556,
  "label": "Hypertask Reconciler",
  "sync_timer": "board-sync@hypertask-reconciler.timer",
  "sync_timer_armed_at": "2026-11-23T20:53:37Z",
  "last_sync": {
    "at": "2026-11-23T20:53:50Z",
    "ok": true,
    "reason": ""
  }
}
```

Hermetic fake-systemctl coverage: repeated arm, board/label update, own-token isolation,
missing timer, disabled timer, stale-chat pruning, watcher exit, reload retry and state preservation.
`python3 -m unittest discover -s tests -p test_board_sync_timer.py`: 12 tests, OK.
All 16 `hooks/*.py --self-test` commands exited 0.
