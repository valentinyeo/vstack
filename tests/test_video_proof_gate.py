"""A user-visible UI diff cannot PASS without a before/after video link in the PR body."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / 'scripts/video_proof_gate.py'
VERDICT = ROOT / 'scripts/verdict.py'
WORKFLOW = ROOT / '.github/workflows/pstack-sources.yml'


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    sys.modules[loader.name] = module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def gate_module():
    return load('shared_video_proof_gate', GATE)


def run(*args, cwd=ROOT):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=cwd)


def git(root, *args):
    subprocess.run(
        ['git', '-C', str(root), '-c', 'user.name=test',
         '-c', 'user.email=test@example.invalid', *args],
        check=True,
        capture_output=True,
        text=True,
    )


class UiFileDetection(unittest.TestCase):
    def setUp(self):
        self.gate = gate_module()

    def test_frontend_templates_and_app_screens_count_as_ui(self):
        paths = [
            'src/components/Button.tsx',
            'web/Card.jsx',
            'app/Modal.vue',
            'src/routes/+page.svelte',
            'styles/theme.css',
            'public/index.html',
            'app/templates/dashboard.jinja2',
            'templates/welcome.py',
            'app/screens/Settings.kt',
            'src/screens/Home.ts',
            'ios/ProfileScreen.swift',
            'android/app/src/main/res/layout/activity_main.xml',
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(self.gate.is_ui_file(path), f'{path} should count as UI')

    def test_backend_docs_and_tests_do_not_count_as_ui(self):
        paths = [
            'scripts/video_proof_gate.py',
            'skills/valentin-mode/SKILL.md',
            'server/api/users.ts',
            'src/components/Button.test.tsx',
            'src/components/Button.spec.jsx',
            'tests/fixtures/index.html',
            'src/screens/README.md',
            'templates/manifest.json',
            'README.md',
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertFalse(self.gate.is_ui_file(path), f'{path} should not count as UI')


class VideoProofGate(unittest.TestCase):
    def setUp(self):
        self.gate = gate_module()

    def test_ui_diff_without_video_is_refused(self):
        for body in (
            '',
            'Fixed the header layout.\nTicket: https://app.hypertask.ai/detail/project-13556/251\n',
            'Before and after screenshots:\nhttps://example.com/before.png\nhttps://example.com/after.jpg\n',
            '![screenshot](https://github.com/user-attachments/assets/550e8400-e29b-41d4-a716-446655440000)\n',
            '<img src="https://github.com/user-attachments/assets/550e8400-e29b-41d4-a716-446655440000">\n',
            '```md\nhttps://example.com/demo.mp4\n```\n',
            'I recorded a before and after video locally.\n',
            'Before and after video: https://app.hypertask.ai/detail/project-13556/251\n',
            'Video proof: https://example.com/screen.png\n',
        ):
            with self.subTest(body=body[:48]):
                standing, why = self.gate.gate(['src/App.tsx'], body, 'PASS')
                self.assertEqual(standing, 'FAIL')
                self.assertEqual(len(why.splitlines()), 1)
                self.assertIn('src/App.tsx', why)
                self.assertIn('before/after video link', why)

    def test_ui_diff_with_video_is_allowed(self):
        for body in (
            'Before and after video: https://example.com/before-after.mp4\n',
            'Proof: https://cdn.example.com/run.webm?token=abc\n',
            'Demo: https://www.loom.com/share/1234567890abcdef\n',
            'Video: https://youtu.be/dQw4w9WgXcQ\n',
            'https://github.com/user-attachments/assets/550e8400-e29b-41d4-a716-446655440000\n',
            '<video src="https://media.example.com/proof"></video>\n',
            '[before and after video](https://r2.example.com/clips/vsta-251)\n',
        ):
            with self.subTest(body=body[:48]):
                self.assertEqual(self.gate.gate(['src/App.tsx'], body, 'PASS'), ('PASS', ''))
                self.assertEqual(self.gate.gate(['styles/app.css'], body, 'PASS+NOTES'), ('PASS+NOTES', ''))

    def test_non_ui_diff_is_unaffected(self):
        self.assertEqual(
            self.gate.gate(['scripts/video_proof_gate.py', 'README.md'], '', 'PASS'),
            ('PASS', ''),
        )
        self.assertEqual(
            self.gate.gate(['src/App.test.tsx', 'tests/fixtures/page.html'], '', 'PASS+NOTES'),
            ('PASS+NOTES', ''),
        )

    def test_fail_and_blocked_always_stand(self):
        for token in ('FAIL', 'BLOCKED'):
            self.assertEqual(self.gate.gate(['src/App.tsx'], '', token), (token, ''))


class CommandLineAndVerdict(unittest.TestCase):
    def test_cli_refuses_ui_diff_without_video_and_allows_with_video(self):
        with tempfile.TemporaryDirectory() as folder:
            changed = Path(folder, 'changed.txt')
            changed.write_text('web/Page.tsx\nscripts/helper.py\n')
            event = Path(folder, 'event.json')

            event.write_text(json.dumps({'pull_request': {'body': 'No video here.'}}))
            refused = run(str(GATE), '--changed-files', str(changed), '--event', str(event))
            self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
            self.assertEqual(refused.stdout.strip(), 'FAIL')
            self.assertIn('web/Page.tsx', refused.stderr)

            event.write_text(json.dumps({'pull_request': {'body': 'Proof: https://example.com/demo.mp4'}}))
            allowed = run(str(GATE), '--changed-files', str(changed), '--event', str(event))
            self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
            self.assertEqual(allowed.stdout.strip(), 'PASS')

            listed = run(str(GATE), '--changed-files', str(changed), '--list')
            self.assertEqual(listed.returncode, 0)
            self.assertEqual(listed.stdout.splitlines(), ['web/Page.tsx'])

    def test_cli_reads_git_base_diff(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder, 'repo')
            repo.mkdir()
            Path(repo, 'README.md').write_text('base\n')
            git(repo, 'init', '-q')
            git(repo, 'add', '-A')
            git(repo, 'commit', '-qm', 'base')
            Path(repo, 'src').mkdir()
            Path(repo, 'src/View.svelte').write_text('<h1>hi</h1>\n')
            git(repo, 'add', '-A')
            git(repo, 'commit', '-qm', 'ui change')
            body = Path(folder, 'body.md')
            body.write_text('Changed heading.\n')

            refused = run(str(GATE), '--base', 'HEAD~1', '--body-file', str(body), cwd=repo)
            self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
            self.assertIn('src/View.svelte', refused.stderr)

            body.write_text('Before/after video: https://example.com/clip.webm\n')
            allowed = run(str(GATE), '--base', 'HEAD~1', '--body-file', str(body), cwd=repo)
            self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)

    def test_verdict_reader_demotes_ui_pass_without_video(self):
        with tempfile.TemporaryDirectory() as folder:
            answer = Path(folder, 'answer.md')
            answer.write_text('Checked everything.\n\nPASS\n')
            ui_changed = Path(folder, 'ui.txt')
            ui_changed.write_text('app/screens/Login.kt\n')
            non_ui_changed = Path(folder, 'backend.txt')
            non_ui_changed.write_text('scripts/verdict.py\n')
            body = Path(folder, 'body.md')
            body.write_text('Updated screen copy.\n')

            refused = run(str(VERDICT), str(answer), '--changed-files', str(ui_changed), '--pr-body', str(body))
            self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
            self.assertEqual(refused.stdout.strip(), 'FAIL')
            self.assertIn('app/screens/Login.kt', refused.stderr)

            non_ui = run(str(VERDICT), str(answer), '--changed-files', str(non_ui_changed), '--pr-body', str(body))
            self.assertEqual(non_ui.returncode, 0, non_ui.stdout + non_ui.stderr)
            self.assertEqual(non_ui.stdout.strip(), 'PASS')

            body.write_text('Before/after video: https://example.com/login.mp4\n')
            allowed = run(str(VERDICT), str(answer), '--changed-files', str(ui_changed), '--pr-body', str(body))
            self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
            self.assertEqual(allowed.stdout.strip(), 'PASS')

    def test_verifier_workflow_wires_precheck_prompt_and_verdict_gate(self):
        text = WORKFLOW.read_text()
        self.assertIn('scripts/video_proof_gate.py --changed-files pr-changed.txt', text)
        self.assertIn('python3 scripts/verdict.py verdict.md --changed-files pr-changed.txt', text)
        self.assertIn('before/after video link in the PR body', text)


if __name__ == '__main__':
    unittest.main()
