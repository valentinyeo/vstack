import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'hooks/reconcile-auto.py'
INSTALL = ROOT / 'install'

spec = importlib.util.spec_from_file_location('reconcile_auto', HOOK)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class ReconcileAuto(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.home = base / 'home'
        self.project = base / 'project'
        self.project.mkdir(parents=True)
        (self.project / 'AGENTS.md').write_text(
            '# project\n\nHypertask board: 2060, label: Test\n')
        roster = hook.roster_path(self.home)
        roster.parent.mkdir(parents=True)
        roster.write_text(json.dumps({'rows': [
            {'tmux': 'live-test', 'multibot': 'Test Chat'}]}))
        self.token = hook.token_path(self.home, 'Test Chat')
        self.token.parent.mkdir(parents=True)
        self.token.write_text('secret\n')
        self.env = {'HOME': str(self.home), 'MULTIPROMPT_TAB': 'live-test'}
        self.calls = []
        self.real_spawn = hook.spawn
        hook.spawn = lambda *args: self.calls.append(args)
        self.addCleanup(setattr, hook, 'spawn', self.real_spawn)

    def answer(self, session='sid-1', cwd=None, now=None):
        payload = {'cwd': str(cwd or self.project), 'session_id': session}
        return hook.hook(payload, self.env, now=now)

    def status(self, exit_code=0, unknown=0, at=None, output=''):
        hook.write_status(self.home, 2060, 'Test', 'Test Chat', exit_code, output)
        target = hook.record_path(self.home, 2060, 'Test')
        record = json.loads(target.read_text())
        record['at'] = time.time() if at is None else at
        record['unknown'] = unknown
        target.write_text(json.dumps(record))
        return target

    def test_a_headless_run_passes(self):
        self.env.pop('MULTIPROMPT_TAB')
        self.assertEqual(self.answer(), {})
        self.assertEqual(self.calls, [])

    def test_a_project_note_without_the_line_blocks(self):
        app = Path(self.temp.name) / 'projects' / 'other-app'
        app.mkdir(parents=True)
        (app / 'AGENTS.md').write_text('# other app\n\nNo board here yet.\n')
        subprocess.run(['git', 'init', '-q', str(app)], check=True)
        answer = self.answer(cwd=app)
        self.assertEqual(answer.get('decision'), 'block')
        self.assertIn('Hypertask board: <id>, label: <label>', answer['reason'])
        self.assertIn('/hypertask-checkup check 5', answer['reason'])
        self.assertEqual(self.calls, [])

    def test_the_vstack_sibling_past_mistake(self):
        projects = Path(self.temp.name) / 'projects'
        vstack = projects / 'vstack'
        vstack.mkdir(parents=True)
        (vstack / 'AGENTS.md').write_text('Hypertask board: 15, label: Vstack\n')
        subprocess.run(['git', 'init', '-q', str(vstack)], check=True)
        sibling = projects / 'pecunia'
        sibling.mkdir()
        (sibling / 'AGENTS.md').write_text('# Pecunia\n\nBoard rules live elsewhere.\n')
        subprocess.run(['git', 'init', '-q', str(sibling)], check=True)
        self.assertEqual(self.answer(session='sid-vstack', cwd=vstack), {})
        self.assertEqual(len(self.calls), 1)
        answer = self.answer(session='sid-pecunia', cwd=sibling)
        self.assertEqual(answer.get('decision'), 'block')
        self.assertIn('Hypertask board: <id>, label: <label>', answer['reason'])

    def test_a_missing_token_blocks_and_names_the_path(self):
        self.token.unlink()
        answer = self.answer()
        self.assertEqual(answer.get('decision'), 'block')
        self.assertIn(str(self.token), answer['reason'])
        self.assertEqual(self.calls, [])

    def test_a_chat_named_only_in_chat_names_still_syncs(self):
        hook.roster_path(self.home).write_text(json.dumps({'rows': [
            {'tmux': 'live-other', 'multibot': 'Other Chat'}]}))
        names = hook.chat_names_path(self.home)
        names.parent.mkdir(parents=True)
        names.write_text(json.dumps({'live-test': {'name': 'Test Chat'}}))
        self.assertEqual(self.answer(), {})
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][2], 'Test Chat')

    def test_a_fresh_status_passes_without_a_run(self):
        self.status(exit_code=0)
        self.assertEqual(self.answer(), {})
        self.assertEqual(self.calls, [])

    def test_a_stale_status_starts_one_run(self):
        self.status(exit_code=0, at=time.time() - hook.THROTTLE - 1)
        self.assertEqual(self.answer(), {})
        self.assertEqual(len(self.calls), 1)
        board, label, name, token, cwd = self.calls[0][:5]
        self.assertEqual((board, label), (2060, 'Test'))
        self.assertEqual(name, 'Test Chat')
        self.assertEqual(str(token), str(self.token))
        self.assertEqual(cwd, self.project)

    def failures(self):
        path = hook.failures_path(self.home)
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_a_failed_run_logs_one_line_and_never_blocks(self):
        self.status(exit_code=1, output='MOVE X-1 Todo -> Doing\n')
        self.assertEqual(self.answer(), {})
        lines = self.failures()
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertEqual(line['board'], 2060)
        self.assertEqual(line['label'], 'Test')
        self.assertIsNone(line['ticket'])
        self.assertEqual(line['session_name'], 'Test Chat')
        self.assertEqual(line['log'], str(hook.log_path(self.home, 2060, 'Test')))
        self.assertEqual(line['summary'], 'MOVE X-1 Todo -> Doing')
        self.assertEqual(self.calls, [])

    def test_the_same_failed_run_is_logged_once(self):
        self.status(exit_code=1)
        for _ in range(3):
            self.assertEqual(self.answer(), {})
        self.assertEqual(len(self.failures()), 1)

    def test_a_run_with_unknowns_logs_and_never_blocks(self):
        self.status(exit_code=0, unknown=1, output='PREVIEW board=2060 tickets=2 unknown=1\n')
        self.assertEqual(self.answer(), {})
        self.assertEqual(len(self.failures()), 1)
        self.assertIn('unknown=1', self.failures()[0]['summary'])

    def test_a_bus_error_logged_never_blocks(self):
        self.status(exit_code=1, output=(
            'Could not connect: No such file or directory\n'))
        self.assertEqual(self.answer(), {})
        self.assertEqual(len(self.failures()), 1)

    def test_setup_gaps_block_once_an_hour_per_session(self):
        self.token.unlink()
        now = time.time()
        self.assertEqual(self.answer(session='sid-x', now=now).get('decision'), 'block')
        self.assertEqual(self.answer(session='sid-x', now=now + 60), {})
        self.assertEqual(self.answer(session='sid-x', now=now + 3601).get('decision'), 'block')
        self.assertFalse(hook.failures_path(self.home).exists(), 'a setup gap is not a tool failure')

    def test_the_status_record_shape_and_names(self):
        hook.write_status(self.home, 2060, 'Test', 'Test Chat', 0, (
            'MOVE SOFT-1 Todo -> Doing | live worker\n'
            'DEFERRED SOFT-2 Doing -> Todo | over limit=5\n'
            'PREVIEW board=2060 tickets=4 unknown=2\n'))
        target = hook.record_path(self.home, 2060, 'Test')
        record = json.loads(target.read_text())
        self.assertEqual(target.name, '2060-test.json')
        self.assertEqual(hook.log_path(self.home, 2060, 'Test').name, '2060-test.log')
        for field in ('at', 'session_name', 'board', 'label', 'exit', 'moved', 'unknown',
                      'summary_line', 'log'):
            self.assertIn(field, record)
        self.assertEqual(record['exit'], 0)
        self.assertEqual(record['moved'], 1)
        self.assertEqual(record['unknown'], 2)
        self.assertEqual(record['summary_line'], 'PREVIEW board=2060 tickets=4 unknown=2')
        self.assertTrue(hook.log_path(self.home, 2060, 'Test').is_file())

    def test_the_run_child_stores_the_board_as_a_number(self):
        real = hook.reconcile_script
        hook.reconcile_script = lambda home: None
        self.addCleanup(setattr, hook, 'reconcile_script', real)
        code = hook.run(['2060', 'Test', 'Test Chat', str(self.token), str(self.project)],
                        {'HOME': str(self.home)})
        record = json.loads(hook.record_path(self.home, 2060, 'Test').read_text())
        self.assertEqual(code, 0)
        self.assertEqual(record['board'], 2060)
        self.assertEqual(record['exit'], 1)
        self.assertIn('no reconcile script', record['summary_line'])

    def test_install_links_the_hook_into_claude(self):
        text = INSTALL.read_text()
        self.assertIn('link_one reconcile-auto.py "$ROOT/hooks/reconcile-auto.py" '
                      '"$HOME/.claude/hooks"', text)

    def test_the_self_test_passes(self):
        done = subprocess.run([sys.executable, str(HOOK), '--self-test'],
                              capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('reconcile-auto self-test ok', done.stdout)

    def test_hook_mode_prints_empty_json_without_a_tab(self):
        env = {'PATH': os.environ['PATH'], 'HOME': str(self.home)}
        done = subprocess.run([sys.executable, str(HOOK)], input='{}', text=True,
                              capture_output=True, env=env, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), '{}')


if __name__ == '__main__':
    unittest.main()
