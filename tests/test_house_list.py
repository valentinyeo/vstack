"""Ratchet for house deviations from pstack (VSTA-65).

Checks three invariants with no keyword heuristics:
  (i)  Every entry in skills/pstack-diff/house.txt quotes a verbatim sentence
       from the pinned pstack file it names.
  (ii) Every row in CLAUDE.md's rule table names either a real pstack
       `<file>: "<verbatim sentence>"` or a real `house `<id>`` from house.txt.
  (iii) Every exception has impossibility evidence and scope; feasible removals
        expire within 14 days, and no entry is past its expiry date.
  (iv) House-tagged reconcile decisions stay on the boards their stanzas name.

In CI, .github/workflows/checks.yml fetches .skill-lint.json's pstack-ref and
sets PSTACK_PINNED_DIR. Locally, falls back to the newest installed
~/.claude/plugins/cache/cursor-plugins/pstack/*.
"""
from __future__ import annotations

import datetime
import importlib.machinery
import importlib.util
import itertools
import os
import sys
from unittest.mock import patch
from pathlib import Path
import re
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "skills/pstack-diff/pstack-diff"
PSTACK_CACHE = Path.home() / ".claude/plugins/cache/cursor-plugins/pstack"

REQUIRED_FIELDS = ("id", "pstack", "quote", "change", "impossible", "scope", "basis", "approved", "expiry")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HOUSE_REF = re.compile(r"\bhouse\s+`([a-z0-9][a-z0-9-]*)`")
PSTACK_REF = re.compile(r'\bpstack\s+`([^`]+\.md)`:\s*"([^"]+)"')


