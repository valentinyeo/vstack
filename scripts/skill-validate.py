#!/usr/bin/env python3
"""Validate skills per pstack authoring-a-skill.md (stdlib only).

Checks only what pstack skills/poteto-mode/playbooks/authoring-a-skill.md asks for:
1. Frontmatter has nonempty name and description.
2. Referenced files exist.
3. Cross-skill links resolve.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

BUILTIN_COMMANDS = frozenset({"/clear", "/rename", "/compact", "/loop"})
PSTACK_HOME = Path.home() / ".claude/plugins/cache/cursor-plugins/pstack"


def newest_pstack_skills(home: Path | None = None) -> Path | None:
    root = (home / ".claude/plugins/cache/cursor-plugins/pstack") if home else PSTACK_HOME
    if not root.is_dir():
        return None
    versions = [
        (tuple(int(n) for n in p.name.split(".") if n.isdigit()), p / "skills")
        for p in root.iterdir()
        if p.is_dir() and (p / "skills").is_dir()
    ]
    return max(versions)[1] if versions else None


def parse_frontmatter(text: str) -> tuple[dict[str, str], str, int]:
    """Return (meta, body, body_line_offset). Raises ValueError when frontmatter is absent or unclosed."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("add YAML frontmatter with name and description")
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        raise ValueError("close YAML frontmatter with ---")
    meta: dict[str, str] = {}
    block_lines = lines[1:end]
    i = 0
    while i < len(block_lines):
        line = block_lines[i]
        i += 1
        if not line.strip() or line[:1].isspace():
            continue
        key, sep, rest = line.partition(":")
        if not sep or not key.strip():
            continue
        key = key.strip().lower()
        rest = rest.strip()
        if rest in (">", ">-", ">+", "|", "|-", "|+"):
            parts = []
            while i < len(block_lines) and (not block_lines[i].strip() or block_lines[i][:1].isspace()):
                parts.append(block_lines[i].strip())
                i += 1
            meta[key] = (" ".join(p for p in parts if p) if rest.startswith(">") else "\n".join(parts).strip())
        elif len(rest) >= 2 and rest[0] in ('"', "'") and rest[-1] == rest[0]:
            meta[key] = rest[1:-1]
        else:
            meta[key] = rest
    body = "\n".join(lines[end + 1 :])
    return meta, body, end + 1


def extract_references(body: str, offset: int) -> list[tuple[int, str]]:
    """Yield (line_number, target) for markdown links and cross-skill slash references outside fences."""
    refs: list[tuple[int, str]] = []
    fence: str | None = None
    for number, line in enumerate(body.splitlines(), offset + 1):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)[0]
            fence = None if fence == token else token
            continue
        if fence is not None:
            continue
        for angled, plain in re.findall(
            r"\[[^]]*\]\((?:<([^>]+)>|([^\s)]+))(?:\s+[\"'][^\n]*[\"'])?\)", line
        ):
            refs.append((number, angled or plain))
        definition = re.match(r"^\s*\[[^]]+\]:\s*<?([^\s>]+)>?", line)
        if definition:
            refs.append((number, definition.group(1)))
        for slash in re.findall(r"`(/(?:pstack:)?[\w-]+)`", line):
            refs.append((number, slash))
    return refs


def reference_exists(target: str, skill_file: Path, root: Path, pstack_skills: Path | None) -> bool:
    if target.startswith(("http://", "https://", "mailto:", "#")):
        return True
    if any(ch in target for ch in "<>{}$*"):
        return True
    if target in BUILTIN_COMMANDS:
        return True
    if target.startswith("/pstack:"):
        if pstack_skills is None:
            return False
        return (pstack_skills / target.removeprefix("/pstack:") / "SKILL.md").is_file()
    if re.fullmatch(r"/[\w-]+", target):
        name = target[1:]
        dirs = [root / "skills", root / ".claude/skills"]
        if pstack_skills is not None:
            dirs.append(pstack_skills)
        return any((d / name / "SKILL.md").is_file() for d in dirs)
    clean = unquote(urlsplit(target).path)
    if not clean:
        return True
    if clean.startswith("pstack/") and pstack_skills is not None:
        return (pstack_skills.parent / clean.removeprefix("pstack/")).exists()
    expanded = Path(clean).expanduser()
    if expanded.is_absolute():
        return expanded.exists()
    bases = [skill_file.parent, root, root / "skills", root / ".claude/skills"]
    if pstack_skills is not None:
        bases.extend([pstack_skills, pstack_skills.parent, pstack_skills / "poteto-mode"])
    return any((base / clean).exists() for base in bases)


def validate_file(skill_file: Path, root: Path, pstack_skills: Path | None) -> list[str]:
    text = skill_file.read_text(encoding="utf-8", errors="replace")
    label = skill_file.relative_to(root).as_posix()
    problems: list[str] = []
    try:
        meta, body, offset = parse_frontmatter(text)
    except ValueError as err:
        return [f"{label}:1: {err}"]
    for field in ("name", "description"):
        if not meta.get(field, "").strip():
            problems.append(f"{label}:1: add a nonempty {field} in YAML frontmatter")
    for line_no, target in extract_references(body, offset):
        if not reference_exists(target, skill_file, root, pstack_skills):
            problems.append(f"{label}:{line_no}: unresolved reference {target}")
    return problems


def discover_skills(root: Path) -> list[Path]:
    found: list[Path] = []
    for folder in ("skills", ".claude/skills"):
        base = root / folder
        if base.is_dir():
            found.extend(sorted(base.rglob("SKILL.md")))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="SKILL.md paths; default: skills/ and .claude/skills/")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--pstack", type=Path, default=None, help="pstack skills directory")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    pstack_skills = args.pstack.resolve() if args.pstack else newest_pstack_skills()
    files = [root / f for f in args.files] if args.files else discover_skills(root)
    errors: list[str] = []
    for skill_file in files:
        errors.extend(validate_file(skill_file, root, pstack_skills))
    for err in errors:
        print(err)
    print(f"skill-validate: {'FAIL' if errors else 'PASS'} ({len(files)} skills, {len(errors)} findings)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
