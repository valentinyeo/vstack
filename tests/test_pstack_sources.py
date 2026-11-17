import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ADVICE = 'I recommend we fix the worker plan. ' * 20


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'hooks' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PstackSources(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.cache = self.home / '.claude/plugins/cache/cursor-plugins/pstack'
        for version, books in [('0.15.9', ['orchestrate']),
                               ('0.15.42', ['orchestrate']),
                               ('0.15.43', ['autonomous-run', 'bug-fix'])]:
            folder = self.cache / version / 'skills/poteto-mode/playbooks'
            folder.mkdir(parents=True)
            for book in books:
                (folder / f'{book}.md').touch()
        for skill in ['figure-it-out', 'principle-attack-the-premise']:
            folder = self.cache / '0.15.43/skills' / skill
            folder.mkdir()
            (folder / 'SKILL.md').touch()
        self.reply = load('pstack-reply')
        self.source = load('pstack-source')
        self.reply.PSTACK = self.source.PSTACK = self.cache

    def test_advice_rejects_removed_source_from_older_versions(self):
        self.assertIsNotNone(self.reply.verdict(ADVICE + '\npstack: Orchestrate playbook'))

    def test_current_sources_and_plain_status_keep_passing(self):
        for name in ['Autonomous run playbook', 'figure-it-out skill', 'Attack the Premise']:
            with self.subTest(name=name):
                self.assertIsNone(self.reply.verdict(ADVICE + '\npstack: ' + name))
        self.assertIsNone(self.reply.verdict('Yes, tested live.'))
        self.assertIsNone(self.reply.verdict('x' * 400))
        self.assertIsNotNone(self.reply.verdict(ADVICE + '\npstack: Made Up Method'))
        self.assertIsNotNone(self.reply.verdict(ADVICE))

    def test_hook_feedback_points_at_current_playbook(self):
        reason = self.reply.verdict(ADVICE)
        self.assertNotIn('Orchestrate', reason)
        self.assertIn('Autonomous run', reason)

    def test_public_sources_name_current_playbook(self):
        text = (ROOT / 'book/pstack-sources.md').read_text()
        self.assertIn('playbooks/autonomous-run.md', text)
        self.assertIn('skills/figure-it-out/SKILL.md', text)
        self.assertNotIn('playbooks/orchestrate.md', text)

    def test_worker_source_rejects_removed_relative_and_absolute_paths(self):
        for path in ['skills/poteto-mode/playbooks/orchestrate.md',
                     str(self.cache / '0.15.42/skills/poteto-mode/playbooks/orchestrate.md')]:
            self.assertIsNotNone(self.source.verdict(
                'codex exec "Read /x/skills/poteto-mode/worker.md before anything else. '
                f'pstack: {path}"'))

    def test_worker_source_rejects_traversal_into_old_version(self):
        newest = self.cache / '0.15.43'
        relative = '../0.15.42/skills/poteto-mode/playbooks/orchestrate.md'
        for path in [relative, str(newest / relative)]:
            with self.subTest(path=path):
                result = subprocess.run(['python3', str(ROOT / 'hooks/pstack-source.py')],
                    input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command':
                        'codex exec "Read /x/skills/poteto-mode/worker.md before anything else. '
                        f'pstack: {path}"'}}), text=True, capture_output=True,
                    env=dict(os.environ, HOME=str(self.home)))
                self.assertEqual(result.returncode, 2, result.stderr)

    def test_worker_source_rejects_symlink_into_old_version(self):
        old = self.cache / '0.15.42/skills/poteto-mode/playbooks/orchestrate.md'
        link = self.cache / '0.15.43/skills/poteto-mode/playbooks/alias.md'
        link.symlink_to(old)
        self.assertIsNotNone(self.source.verdict(
            'codex exec "Read /x/skills/poteto-mode/worker.md before anything else. '
            'pstack: skills/poteto-mode/playbooks/alias.md"'))

    def test_real_hook_protocol_and_self_tests(self):
        transcript = self.home / 'transcript.jsonl'
        transcript.write_text(json.dumps({'type': 'assistant', 'message': {'content': [
            {'type': 'text', 'text': ADVICE + '\npstack: Orchestrate playbook'}]}}) + '\n')
        env = dict(os.environ, HOME=str(self.home))
        result = subprocess.run(['python3', str(ROOT / 'hooks/pstack-reply.py')],
            input=json.dumps({'transcript_path': str(transcript)}),
            text=True, capture_output=True, check=True, env=env)
        self.assertEqual(json.loads(result.stdout).get('decision'), 'block')
        for name in ['pstack-reply', 'pstack-source']:
            with self.subTest(hook=name):
                result = subprocess.run(['python3', str(ROOT / 'hooks' / f'{name}.py'), '--self-test'],
                    text=True, capture_output=True, env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('self-test ok', result.stdout)


if __name__ == '__main__':
    unittest.main()
