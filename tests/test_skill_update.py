"""Tests for hooks/skill-update.py.

Every test runs in temp dirs with its own HOME. Job 1 is exercised against a temp
bare origin, never the real ~/.local/share/vstack.
"""
import hashlib
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
HOOK = ROOT / 'hooks/skill-update.py'
INSTALL = ROOT / 'install'

spec = importlib.util.spec_from_file_location('skill_update', HOOK)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class SkillUpdate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / 'home'
        self.share = self.home / '.local/share/vstack'
        self.env = {'HOME': str(self.home)}
        self.calls = []
        real = hook.run

        def counting(command, cwd, timeout, env=None):
            self.calls.append(list(command))
            return real(command, cwd, timeout, env)

        hook.run = counting
        self.addCleanup(setattr, hook, 'run', real)

    def git(self, cwd, *args):
        done = subprocess.run(['git', '-c', 'commit.gpgsign=false', '-C', str(cwd), *args],
                              capture_output=True, text=True, check=True)
        return done.stdout.strip()

    def commit(self, repo, message):
        self.git(repo, 'add', '-A')
        self.git(repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                 'commit', '-q', '-m', message)
        return self.git(repo, 'rev-parse', 'HEAD')

    def make_repo(self, with_install=False):
        """A temp bare origin and a clean clone at the shared path, one commit behind."""
        origin = self.base / 'origin.git'
        self.git(self.base, 'init', '-q', '--bare', '-b', 'main', str(origin))
        seed = self.base / 'seed'
        (seed / 'skills/valentin-mode').mkdir(parents=True)
        (seed / 'skills/valentin-mode/SKILL.md').write_text('v1\n')
        self.git(seed, 'init', '-q', '-b', 'main')
        first = self.commit(seed, 'first')
        if with_install:
            stub = seed / 'install'
            stub.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" > "$HOME/install-ran"\n')
            stub.chmod(0o755)
            self.commit(seed, 'install stub')
        self.git(seed, 'remote', 'add', 'origin', str(origin))
        self.git(seed, 'push', '-q', 'origin', 'main')
        self.share.parent.mkdir(parents=True)
        self.git(self.base, 'clone', '-q', str(origin), str(self.share))
        self.git(self.share, 'reset', '-q', '--hard', first)
        return origin, first

    def update(self, now=None):
        hook.update_shared(self.home, self.env, time.time() if now is None else now)

    def log(self):
        path = hook.state_dir(self.home) / 'updates.log'
        return path.read_text() if path.exists() else ''

    def test_the_throttle_does_no_git_inside_ten_minutes(self):
        self.make_repo(with_install=True)
        now = time.time()
        self.update(now)
        self.assertTrue(self.calls, 'the first prompt does the work')
        before = len(self.calls)
        self.update(now + 60)
        self.assertEqual(len(self.calls), before, 'a prompt inside ten minutes runs no git')
        self.update(now + hook.THROTTLE + 1)
        self.assertGreater(len(self.calls), before, 'the next window fetches again')

    def test_a_dirty_tree_is_left_alone(self):
        self.make_repo(with_install=True)
        head = self.git(self.share, 'rev-parse', 'HEAD')
        (self.share / 'scratch.txt').write_text('local work\n')
        self.update()
        self.assertEqual(self.git(self.share, 'rev-parse', 'HEAD'), head, 'HEAD stays put')
        self.assertFalse((self.home / 'install-ran').exists(), 'install never runs on a dirty tree')
        self.assertIn('dirty tree', self.log(), 'the skip is one log line')

    def test_a_clean_checkout_behind_moves_and_runs_its_install(self):
        _origin, first = self.make_repo(with_install=True)
        target = self.git(self.share, 'rev-parse', 'origin/main')
        self.assertNotEqual(first, target, 'the fixture is behind')
        self.update()
        self.assertEqual(self.git(self.share, 'rev-parse', 'HEAD'), target,
                         'the checkout moves to origin/main')
        ran = self.home / 'install-ran'
        self.assertTrue(ran.is_file(), 'that checkout ran its own install')
        self.assertEqual(ran.read_text().strip(), str(self.share))
        line = self.log().strip()
        self.assertIn(f'{first[:8]}..{target[:8]}', line, 'the log names both commits')

    def test_an_up_to_date_checkout_runs_no_install(self):
        self.make_repo(with_install=True)
        self.git(self.share, 'checkout', '-q', '--detach', 'origin/main')
        self.update()
        self.assertFalse((self.home / 'install-ran').exists(), 'nothing to do, no install')

    def test_a_failed_fetch_logs_and_never_raises(self):
        self.make_repo()
        self.git(self.share, 'remote', 'set-url', 'origin', str(self.base / 'missing.git'))
        self.update()
        self.assertIn('fetch failed', self.log(), 'a broken remote is one log line')

    def test_no_git_env_skips_the_checkout_job(self):
        self.make_repo(with_install=True)
        hook.update_shared(self.home, dict(self.env, SKILL_UPDATE_NO_GIT='1'), time.time())
        self.assertEqual(self.calls, [])

    def valentin_skill(self, text='v1\n'):
        """The real shape: a symlink from ~/.claude/skills into the shared checkout."""
        target = self.share / 'skills/valentin-mode'
        target.mkdir(parents=True)
        (target / 'SKILL.md').write_text(text)
        link = self.home / '.claude/skills/valentin-mode'
        link.parent.mkdir(parents=True)
        link.symlink_to(target)
        return target / 'SKILL.md'

    def transcript(self, loaded=True):
        path = self.base / 'transcript.jsonl'
        line = ('{"role": "user", "content": "Base directory for this skill: '
                '/home/x/.claude/skills/valentin-mode"}')
        path.write_text((line if loaded else '{"role": "user", "content": "hello"}') + '\n')
        return path

    def payload(self, session='sid-1', loaded=True):
        return {'session_id': session, 'transcript_path': str(self.transcript(loaded))}

    def notice(self, answer):
        return answer['hookSpecificOutput']['additionalContext']

    def test_the_reload_notice_fires_once_after_the_skill_changes(self):
        skill = self.valentin_skill('v1\n')
        payload = self.payload()
        self.assertEqual(hook.reload_notice(payload, self.home), {},
                         'the first immediate prompt only records the hash')
        skill.write_text('v2\n')
        answer = hook.reload_notice(payload, self.home)
        self.assertEqual(answer['hookSpecificOutput']['hookEventName'], 'UserPromptSubmit')
        text = self.notice(answer)
        old = hashlib.sha256(b'v1\n').hexdigest()[:8]
        new = hashlib.sha256(b'v2\n').hexdigest()[:8]
        self.assertIn(f'({old}..{new})', text)
        self.assertIn('Re-read ~/.claude/skills/valentin-mode/SKILL.md in full now', text)
        self.assertEqual(hook.reload_notice(payload, self.home), {}, 'the notice fires once')

    def test_a_chat_that_never_loaded_valentin_mode_gets_nothing(self):
        self.valentin_skill('v1\n')
        payload = self.payload(loaded=False)
        self.assertEqual(hook.reload_notice(payload, self.home), {})
        record = hook.session_record(self.home, payload['session_id'])
        self.assertFalse(record.exists(), 'nothing is recorded without a load')

    def test_no_transcript_prints_and_records_nothing(self):
        self.valentin_skill('v1\n')
        self.assertEqual(hook.reload_notice({'session_id': 'sid-x'}, self.home), {})
        self.assertEqual(hook.reload_notice({'transcript_path': '/no/such/file'}, self.home), {})
        self.assertFalse(hook.state_dir(self.home).joinpath('sessions').exists())

    def test_each_session_carries_its_own_record(self):
        skill = self.valentin_skill('v1\n')
        first, second = self.payload('sid-a'), self.payload('sid-b')
        self.assertEqual(hook.reload_notice(first, self.home), {})
        skill.write_text('v2\n')
        self.assertEqual(hook.reload_notice(second, self.home), {},
                         'the second chat loaded v2 and needs no notice')
        self.assertNotEqual(self.notice(hook.reload_notice(first, self.home)), '')

    def test_the_hook_prints_json_and_exits_zero_on_malformed_stdin(self):
        env = {'PATH': os.environ['PATH'], 'HOME': str(self.home)}
        done = subprocess.run([sys.executable, str(HOOK)], input='not json{',
                              text=True, capture_output=True, env=env, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, '')

    def test_the_hook_prints_the_notice_for_a_session(self):
        skill = self.valentin_skill('v1\n')
        payload = self.payload()
        env = {'PATH': os.environ['PATH'], 'HOME': str(self.home),
               'SKILL_UPDATE_NO_GIT': '1'}
        hook.reload_notice(payload, self.home)
        skill.write_text('v2\n')
        done = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                              text=True, capture_output=True, env=env, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        answer = json.loads(done.stdout)
        self.assertIn('valentin-mode changed', self.notice(answer))

    def test_install_links_the_hook_into_claude(self):
        self.assertIn('link_one skill-update.py "$ROOT/hooks/skill-update.py" '
                      '"$HOME/.claude/hooks"', INSTALL.read_text())

    def test_the_self_test_passes(self):
        done = subprocess.run([sys.executable, str(HOOK), '--self-test'],
                              capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('skill-update self-test ok', done.stdout)


if __name__ == '__main__':
    unittest.main()
