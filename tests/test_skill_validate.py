"""Tests for scripts/skill-validate.py (pstack authoring-a-skill.md validation)."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/skill-validate.py"


def run_validator(repo: Path, pstack_skills: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT), "--root", str(repo)]
    if pstack_skills is not None:
        cmd.extend(["--pstack", str(pstack_skills)])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


class SkillValidateTests(unittest.TestCase):
    def make_tree(self, files: dict[str, str]) -> tuple[Path, Path]:
        holder = tempfile.TemporaryDirectory(prefix="skill-validate-")
        self.addCleanup(holder.cleanup)
        base = Path(holder.name)
        repo = base / "repo"
        pstack = base / "pstack/skills"
        repo.mkdir()
        (pstack / "unslop").mkdir(parents=True)
        (pstack / "unslop/SKILL.md").write_text("---\nname: unslop\ndescription: Cut AI tells.\n---\n")
        for rel, content in files.items():
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        return repo, pstack

    def test_valid_skill_passes(self):
        repo, pstack = self.make_tree({
            "skills/demo/SKILL.md": (
                "---\nname: demo\ndescription: A valid demo skill.\n---\n\n"
                "See [guide](references/guide.md), `/other`, and `/pstack:unslop`.\n"
            ),
            "skills/demo/references/guide.md": "# guide\n",
            "skills/other/SKILL.md": "---\nname: other\ndescription: Target skill.\n---\n",
        })
        result = run_validator(repo, pstack)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_name_or_description_fails(self):
        repo, pstack = self.make_tree({
            "skills/bad/SKILL.md": "---\nname: bad\n---\n\nBody.\n",
        })
        result = run_validator(repo, pstack)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("nonempty description", result.stdout)

    def test_missing_referenced_file_fails(self):
        repo, pstack = self.make_tree({
            "skills/bad/SKILL.md": (
                "---\nname: bad\ndescription: Broken local link.\n---\n\n"
                "Read [missing](references/nope.md).\n"
            ),
        })
        result = run_validator(repo, pstack)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("unresolved reference references/nope.md", result.stdout)

    def test_unresolved_cross_skill_link_fails(self):
        repo, pstack = self.make_tree({
            "skills/bad/SKILL.md": (
                "---\nname: bad\ndescription: Broken skill link.\n---\n\n"
                "Run `/no-such-skill` or `/pstack:no-such`.\n"
            ),
        })
        result = run_validator(repo, pstack)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("unresolved reference /no-such-skill", result.stdout)
        self.assertIn("unresolved reference /pstack:no-such", result.stdout)

    def test_repo_skills_pass_validation(self):
        result = run_validator(ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
