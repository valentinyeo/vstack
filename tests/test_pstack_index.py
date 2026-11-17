"""The generated inventory follows installed versions without drift."""
import runpy
import tempfile
import unittest
from pathlib import Path

INDEX = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/pstack-index'))


class Inventory(unittest.TestCase):
    def test_descriptions_exclude_yaml_and_code_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = [
                ('SKILL.md', '---\ndescription: >-\n  Build custom tools.\n---\n', 'Build custom tools.'),
                ('types.ts', 'export type Thing = string;\n/**\n *\n */\n', 'types'),
                ('statechart', '#!/bin/sh\ncase $link in\n    /*) self=$link ;;\nesac\n', 'statechart'),
            ]
            for name, text, expected in cases:
                with self.subTest(name=name):
                    path = root / name
                    path.write_text(text)
                    self.assertEqual(INDEX['description'](path), expected)
                    path.unlink()

    def test_newest_idempotent_and_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / 'cache'
            output = Path(tmp) / 'index.md'
            for version in ['0.9.99', '0.15.43']:
                root = cache / version
                files = {
                    'skills/correct/SKILL.md': '---\nname: correct\ndescription: Prevent repeated mistakes.\n---\n# Correct\n',
                    'skills/principle-proof/SKILL.md': '# Proof\n\nDrive real commands.\n',
                    'skills/poteto-mode/playbooks/shipping.md': '# Shipping\n\nMerge verified changes.\n',
                    'skills/poteto-mode/scripts/watch-pr/watch-pr': '#!/bin/sh\n# Watch pull requests.\n',
                    'skills/poteto-mode/scripts/node_modules/vendor/index.js': '// Exclude vendor code.\n',
                }
                for name, text in files.items():
                    p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
            render = INDEX['refresh'](cache, output)
            self.assertIn('pstack 0.15.43', render)
            for name in ['correct', 'principle-proof', 'shipping.md', 'scripts/watch-pr/watch-pr', 'Watch pull requests.']:
                self.assertIn(name, render)
            self.assertNotIn('vendor', render)
            before = output.stat().st_mtime_ns
            self.assertEqual(INDEX['refresh'](cache, output), render)
            self.assertEqual(output.stat().st_mtime_ns, before)
            newer = cache / '0.16.0/skills/new/SKILL.md'
            newer.parent.mkdir(parents=True); newer.write_text('# New\n')
            updated = INDEX['refresh'](cache, output)
            self.assertIn('pstack 0.16.0', updated)
            self.assertNotIn('shipping.md', updated)


if __name__ == '__main__':
    unittest.main()
