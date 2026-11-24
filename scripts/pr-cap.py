#!/usr/bin/env python3
"""Open pull request cap for the repos whose CLAUDE.md says commit straight to master (VSTA-204).

valentinyeo/multiprompt held 77 open pull requests on 24 Nov 2026 while its own CLAUDE.md
says commit small units to master and open no new PRs. One table here holds the repos and
the cap. hooks/pr-cap-guard.py asks `block(repo)` before every `gh pr create`,
`gh api ... /pulls -X POST` and MCP `create_pull_request`; scripts/worker-shims writes a
`gh` shim that asks the same module, so a Claude chat and a plan-pick worker read one answer.

A read failure fails open with one warning line: a GitHub outage must never stop work.

  pr-cap.py --count REPO   print the open count (the 5 minute cache applies)
  pr-cap.py --self-test
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

CAP = 10
REPOS = {
    'valentinyeo/multiprompt': CAP,
    'valentinyeo/multiprompt-android': CAP,
}
FIX = "commit small units to master per the repo's CLAUDE.md; close or land open PRs first"
TTL = 300
TIMEOUT = 20
MESSAGE = ('BLOCKED by pr-cap: {repo} has {count} open pull requests, above the cap of {cap}. '
           '{fix}. No pull request was opened.')

_warned = set()


def state_dir():
    return Path.home() / '.local/state/vstack/pr-cap'


def warn_once(repo, detail):
    """One line on stderr per repo per run; a repeated failure stays quiet."""
    if repo in _warned:
        return
    _warned.add(repo)
    print(f'pr-cap: cannot read open PR count for {repo} ({detail}); allowing this one',
          file=sys.stderr)


def read_cache(repo, now, directory=None):
    try:
        saved = json.loads(((directory or state_dir()) / (repo.replace('/', '-') + '.json')).read_text())
        count = int(saved['count'])
        at = float(saved['at'])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not 0 <= now - at < TTL:
        return None
    return count


def write_cache(repo, count, now, directory=None):
    path = (directory or state_dir()) / (repo.replace('/', '-') + '.json')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'count': count, 'at': now}))
    except OSError:
        pass  # A full or read-only state directory must not block work either.


def one_call(repo):
    """`gh api` search asks GitHub for the open PR total in one request."""
    return subprocess.run(
        ['gh', 'api', '-X', 'GET', 'search/issues',
         '-f', f'q=repo:{repo} type:pr state:open', '--jq', '.total_count'],
        capture_output=True, text=True, timeout=TIMEOUT)


def open_count(repo, now=None, run=None, directory=None):
    """Open pull requests on REPO, or None when the read failed (fail open)."""
    now = time.time() if now is None else now
    cached = read_cache(repo, now, directory)
    if cached is not None:
        return cached
    run = run or one_call
    try:
        result = run(repo)
    except (OSError, subprocess.SubprocessError) as error:
        warn_once(repo, str(error).splitlines()[0] if str(error) else type(error).__name__)
        return None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or f'exit {result.returncode}').strip()
        warn_once(repo, detail.splitlines()[0][:160] if detail else f'exit {result.returncode}')
        return None
    try:
        count = int((result.stdout or '').strip())
    except ValueError:
        warn_once(repo, f'unreadable count {(result.stdout or "").strip()[:40]!r}')
        return None
    if count < 0:
        warn_once(repo, f'unreadable count {count}')
        return None
    write_cache(repo, count, now, directory)
    return count


def block(repo, now=None, run=None, directory=None):
    """The refusal for one repo above its cap, or None for another repo or a count at the cap."""
    if repo not in REPOS:
        return None
    count = open_count(repo, now=now, run=run, directory=directory)
    if count is None or count <= REPOS[repo]:
        return None
    return MESSAGE.format(repo=repo, count=count, cap=REPOS[repo], fix=FIX)


def self_test():
    assert set(REPOS.values()) == {CAP}, 'every listed repo carries the one cap'
    repo = sorted(REPOS)[0]
    at_cap = subprocess.CompletedProcess([], 0, str(CAP), '')
    over = subprocess.CompletedProcess([], 0, str(CAP + 1), '')
    with tempfile.TemporaryDirectory() as scratch:
        cache = Path(scratch)
        now = time.time()
        assert block(repo, now=now, run=lambda name: over, directory=cache) is not None, 'one over the cap blocks'
        later = now + TTL + 1
        assert block(repo, now=later, run=lambda name: at_cap, directory=cache) is None, 'the cap itself passes'
        assert block('valentinyeo/other', now=now, run=lambda name: over, directory=cache) is None, 'another repo passes'
        calls = []
        assert open_count(repo, now=later + 1, run=lambda name: calls.append(name) or at_cap,
                          directory=cache) is not None
        assert calls == [], 'a cached count makes no second call'
    print('pr-cap self-test ok')
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ['--self-test']:
        return self_test()
    if len(argv) == 2 and argv[0] == '--count':
        count = open_count(argv[1])
        print('unknown' if count is None else count)
        return 0 if count is not None else 1
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
