# Verdict

Two answers, `ADD`, `CAREFUL` or `HOLD` for a chat and for a worker, each with the reasons that produced it.

## Sub-features

- `json`: `--json` parses and carries a verdict and a facts block.
- `cores`, `load5`, `mem_avail_gb`, `disk_free_gb`, `disk_used_pct`: each reported number agrees with a read by another tool, inside its tolerance.
- `exit-codes`: `--can-launch worker` and `--can-launch chat` exit with the code the verdict names, 0 ADD, 1 CAREFUL, 2 HOLD.

## How to get to it (user POV)

- Run `vps-state`. The first line is the answer: `HOLD worker, CAREFUL chat: <reasons>`.
- A script asks `vps-state --can-launch worker` and reads the exit code.
- A person who wants every number runs `vps-state --json`.

## Driving it with run

- Action: `run`. It calls the script with `--json`, with no flags, and with `--can-launch chat` and `--can-launch worker`, saving each output and exit code.
- Check: the five numbers and `cores` are compared with `live.json`, which is built from `nproc`, /proc/loadavg, `free -b` and `df -B1 /`. The exit codes are compared with the verdict inside the JSON.
- Tolerance: load5 within 25% (it moves), memory within 5%, disk free and disk percentage within 2%, cores exact.

## Gotchas

- The worker ADD rule is also the fleet runner gate in house-rules `fleet/runner`: load5/cores below 1.0 and integer gigabytes above 24. The unit test `RunnerGate` fails when the two drift, so change both or neither.
- The two reads are seconds apart. On a host near a threshold the verdict itself can flip between them, which is why the verdict is not compared, only the numbers behind it.
- `--can-launch` exits 3 when /proc/loadavg or /proc/meminfo could not be read. That is a probe failure and a FAIL here, never a quiet HOLD.
