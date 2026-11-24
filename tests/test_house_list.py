"""Ratchet for house deviations from pstack (VSTA-65).

Checks three invariants with no keyword heuristics:
  (i)  Every entry in skills/pstack-diff/house.txt quotes a verbatim sentence
       from the pinned pstack file it names.
  (ii) Every row in CLAUDE.md's rule table names either a real pstack
       `<file>: "<verbatim sentence>"` or a real `house `<id>`` from house.txt.
  (iii) No house.txt entry is past its expiry date.

In CI, .github/workflows/checks.yml fetches .skill-lint.json's pstack-ref and
sets PSTACK_PINNED_DIR. Locally, falls back to the newest installed
~/.claude/plugins/cache/cursor-plugins/pstack/*.
"""
from __future__ import annotations

import datetime
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import re
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "skills/pstack-diff/pstack-diff"
PSTACK_CACHE = Path.home() / ".claude/plugins/cache/cursor-plugins/pstack"

REQUIRED_FIELDS = ("id", "pstack", "quote", "change", "basis", "approved", "expiry")
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


class HouseListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pstack_root = resolve_pstack_root()

    def test_repo_house_list_and_claude_rule_table_pass(self):
        errors = check_tree(ROOT, self.pstack_root)
        self.assertEqual(errors, [], "\n".join(errors))

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
        altered = house_text.replace("Opening a PR does not start a babysit.", "Opening a PR never starts babysit.", 1)
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
