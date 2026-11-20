# gh wrapper

One shared GitHub token serves every chat on this box, with 5000 requests an hour. This
wrapper sits at `/usr/bin/gh` in front of the real binary, `/usr/bin/gh.real`, and answers
repeated reads from a folder on disk instead of spending a request.

It lives here so the changes are reviewable. The file deployed at `/usr/bin/gh` is a copy of
`tools/gh-wrapper/gh`.

## What it caches

| Command | Cached | For |
|---|---|---|
| `gh api` REST GET | yes | 5 minutes, ETag revalidation |
| `gh pr checks`, `gh pr view`, `gh pr list`, `gh pr status` | yes | 60 seconds |
| every other command | no | passed straight through |

`gh pr checks`, `view`, `list` and `status` are GraphQL calls, so the older REST snapshot
never covered them. They were the bulk of the spent budget.

Each `pr` answer is stored whole: stdout, stderr and the exit code, so a cached call behaves
exactly like the live one, including `gh pr checks` exit code 8 for "still pending" and the
warnings `pr view` writes to stderr. A key holds the full argv, the repo (from `-R` or
this folder's `origin` remote) and a 16 character hash of the credential. The credential
itself is never written; only that hash, so two tokens never share a body and no token
reaches a cache file or the log.

Writes are never cached: `create`, `merge`, `edit`, `close`, `comment`, `review`, `ready`,
`update-branch`, `diff` and anything else that is not one of the four reads go through.

Concurrency: one lock per key, then a second look at the cache under the lock. Twenty chats
asking for the same PR at the same moment make one upstream call and share the answer.

## `--watch`

`gh.real pr checks --watch` polls on its own interval, each poll a fresh GraphQL call, and
none of it passed through this wrapper or its log. The wrapper now runs the loop itself on
top of the cache: it never passes `--watch` to `gh.real`, polls at `max(--interval, 60)`
seconds, prints the same header and table gh prints, and stops when no check is pending.
Exit codes match gh: 0 all passed, 1 a check failed, `--fail-fast` stops on the first
failure instead of waiting for the rest.

## Pruning

The old folder grew to 138,964 files and 56 GB with nothing deleting anything. Now every
call does at most one prune per 10 minutes, and each prune looks at the folder for at most
2 seconds, so a large backlog drains across normal traffic instead of blocking a call:

- entries whose mtime is more than 1 day old are deleted;
- the folder is capped at 2 GB, oldest deleted first.

To clear a backlog in one go, as the orchestrator does after deploying:

```bash
GH_WRAPPER_PRUNE=1 gh
```

It prints `removed N entries, freed N bytes, seen N`. It never deletes `pause-until`,
`prune-stamp` or a lock file, only cache entries named as 64 hex characters.

## Deploy

The orchestrator deploys after review, not the worker. On the box that runs the wrapper:

```bash
sudo cp -p /usr/bin/gh /usr/bin/gh.prune-backup   # once, before the first deploy
sudo install -m 755 tools/gh-wrapper/gh /usr/bin/gh
sudo GH_WRAPPER_PRUNE=1 gh.real --version >/dev/null   # sanity: the real binary still runs
GH_WRAPPER_PRUNE=1 gh
```

Roll back:

```bash
sudo install -m 755 /usr/bin/gh.prune-backup /usr/bin/gh
```

## Reading the hit rate

The log is `~/.local/state/gh-call-log/calls.tsv`, still tab separated, still six columns in
the same order, with a seventh added:

```
epoch  caller  method  path  bucket  session  marker
```

`marker` is `hit`, `miss` or `-` for calls the cache does not cover. So:

```bash
# hit rate over the last hour
awk -F'\t' -v now="$(date +%s)" '$1>now-3600 && $3=="pr"{n++; if($7=="hit") h++} END{printf "%d pr calls, %d hits, %.0f%%\n", n, h, 100*h/n}' \
  ~/.local/state/gh-call-log/calls.tsv

# where the misses still come from
awk -F'\t' -v now="$(date +%s)" '$1>now-3600 && $3=="pr" && $7=="miss"{print $4}' \
  ~/.local/state/gh-call-log/calls.tsv | cut -d' ' -f1-2 | sort | uniq -c | sort -rn | head
```

## What the change saves

Replay of the real log, offline, in `tools/gh-wrapper/replay.py`:

```bash
python3 tools/gh-wrapper/replay.py --seconds 3600              # the last hour in the log
python3 tools/gh-wrapper/replay.py --seconds 3600 --end 1795180440   # the busiest hour
```

| Window | pr calls before | after | saved |
|---|---|---|---|
| the log's last hour (2168 invocations, 36 writes) | 2168 per hour | 1520 per hour | 29.9% |
| busiest hour in the log, `--end 1795180440` (7539 invocations, 176 writes) | 7539 per hour | 5101 per hour | 32.3% |

The log is live, so a rerun moves these numbers slightly.

Both numbers are estimates. The old logger cut the argv column at 160 characters and never
recorded the cwd, so some distinct calls collapse into one key here. The bigger omission runs
the other way: gh.real's own watch polls never reached calls.tsv, so the real "before" figure
is higher than the replay shows. In the busiest hour the log has 13 `--watch` calls at
20 to 30 second intervals; each of those polled GitHub itself and none of it was logged. Each
such watch now costs at most one upstream call a minute.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `GH_REAL` | `/usr/bin/gh.real` | the real binary |
| `HT_GH_CACHE_DIR` | `~/.local/state/gh-shared-cache` | where entries live |
| `GH_WRAPPER_TTL` | `60` | seconds a `pr` read stays fresh |
| `GH_WRAPPER_NO_CACHE` | unset | `1` bypasses the cache |
| `--no-cache` | absent | bypasses the cache for one call |
| `GH_WRAPPER_PRUNE` | unset | `1` prunes to completion and exits |
| `GH_CALL_LOG` | `~/.local/state/gh-call-log/calls.tsv` | the log |

## Tests

`tests/test_gh_wrapper.py` drives the real wrapper against a fake `gh.real` that counts its
own invocations: ten concurrent `pr checks` making one upstream call, writes never cached,
exit code and stderr replayed, watch sleeping 60 seconds on `--interval 10`, prune by age and
by size, and no token in any cache file or log line.

```bash
timeout 600 python3 -m unittest discover -s tests -p 'test_gh_wrapper.py'
```
