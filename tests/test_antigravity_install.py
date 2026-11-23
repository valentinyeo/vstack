"""install links valentin-mode for Antigravity and merges global hooks."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AntigravityInstallTest(unittest.TestCase):
    def test_install_links_gemini_skill_paths_and_merges_hooks(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            share = home / '.local' / 'share' / 'vstack'
            os.makedirs(home / '.claude' / 'hooks', exist_ok=True)
            env = {
                **os.environ,
                'HOME': str(home),
                'VSTACK_INSTALL_ANYWHERE': '1',
                'VSTACK_DIR': str(share),
            }
            subprocess.run([str(ROOT / 'install')], check=True, env=env, cwd=ROOT)
            for tail in (
                '.gemini/antigravity-cli/skills/valentin-mode',
                '.gemini/config/skills/valentin-mode',
                '.agents/skills/valentin-mode',
            ):
                link = home / tail
                self.assertTrue(link.is_symlink(), tail)
                installed = (link / 'SKILL.md').read_text()
                source = (ROOT / 'skills/valentin-mode/SKILL.md').read_text()
                self.assertEqual(installed.split('\n---', 1)[1], source.split('\n---', 1)[1])
                self.assertIn('hooks/run-hook', installed)
                self.assertTrue((link / 'context.py').samefile(ROOT / 'skills/valentin-mode/context.py'))
            hooks = json.loads((home / '.gemini/config/hooks.json').read_text())
            block = hooks.get('vstack-valentin-mode', {})
            self.assertIn('PreToolUse', block)
            self.assertIn('Stop', block)
            joined = json.dumps(block)
            self.assertIn('context.py', joined)
            self.assertIn('idle-stop.py', joined)

    def test_context_self_test_passes(self):
        result = subprocess.run(
            ['python3', str(ROOT / 'skills/valentin-mode/context.py'), '--self-test'],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn('self-test ok', result.stdout)

    def test_merge_script_self_test(self):
        result = subprocess.run(
            ['python3', str(ROOT / 'scripts/merge-antigravity-hooks.py'), '--self-test'],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()