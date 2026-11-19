#!/usr/bin/env python3
"""pacer-check: a PR that changes code was written by a worker, never by a Valentin-facing chat.

  pacer-check.py --body-file <file> --changed-files-file <file>
  pacer-check.py --self-test

A PR with no code file passes. A code-changing PR fails when any `Author model: <family>/<model>`
line names the anthropic family or a claude model, and fails when the body has no
`Pacer launch: <lane> <ISO time>` line. The code-file rule is the one the PreToolUse hook
hooks/pacer-guard.py enforces, imported by path because hooks/ is no package.
"""
import argparse
import importlib.machinery
import importlib.util
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / 'hooks/pacer-guard.py'
AUTHOR = re.compile(r'^Author model:[ \t]*([^/\s]+)/(\S+)', re.M)
LAUNCH = re.compile(
    r'^Pacer launch:[ \t]+\S+[ \t]+'
    r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?[ \t]*$', re.M)
# pacer-check counts an extensionless file in the shared corpus as code, because a worker writes it.
CORPUS = re.compile(r'(^|/)(bin|hooks|scripts)/.+$|(^|/)skills/[^/]+/.+$')


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


guard = load('pacer_guard', GUARD)


def code_change(path):
    """This changed path is a code file, counting an extensionless script in the shared corpus."""
    name = guard.clean(path)
    if name and not Path(name).suffix and CORPUS.search(Path(name).as_posix()):
        return True
    return guard.is_code(name)


def verdict(body, changed):
    """Why this PR fails, or None when it passes."""
    code = [path.strip() for path in changed if path.strip() and code_change(path)]
    if not code:
        return None
    reasons = []
    for family, model in AUTHOR.findall(body):
        if family.lower() == 'anthropic' or 'claude' in model.lower():
            reasons.append(f'author model {family}/{model} is a Claude family, so this chat wrote the code itself')
    if not LAUNCH.search(body):
        reasons.append('the body has no "Pacer launch: <lane> <ISO time>" line, so no worker wrote this code')
    if not reasons:
        return None
    return f'{", and ".join(reasons)}: {", ".join(code[:3])}'


def read(path):
    try:
        return Path(path).read_text(errors='replace')
    except OSError:
        return ''


def self_test():
    body = 'Author model: deepseek/deepseek-v4.1-flash\nPacer launch: vercel 2026-11-19T22:00:00Z\n'
    assert verdict(body, ['hooks/pacer-guard.py']) is None, "a worker PR passes"
    assert 'Claude family' in verdict(body.replace('deepseek', 'anthropic'), ['x.js']), "anthropic fails"
    assert 'Pacer launch' in verdict('Author model: openai/gpt-5\n', ['x.js']), "no launch line fails"
    assert verdict('Author model: anthropic/claude-opus-5-5\n', ['notes.md', 'brief.txt']) is None, "docs pass"
    assert 'Pacer launch' in verdict('Pacer launch: soon\n', ['x.py']), "an unparseable launch line counts as none"
    assert verdict(body, ['scripts/run-verifier']) is None, "an extensionless corpus script and a worker pass"
    assert 'run-verifier' in verdict('Author model: openai/gpt-5\n', ['scripts/run-verifier']), \
        "an extensionless corpus script is code"
    with tempfile.TemporaryDirectory() as where:
        script = Path(where, 'deploy')
        script.write_text('#!/bin/sh\n')
        assert code_change(str(script)), "an extensionless shebang file is code"
    print('pacer-check self-test ok')


def main():
    parser = argparse.ArgumentParser(description="a code-changing PR comes from a plan-pick worker")
    parser.add_argument('--body-file')
    parser.add_argument('--changed-files-file')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.body_file or not args.changed_files_file:
        parser.error('--body-file and --changed-files-file are both required')
    why = verdict(read(args.body_file), read(args.changed_files_file).splitlines())
    if not why:
        print('pacer-check: PASS')
        return 0
    print(f'pacer-check: FAIL {why}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
