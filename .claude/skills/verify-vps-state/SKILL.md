---
name: verify-vps-state
description: >-
  Prove that skills/vps-state/vps-state answers the real host correctly. Drives the script on this VPS, saves every output and exit code, re-reads the same numbers with nproc, /proc/loadavg, free and df, and grades PASS or FAIL per check. Use after any change to vps-state, as proof on such a PR, and whenever a session doubts the server verdict.
---

# Verify vps-state

Prior art: checked pstack (`create-verification-skill`), this repo's `verify-reconcile` and `verify-valentin-mode`. Neither proves a host reading. This is the `verify-<app>` skill create-verification-skill asks for, with `vps-state` as the app.

The proof bar: the script's own numbers are compared with a second read of the same host, taken by other tools. A run where the two agree, the exit codes match the verdict, the status file carries the verdict, and the hook prints the line, is a PASS. A script that prints a nice block nobody checked is not proof.

Read `features/README.md` for the map.

## Launch

There is no server to start. The app is one script, so launch means pick which copy to drive:

```sh
.claude/skills/verify-vps-state/run                 # this checkout
.claude/skills/verify-vps-state/run --script ~/.local/bin/vps-state
```

`run` does, in order:

1. Makes ~/.local/state/verify-vps-state/<run-id>/ and writes meta.json (script path, git shas, host).
2. Runs the doctor into doctor.txt. Exit 3 when it fails.
3. Drives the script: `--json`, `--brief`, the human block, `--can-launch chat` and `--can-launch worker`, then the SessionStart hook.
4. Reads the host again with `nproc`, /proc/loadavg, `free -b` and `df -B1 /` into live.json.
5. Scrubs nothing back, grades every check, prints one line per check and the verdict.

Exit codes: 0 PASS, 1 FAIL, 3 doctor failure.

## Doctor

doctor.txt holds one line per check, and each must pass before anything is driven:

- the script exists and is executable;
- python3, ps, free and df are on PATH, because the independent read uses them;
- /proc/loadavg is readable.

## Drive

Only `run` drives it. The script reads live /proc, so there is nothing to seed and nothing to reset. Never hand-edit ~/.local/state/vps-load/status to force a verdict: the run rewrites it from what it measured, and that rewrite is one of the checks.

Do not run it twice in the same second; run ids are whole seconds.

## Evidence

Every run keeps ~/.local/state/verify-vps-state/<run-id>/:

| File | What it proves |
| --- | --- |
| meta.json | which script, which commits, which host |
| doctor.txt | the host was worth driving |
| json.out, json.err | everything the script reported |
| brief.out, human.out | the one-liner and the block a person sees |
| can-launch-chat.code, can-launch-worker.code | the exit codes, never the claim |
| hook.out, hook.code | the SessionStart line and that the hook exits 0 fast |
| reported.json, live.json | the two reads, side by side |
| status.txt | what every fleet runner now reads |
| verdict.txt, verdict.json | one PASS/FAIL line per check, then the verdict |

Attach verdict.txt to the PR or ticket. CI runs only `tests/test_vps_state.py`; a live host read needs this server.

## Cleanup

`run` deletes nothing and starts no long-lived process. Every evidence directory stays until a person deletes it. It does rewrite ~/.local/state/vps-load/status, on purpose: that is the state every fleet runner reads.

## Gotchas

- Tolerances are part of the grade: load5 within 25%, memory within 5%, disk free and disk percentage within 2%, cores exact. A failing `load5` on a host under 40 load usually means the two reads landed in different minutes, not a broken script.
- `--can-launch` exits 3 when a core probe failed. That is a FAIL for the run, not a HOLD.
- The hook prints nothing when vps-state is missing. That is a FAIL for the `hook` check, by design.
- One run changes the status file other sessions read. Run it when the answer matters, not in a loop.
