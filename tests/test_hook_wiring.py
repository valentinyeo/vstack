"""CI fails when a settings file or the installer names a hook the repo does not have.

#278 deleted twelve hooks and left every chat whose settings named one with no working
Bash call, because a bare `python3 ~/.claude/hooks/<deleted>.py` exits 2 and Claude Code
reads exit 2 as a block. Nothing failed in between. Now deleting a script fails CI until
its wiring is gone too (pstack principle-migrate-callers-then-delete-legacy-apis).

The scan covers every file vstack installs or documents: tracked `.claude/settings*.json`,
any setup doc that rewrites a hook command, and the `install` script's own link lines.
"""
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMAND = re.compile(r'"command"\s*:\s*"((?:[^"\\]|\\.)*)"')
HOOK_REF = re.compile(r'/hooks/([A-Za-z0-9_.-]+)')
INSTALLER_REF = re.compile(r'\$ROOT/hooks/([A-Za-z0-9_.-]+)')


def wiring_files(root):
    """Tracked settings JSON, plus every doc that registers a hook command."""
    files = sorted(root.glob('.claude/settings*.json'))
    for path in sorted(root.rglob('*.md')):
        if '.git' in path.parts:
            continue
        if '"command"' in path.read_text(errors='ignore'):
            files.append(path)
    return files


def missing_hooks(root):
    """(file, hook name) for every registration whose script the repo does not have."""
    missing = []
    for path in wiring_files(root):
        for command in COMMAND.findall(path.read_text(errors='ignore')):
            for name in HOOK_REF.findall(command):
                if not (root / 'hooks' / name).is_file():
                    missing.append((path.relative_to(root).as_posix(), name))
    installer = root / 'install'
    if installer.is_file():
        for name in INSTALLER_REF.findall(installer.read_text()):
            if not (root / 'hooks' / name).is_file():
                missing.append(('install', name))
    return missing


def settings(*commands):
    return json.dumps({'hooks': {'PreToolUse': [
        {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': command}
                                      for command in commands]}]}})


class HookWiring(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'hooks').mkdir()
        (self.root / 'hooks/live.py').write_text('')
        (self.root / '.claude').mkdir()

    def test_every_registered_hook_exists_in_the_repo(self):
        self.assertEqual(missing_hooks(ROOT), [],
                         'a settings file or install line names a hook script this repo '
                         'does not have; restore the script or delete its wiring')

    def test_it_catches_the_278_state(self):
        """The shape of #278: settings keep calling plan-pick-only.py after its deletion."""
        (self.root / '.claude/settings.json').write_text(settings(
            '/usr/bin/python3 "$CLAUDE_PROJECT_DIR"/hooks/live.py',
            "sh -c 'f=\"$HOME/.claude/hooks/plan-pick-only.py\"; [ -f \"$f\" ] || exit 0; "
            'exec python3 "$f"'))
        self.assertEqual(missing_hooks(self.root),
                         [('.claude/settings.json', 'plan-pick-only.py')])

    def test_it_reads_a_setup_doc_snippet(self):
        doc = self.root / 'skills/valentin-mode/setup.md'
        doc.parent.mkdir(parents=True)
        doc.write_text('```json\n' + settings("/usr/bin/python3 \"$HOME/.claude/hooks/gone.py\"")
                       + '\n```\n')
        self.assertEqual(missing_hooks(self.root),
                         [('skills/valentin-mode/setup.md', 'gone.py')])

    def test_it_reads_the_installer_link_lines(self):
        (self.root / 'install').write_text(
            'link_one gone.py "$ROOT/hooks/gone.py" "$HOME/.claude/hooks"\n')
        self.assertEqual(missing_hooks(self.root), [('install', 'gone.py')])


if __name__ == '__main__':
    unittest.main()
