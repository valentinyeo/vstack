#!/usr/bin/env python3
"""vstack tools must act only on the chat that runs them, not the whole fleet."""
from __future__ import annotations

import datetime
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / 'config/cross-chat-allowlist.txt'
SCAN_ROOTS = ('skills', 'tools', 'scripts')
FAIL_HINT = (
    'vstack tools act only on the chat that runs them. '
    'Make it run per chat (like pr-queue --mine), or add a line to '
    'config/cross-chat-allowlist.txt with a reason.'
)

# Plain cross-chat calls: any hit in a non-allowlisted file fails.
REACH = (
    (re.compile(r'mp-send'), 'mp-send'),
    (re.compile(r'mp-sessions'), 'mp-sessions'),
    (re.compile(r'roster-live'), 'roster-live'),
    (re.compile(r'multiprompt/agent-host'), 'multiprompt/agent-host'),
    (re.compile(r'tmux[\s\'"].*send-keys|send-keys'), 'tmux send-keys'),
    (re.compile(r'SendMessage'), 'SendMessage'),
    (re.compile(r'cc-socks'), 'cc-socks'),
)
GH_PR = re.compile(r'gh\s+pr\s+(merge|close|comment)\b')
# A script that writes PRs on GitHub must scope to this chat (see pr-queue --mine).
GH_SELF = re.compile(
    r'--mine\b|args\.mine|add_argument\([^)]*--mine|'
    r'only PRs owned by this live chat',
    re.I,
)


def parse_allowlist(text: str) -> dict[str, dict]:
    """path -> {reach, reason, expiry, approved}"""
    entries = {}
    for line in text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith('#'):
            continue
        parts = [part.strip() for part in raw.split('|')]
        if len(parts) != 5:
            raise ValueError(f'allowlist line needs five fields: {raw!r}')
        path, reach, reason, expiry, approved = parts
        if approved != 'approved-by: Valentin':
            raise ValueError(f'allowlist line missing Valentin approval: {raw!r}')
        entries[path] = {'reach': reach, 'reason': reason, 'expiry': expiry, 'approved': approved}
    return entries


def expired(expiry: str, today: datetime.date) -> bool:
    if expiry == 'never':
        return False
    try:
        end = datetime.date.fromisoformat(expiry)
    except ValueError as error:
        raise ValueError(f'bad expiry {expiry!r}') from error
    return today > end


def validate_allowlist(entries: dict[str, dict], today: datetime.date) -> list[str]:
    problems = []
    for path, meta in sorted(entries.items()):
        file_path = ROOT / path
        if not file_path.is_file():
            problems.append(f'allowlist {path}: file no longer exists ({meta["reach"]})')
        if expired(meta['expiry'], today):
            problems.append(f'allowlist {path}: expiry {meta["expiry"]} passed ({meta["reach"]})')
    return problems


def iter_scan_files() -> list[Path]:
    found = []
    for name in SCAN_ROOTS:
        base = ROOT / name
        if not base.is_dir():
            continue
        for path in sorted(base.rglob('*')):
            if not path.is_file():
                continue
            if path.suffix.lower() in {'.md', '.markdown', '.pyc', '.pyo'}:
                continue
            if '__pycache__' in path.parts:
                continue
            found.append(path)
    return found


def hits_in_text(text: str) -> list[str]:
    """Named pattern hits in file text."""
    matched = []
    for pattern, label in REACH:
        if pattern.search(text):
            matched.append(label)
    if GH_PR.search(text) and not GH_SELF.search(text):
        matched.append('gh pr merge/close/comment without --mine or author filter')
    return matched


def violations_for_rel(rel: str, text: str, allowed: set[str]) -> list[str]:
    if rel in allowed:
        return []
    lines = []
    for label in hits_in_text(text):
        lines.append(f'{rel}: matched {label!r}. {FAIL_HINT}')
    return lines


def scan_repo(allowed: set[str]) -> list[str]:
    violations = []
    for path in iter_scan_files():
        rel = path.relative_to(ROOT).as_posix()
        try:
            text = path.read_text(errors='replace')
        except OSError as error:
            violations.append(f'{rel}: cannot read: {error}')
            continue
        violations.extend(violations_for_rel(rel, text, allowed))
    return violations


class OwnChatOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = parse_allowlist(ALLOWLIST.read_text())
        cls.allowed = set(cls.entries)

    def test_allowlist_file_valid(self):
        problems = validate_allowlist(self.entries, datetime.date.today())
        self.assertEqual(problems, [], '\n'.join(problems))

    def test_skills_tools_scripts_stay_own_chat(self):
        violations = scan_repo(self.allowed)
        self.assertEqual(violations, [], '\n'.join(violations))

    def test_past_fleet_report_snippet_would_fail(self):
        """Real past mistake (VSTA-92 fleet-report): mp-sessions across every live chat."""
        snippet = subprocess.check_output(
            ['git', 'show', '44c4480:skills/fleet-report/fleet-report'],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        rel = 'skills/fleet-report/fleet-report'
        hits = violations_for_rel(rel, snippet, self.allowed)
        self.assertTrue(hits, 'expected fleet-report snippet to trip cross-chat scan')
        self.assertTrue(any('mp-sessions' in line for line in hits), hits)


if __name__ == '__main__':
    unittest.main()