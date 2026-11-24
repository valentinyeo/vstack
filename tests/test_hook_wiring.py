"""The CLI used by CI must reject the deletion from PR #278."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HookWiring(unittest.TestCase):
    def test_pr278_skill_update_deletion_fails_until_references_are_removed(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            # Copy shipped configuration, not home settings or this worktree's git metadata.
            for directory in ('.claude', 'hooks', 'config', 'scripts', 'skills'):
                shutil.copytree(ROOT / directory, repo / directory,
                                ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copy2(ROOT / 'install', repo / 'install')
            command = ['python3', str(ROOT / 'scripts/check-hook-paths'), '--repo', str(repo)]
            before = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(before.returncode, 0, before.stderr)
            (repo / 'hooks/skill-update.py').unlink()
            after = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(after.returncode, 1, after.stdout + after.stderr)
            self.assertIn('hooks/skill-update.py', after.stderr)
            self.assertIn('install', after.stderr)
            self.assertIn('reinstall vstack', after.stderr)
            # Skill-update is registered globally by `install`, not by project settings,
            # so the registration that must fail here is the one in `install`.
            (repo / '.claude/settings.json').write_text('{"hooks": {}}')
            install = repo / 'install'
            install.write_text('\n'.join(line for line in install.read_text().splitlines()
                                         if not line.startswith('SKILL_UPDATE_HOOK=')) + '\n')
            repaired = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(repaired.returncode, 0, repaired.stdout + repaired.stderr)


if __name__ == '__main__':
    unittest.main()