def _load_pstack_diff():
    loader = importlib.machinery.SourceFileLoader("pstack_diff_house_test", str(TOOL))
    spec = importlib.util.spec_from_loader("pstack_diff_house_test", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


PSTACK_DIFF = _load_pstack_diff()


def resolve_pstack_root() -> Path:
    pinned = os.environ.get("PSTACK_PINNED_DIR")
    if pinned:
        path = Path(pinned).expanduser()
        if (path / "skills").is_dir():
            return path
        raise AssertionError(f"PSTACK_PINNED_DIR={pinned!r} has no skills/ directory")
    diff_root = os.environ.get("PSTACK_DIFF_PSTACK")
    if diff_root:
        base = Path(diff_root).expanduser()
        if (base / "skills").is_dir():
            return base
        versions = [p for p in base.glob("*") if p.is_dir() and (p / "skills").is_dir()]
        if versions:
            return max(versions, key=lambda p: tuple(int(n) for n in p.name.split(".") if n.isdigit()))
    if PSTACK_CACHE.is_dir():
        versions = [p for p in PSTACK_CACHE.glob("*") if p.is_dir() and (p / "skills").is_dir()]
        if versions:
            return max(versions, key=lambda p: tuple(int(n) for n in p.name.split(".") if n.isdigit()))
    raise AssertionError(
        f"No pinned pstack found: set PSTACK_PINNED_DIR or install pstack under {PSTACK_CACHE}"
    )


def parse_rule_table_rows(claude_md_text: str) -> list[tuple[int, str]]:
    """Return (line_number, raw_row) for every data row in CLAUDE.md's rule table."""
    lines = claude_md_text.splitlines()
    rows: list[tuple[int, str]] = []
    in_table = False
    saw_separator = False
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not in_table:
            if stripped.startswith("| Rule |") and "Enforced by" in stripped:
                in_table = True
            continue
        if not stripped.startswith("|"):
            break
        if not saw_separator:
            if re.fullmatch(r"\|[-:\s|]+\|", stripped):
                saw_separator = True
                continue
        rows.append((number, stripped))
    return rows


def check_house_entries(
    house_text: str, pstack_root: Path, today: datetime.date | None = None
) -> tuple[set[str], list[str]]:
    """Validate house.txt stanzas. Return (valid_ids, errors)."""
    today = today or datetime.date.today()
    stanzas = PSTACK_DIFF.parse_house_stanzas(house_text)
    errors: list[str] = []
    ids: set[str] = set()
    if not stanzas:
        return ids, ["house.txt has no entries"]
    for idx, stanza in enumerate(stanzas, 1):
        entry_id = stanza.get("id", "").strip()
        label = entry_id or f"stanza #{idx}"
        if not entry_id:
            errors.append(f"{label}: missing required field 'id'")
        elif entry_id in ids:
            errors.append(f"{label}: duplicate house id")
        else:
            ids.add(entry_id)
        for field in REQUIRED_FIELDS:
            if not stanza.get(field, "").strip():
                errors.append(f"{label}: missing required field '{field}'")
        pstack_rel = stanza.get("pstack", "").strip()
        quote = stanza.get("quote", "").strip()
        if pstack_rel and quote:
            target = pstack_root / pstack_rel
            if not target.is_file():
                errors.append(f"{label}: pstack file not found: {pstack_rel}")
            else:
                content = target.read_text(encoding="utf-8", errors="replace")
                if quote not in content:
                    errors.append(
                        f"{label}: quote not found verbatim in {pstack_rel}: {quote!r}"
                    )
        scope = stanza.get('scope', '').strip()
        if scope and not re.fullmatch(
                r'(?:board:(?:[1-9][0-9]*|\*)|repo:(?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+|\*)|'
                r'skill:(?:[a-z0-9][a-z0-9-]*|\*))'
                r'(?:; (?:board:(?:[1-9][0-9]*|\*)|repo:(?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+|\*)|'
                r'skill:(?:[a-z0-9][a-z0-9-]*|\*)))*', scope):
            errors.append(f'{label}: invalid scope; use board:<id|*>, repo:<owner/name|*>, skill:<name|*>')
        for date_field in ("approved", "expiry"):
            raw_date = stanza.get(date_field, "").strip()
            if not raw_date:
                continue
            if not ISO_DATE.match(raw_date):
                errors.append(f"{label}: {date_field} must be YYYY-MM-DD, got {raw_date!r}")
                continue
            try:
                parsed = datetime.date.fromisoformat(raw_date)
            except ValueError:
                errors.append(f"{label}: invalid {date_field} date {raw_date!r}")
                continue
            if date_field == "expiry" and parsed < today:
                errors.append(
                    f"{label}: entry expired on {raw_date} (today is {today.isoformat()}); "
                    "re-approve with a new expiry or drop it"
                )
        if stanza.get('impossible', '').startswith('Not impossible:'):
            try:
                approved = datetime.date.fromisoformat(stanza['approved'])
                expiry = datetime.date.fromisoformat(stanza['expiry'])
            except (KeyError, ValueError):
                continue
            if expiry > approved + datetime.timedelta(days=14):
                errors.append(f'{label}: feasible removal must expire within 14 days of approval')
    return ids, errors


def check_claude_rule_table(
    claude_text: str, house_ids: set[str], pstack_root: Path
) -> list[str]:
    """Every CLAUDE.md rule-table row names a verbatim pstack file:sentence or a house.txt id."""
    rows = parse_rule_table_rows(claude_text)
    if not rows:
        return ["CLAUDE.md: rule table not found or empty"]
    errors: list[str] = []
    for line_no, row in rows:
        house_matches = HOUSE_REF.findall(row)
        pstack_matches = PSTACK_REF.findall(row)
        if not house_matches and not pstack_matches:
            errors.append(
                f"CLAUDE.md:{line_no}: rule-table row names neither a `pstack `<file>`: \"<quote>\"` "
                f"nor a `house `<id>``: {row}"
            )
            continue
        for hid in house_matches:
            if hid not in house_ids:
                errors.append(f"CLAUDE.md:{line_no}: unknown house id '{hid}' (not in house.txt)")
        for rel_path, quote in pstack_matches:
            target = pstack_root / rel_path
            if not target.is_file():
                errors.append(f"CLAUDE.md:{line_no}: pstack file not found: {rel_path}")
            else:
                content = target.read_text(encoding="utf-8", errors="replace")
                if quote not in content:
                    errors.append(
                        f"CLAUDE.md:{line_no}: quote not found verbatim in {rel_path}: {quote!r}"
                    )
    return errors


def check_tree(repo_root: Path, pstack_root: Path, today: datetime.date | None = None) -> list[str]:
    errors: list[str] = []
    house_path = repo_root / "skills/pstack-diff/house.txt"
    if not house_path.is_file():
        errors.append("skills/pstack-diff/house.txt is missing")
        house_ids: set[str] = set()
    else:
        house_ids, house_errors = check_house_entries(
            house_path.read_text(encoding="utf-8", errors="replace"), pstack_root, today=today
        )
        errors.extend(house_errors)
    claude_path = repo_root / "CLAUDE.md"
    if not claude_path.is_file():
        errors.append("CLAUDE.md is missing")
    else:
        errors.extend(
            check_claude_rule_table(
                claude_path.read_text(encoding="utf-8", errors="replace"), house_ids, pstack_root
            )
        )
    return errors


def reconcile_scope_errors(reconcile, house_text: str) -> list[str]:
    """Drive the stage table on configured and runtime boards, including unknown ids."""
    stanzas = {row['id']: row for row in PSTACK_DIFF.parse_house_stanzas(house_text)}
    tagged = {row['reason']: row['house'] for row in reconcile.PLAN_SOURCES if 'house' in row}
    errors, exercised = set(), set()
    columns = frozenset({'Todo', 'Doing', 'Checks', 'AI Review', 'Done', 'Verification Backlog'})
    stages, names = reconcile.dynamic_stage_maps(columns, reconcile.stage_names(sections=columns))
    boards = list(reconcile.BOARDS.values()) + [
        reconcile.make_board(board_id, 'TEST', columns, (), stages, names, columns=columns)
        for board_id in (13734, 999999)
    ]
    pulls = ((), (reconcile.Pull('https://github.com/valentinyeo/vstack/pull/1',
                                'MERGED', 'green', True),),
             (reconcile.Pull('https://github.com/valentinyeo/vstack/pull/1',
                             'MERGED', 'green', False),))
    for board in boards:
        for column, alive, waiting, blocked, verification, lane_empty, prs in itertools.product(
                reconcile.column_stage_map(board), (False, True), (False, True),
                (False, True), (False, True), (False, True), pulls):
            facts = reconcile.Facts(column, 8000, alive, prs, waiting=waiting,
                                    blocked=blocked, verification=verification)
            with patch.object(reconcile, 'nothing_ran', return_value=lane_empty):
                _, reason = reconcile.target(facts, board=board)
            if reason not in tagged:
                continue
            house_id = tagged[reason]
            exercised.add(house_id)
            stanza = stanzas.get(house_id, {})
            board_scopes = [item.removeprefix('board:') for item in
                            stanza.get('scope', '').split('; ') if item.startswith('board:')]
            if not board_scopes or not any(s in ('*', str(board.id)) for s in board_scopes):
                errors.add(f'{house_id}: {reason!r} ran outside scope on board {board.id}')
    for house_id in set(tagged.values()) - exercised:
        errors.add(f'{house_id}: scope test did not exercise this tagged path')
    return sorted(errors)


class HouseListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pstack_root = resolve_pstack_root()

    def test_repo_house_list_and_claude_rule_table_pass(self):
        errors = check_tree(ROOT, self.pstack_root)
        self.assertEqual(errors, [], "\n".join(errors))

    def test_missing_impossible_or_scope_fails(self):
        house_text = (ROOT / 'skills/pstack-diff/house.txt').read_text()
        for field in ('impossible', 'scope'):
            with self.subTest(field=field):
                edited = re.sub(rf'^{field}:.*\n', '', house_text, count=1, flags=re.M)
                _, errors = check_house_entries(edited, self.pstack_root)
                self.assertTrue(any(f"missing required field '{field}'" in e for e in errors), errors)

    def test_reconcile_tagged_paths_stay_inside_house_scope(self):
        reconcile = self.load_reconcile()
        errors = reconcile_scope_errors(reconcile, (ROOT / 'skills/pstack-diff/house.txt').read_text())
        self.assertEqual(errors, [], '\n'.join(errors))

    def test_scope_check_catches_the_historical_all_board_leak(self):
        reconcile = self.load_reconcile()
        # Before VSTA-186, the post-merge proof stage leaked onto board 13734.
        with patch.object(reconcile, 'product_board', return_value=True):
            errors = reconcile_scope_errors(reconcile, (ROOT / 'skills/pstack-diff/house.txt').read_text())
        self.assertTrue(any('board-15-live-proof-stage' in e and 'board 13734' in e
                            for e in errors), errors)

    @staticmethod
    def load_reconcile():
        source = ROOT / 'skills/hypertask-work/reconcile'
        loader = importlib.machinery.SourceFileLoader('house_scope_reconcile', str(source))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[loader.name] = module
        loader.exec_module(module)
        return module

    def test_invalid_scope_fails(self):
        house_text = (ROOT / 'skills/pstack-diff/house.txt').read_text()
        edited = re.sub(r'^scope:.*$', 'scope: everywhere', house_text, count=1, flags=re.M)
        _, errors = check_house_entries(edited, self.pstack_root)
        self.assertTrue(any('invalid scope' in e for e in errors), errors)

    def test_feasible_removal_cannot_keep_a_long_expiry(self):
        house_text = (ROOT / 'skills/pstack-diff/house.txt').read_text()
        edited = house_text.replace('expiry: 2026-12-08', 'expiry: 2027-02-23', 1)
        _, errors = check_house_entries(edited, self.pstack_root)
        self.assertTrue(any('within 14 days' in e for e in errors), errors)

    def test_narrowed_scope_rejects_an_existing_execution(self):
        house_text = (ROOT / 'skills/pstack-diff/house.txt').read_text()
        edited = house_text.replace('scope: board:15;', 'scope: board:2060;')
        self.assertNotEqual(edited, house_text)
        errors = reconcile_scope_errors(self.load_reconcile(), edited)
        self.assertTrue(any('board-15-live-proof-stage' in e and 'board 15' in e
                            for e in errors), errors)

    def test_missing_or_paraphrased_quote_fails(self):
        house_text = (ROOT / "skills/pstack-diff/house.txt").read_text(encoding="utf-8")
        # Delete the quote line from the first stanza.
        lines = house_text.splitlines()
        removed = False
        edited = []
        for line in lines:
            if not removed and line.startswith("quote:"):
                removed = True
                continue
            edited.append(line)
        self.assertTrue(removed)
        _, errors = check_house_entries("\n".join(edited), self.pstack_root)
        self.assertTrue(any("missing required field 'quote'" in e for e in errors), errors)

        # Alter a quote so it is no longer verbatim.
        quote = PSTACK_DIFF.parse_house_stanzas(house_text)[0]['quote']
        altered = house_text.replace('quote: ' + quote, 'quote: A fabricated pstack rule.', 1)
        _, errors = check_house_entries(altered, self.pstack_root)
        self.assertTrue(any("quote not found verbatim" in e for e in errors), errors)

    def test_expired_entry_fails(self):
        house_text = (ROOT / "skills/pstack-diff/house.txt").read_text(encoding="utf-8")
        _, errors = check_house_entries(
            house_text, self.pstack_root, today=datetime.date(2027, 2, 24)
        )
        self.assertTrue(any("entry expired on 2027-02-23" in e for e in errors), errors)

    def test_claude_row_without_pstack_or_house_id_fails(self):
        claude_md = (
            "| Rule | Enforced by |\n"
            "|---|---|\n"
            "| Flaky checks are never rerun to pass | `skills/valentin-mode/SKILL.md` |\n"
        )
        errors = check_claude_rule_table(claude_md, {"pacer-check"}, self.pstack_root)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("names neither", errors[0])

    def test_claude_row_with_unknown_house_id_fails(self):
        claude_md = (
            "| Rule | Enforced by |\n"
            "|---|---|\n"
            "| Made up rule (house `no-such-id`) | `hooks/x.py` |\n"
        )
        errors = check_claude_rule_table(claude_md, {"pacer-check"}, self.pstack_root)
        self.assertTrue(any("unknown house id 'no-such-id'" in e for e in errors), errors)

    def test_claude_row_with_non_verbatim_pstack_quote_fails(self):
        claude_md = (
            "| Rule | Enforced by |\n"
            "|---|---|\n"
            '| Invented rule (pstack `skills/poteto-mode/worker.md`: "Never rerun checks to pass.") | `hooks/x.py` |\n'
        )
        errors = check_claude_rule_table(claude_md, set(), self.pstack_root)
        self.assertTrue(any("quote not found verbatim" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
