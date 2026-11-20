#!/usr/bin/env python3
"""Replay a slice of calls.tsv through the wrapper's pr cache rules, offline.

Every `gh pr` line in the log reached GitHub, because no pr subcommand was cached: the
api snapshot in the wrapper covers REST GETs only, and `pr checks`, `view`, `list` and
`status` are GraphQL. This script takes a real slice of the log, keys each line the way
tools/gh-wrapper/gh now keys it (full argv, repo, credential) and applies the same 60 second
ttl, then counts the lines that would still reach GitHub. It makes no network call and runs
no gh.

  tools/gh-wrapper/replay.py --log ~/.local/state/gh-call-log/calls.tsv --seconds 3600

Columns in calls.tsv: epoch, caller, method, path, bucket, session, marker. The path column
was already cut to 160 characters by the old logger, and the log holds no cwd, so two calls
that differed only after 160 characters, or differed only by folder, collapse into one key
here. The credential identity is the bucket column, which is as close as the log comes.
"""
import argparse
import collections
import gzip
import sys
from pathlib import Path

READ_SUBS = {"checks", "view", "list", "status"}
BYPASS_FLAGS = {"--web", "-w", "--no-cache"}
TTL = 60


def repo_of(argv):
    words = argv.split()
    for index, word in enumerate(words):
        if word in ("-R", "--repo") and index + 1 < len(words):
            return words[index + 1]
        if word.startswith("--repo="):
            return word.split("=", 1)[1]
    return "-"


def sub_of(argv):
    words = argv.split()
    return words[1] if len(words) > 1 else ""


def cacheable(argv):
    words = argv.split()
    return sub_of(argv) in READ_SUBS and not (set(words) & BYPASS_FLAGS)


def _log_slices(path):
    """Yield line iterators oldest-first: .2.gz, .1.gz, then the live file."""
    log = Path(path)
    parent, name = log.parent, log.name
    for piece in (name + ".2.gz", name + ".1.gz", name):
        target = parent / piece
        if not target.exists():
            continue
        if piece.endswith(".gz"):
            with gzip.open(target, "rt", encoding="utf-8", errors="replace") as handle:
                yield handle
        else:
            with open(target, encoding="utf-8", errors="replace") as handle:
                yield handle


def rows(path, seconds=None, end=None):
    for handle in _log_slices(path):
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 4 or fields[2] != "pr":
                continue
            try:
                when = int(fields[0])
            except ValueError:
                continue
            yield when, fields[3], fields[4] if len(fields) > 4 else "-"


def replay(path, seconds, end=None):
    picked = list(rows(path, seconds, end))
    if not picked:
        return None
    last = end or max(when for when, _argv, _bucket in picked)
    first = last - seconds
    window = [(when, argv, bucket) for when, argv, bucket in picked if when >= first]
    seen = {}
    before = after = 0
    writes = 0
    subs = collections.Counter()
    misses = collections.Counter()
    for when, argv, bucket in window:
        before += 1
        subs[sub_of(argv)] += 1
        if not cacheable(argv):
            writes += 1
            after += 1
            continue
        key = (argv, repo_of(argv), bucket)
        fetched = seen.get(key)
        if fetched is not None and 0 <= when - fetched < TTL:
            continue
        seen[key] = when
        after += 1
        misses[sub_of(argv)] += 1
    return {
        "from": first,
        "to": last,
        "window": window,
        "before": before,
        "after": after,
        "writes": writes,
        "distinct": len({(argv, repo_of(argv), bucket) for _w, argv, bucket in window}),
        "subs": subs,
        "misses": misses,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Estimate what the gh pr cache saves, from the real log.")
    parser.add_argument("--log", default=str(Path.home() / ".local/state/gh-call-log/calls.tsv"))
    parser.add_argument("--seconds", type=int, default=3600, help="window length ending at the last log line")
    parser.add_argument("--end", type=int, default=None, help="window end epoch, default the last log line")
    parser.add_argument("--per-hour", action="store_true", help="also print a per hour rate over the window")
    options = parser.parse_args(argv)
    result = replay(options.log, options.seconds, options.end)
    if result is None:
        sys.stdout.write("no pr calls in %s\n" % options.log)
        return 1
    hours = max(1e-9, (result["to"] - result["from"]) / 3600.0)
    hits = result["before"] - result["after"]
    rate = 100.0 * hits / result["before"] if result["before"] else 0.0
    out = sys.stdout
    out.write("window: %d .. %d (%.2f h)\n" % (result["from"], result["to"], hours))
    out.write("pr calls before: %d  (%.0f per hour)\n" % (result["before"], result["before"] / hours))
    out.write("pr calls after:  %d  (%.0f per hour)\n" % (result["after"], result["after"] / hours))
    out.write("cached hits:     %d  (%.1f%% of pr calls)\n" % (hits, rate))
    out.write("writes, never cached: %d\n" % result["writes"])
    out.write("distinct keys in window: %d\n" % result["distinct"])
    for name, count in result["subs"].most_common():
        out.write("  %-8s %5d calls, %5d still upstream\n" % (name, count, result["misses"][name]))
    out.write("estimate only: the log cuts argv at 160 characters and holds no cwd.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
