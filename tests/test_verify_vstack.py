"""verify-vstack: Doctor reads the real wiring, and Grade reads only the evidence.

The skill's merge gate is Doctor, so its checks must fail on the wiring that killed chats
(hooks deleted while the base still called them) and pass on a clean install. These tests
build small checkouts and scratch HOMEs; they never start a chat and never touch the real
HOME. VSTA-137.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / '.claude/skills/verify-vstack'
DOCTOR = SKILL / 'doctor.py'
GRADE = SKILL / 'grade.py'
LAUNCH = SKILL / 'launch.py'
INSTALL = ROOT / 'install'


def git(cwd, *args):
    return subprocess.run(
        ['git', '-c', 'user.name=test', '-c', 'user.email=test@example.invalid',
         '-c', 'commit.gpgsign=false', *args],
        cwd=str(cwd), capture_output=True, text=True, check=True).stdout


class Scratch:
    """A temp checkout with its own hooks, install and settings, plus a temp HOME."""

    def __init__(self, test):
        self.root = Path(tempfile.mkdtemp())
        test.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.checkout = self.root / 'checkout'
        self.home = self.root / 'home'
        (self.checkout / 'hooks').mkdir(parents=True)
        (self.checkout / '.claude').mkdir(parents=True)
        for folder in ('.claude/hooks', '.claude/skills', '.local/bin', '.local/state'):
            (self.home / folder).mkdir(parents=True)
        (self.root / 'evidence').mkdir()

    def commit(self, message):
        git(self.checkout, 'init', '-q')
        git(self.checkout, 'add', '-A')
        git(self.checkout, 'commit', '-qm', message)
        return git(self.checkout, 'rev-parse', 'HEAD').strip()

    def evidence(self):
        return self.root / 'evidence'

    def install_record(self, **fields):
        path = self.home / '.local/state/vstack/install.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fields))
        return path

    def launch_record(self, **overrides):
        record = {'checkout': str(self.checkout), 'commit': overrides.pop('commit', ''),
                  'base_ref': 'HEAD', 'base': '', 'install_exit': 0,
                  'seed_source': 'test', 'seeded_commands': 0}
        record.update(overrides)
        (self.evidence() / 'launch.json').write_text(json.dumps(record))
        return record


class Doctor(unittest.TestCase):
    def test_passes_on_a_clean_install(self):
        scratch = Scratch(self)
        (scratch.checkout / 'hooks/guard.py').write_text('#!/usr/bin/env python3\n')
        (scratch.checkout / 'hooks/long-chat.py').write_text('#!/usr/bin/env python3\n')
        (scratch.checkout / '.claude/settings.json').write_text(json.dumps({'hooks': {}}))
        commit = scratch.commit('base')
        (scratch.home / '.claude/hooks/guard.py').symlink_to(
            scratch.checkout / 'hooks/guard.py')
        (scratch.home / '.claude/skills/valentin-mode').mkdir()
        (scratch.home / '.claude/skills/valentin-mode/SKILL.md').write_text(
            '---\nname: valentin-mode\n---\n')
        (scratch.home / '.claude/settings.json').write_text(json.dumps({'hooks': {
            'PreToolUse': [{'matcher': 'Bash', 'hooks': [
                {'type': 'command', 'command': 'python3 "$HOME/.claude/hooks/guard.py"'}]}]}}))
        scratch.install_record(commit=commit, root=str(scratch.checkout))
        scratch.launch_record(commit=commit)

        result = subprocess.run(['python3', str(DOCTOR), '--checkout', str(scratch.checkout),
                                 '--scratch', str(scratch.home), '--evidence',
                                 str(scratch.evidence())],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('DOCTOR PASS', result.stdout)
        self.assertIn('CHECK wiring PASS', result.stdout)

    def test_fails_when_the_base_wiring_called_a_hook_this_tree_deleted(self):
        """The PR #278 shape: base settings register a hook, the change stops shipping it."""
        scratch = Scratch(self)
        (scratch.checkout / 'hooks/guard.py').write_text('#!/usr/bin/env python3\n')
        (scratch.checkout / 'hooks/skill-update.py').write_text('#!/usr/bin/env python3\n')
        wiring = {'hooks': {'UserPromptSubmit': [{'hooks': [
            {'type': 'command', 'command': 'python3 ~/.claude/hooks/skill-update.py'}]}]}}
        (scratch.checkout / '.claude/settings.json').write_text(json.dumps(wiring))
        base = scratch.commit('base wiring calls skill-update')
        (scratch.checkout / 'hooks/skill-update.py').unlink()
        (scratch.checkout / '.claude/settings.json').write_text(json.dumps({'hooks': {}}))
        commit = scratch.commit('delete the hook')
        (scratch.home / '.claude/settings.json').write_text(json.dumps({'hooks': {}}))
        scratch.install_record(commit=commit)
        scratch.launch_record(commit=commit, base=base)

        result = subprocess.run(['python3', str(DOCTOR), '--checkout', str(scratch.checkout),
                                 '--scratch', str(scratch.home), '--evidence',
                                 str(scratch.evidence())],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('CHECK base-wiring FAIL', result.stdout)
        self.assertIn('skill-update.py', result.stdout)

    def test_fails_when_a_registered_hook_file_is_missing(self):
        scratch = Scratch(self)
        (scratch.checkout / 'hooks/guard.py').write_text('#!/usr/bin/env python3\n')
        (scratch.checkout / '.claude/settings.json').write_text(json.dumps({'hooks': {}}))
        commit = scratch.commit('one hook')
        (scratch.home / '.claude/settings.json').write_text(json.dumps({'hooks': {
            'PreToolUse': [{'hooks': [
                {'type': 'command', 'command': 'python3 "$HOME/.claude/hooks/plan-pick-only.py"'}]}]}}))
        scratch.install_record(commit=commit)
        scratch.launch_record(commit=commit)

        result = subprocess.run(['python3', str(DOCTOR), '--checkout', str(scratch.checkout),
                                 '--scratch', str(scratch.home), '--evidence',
                                 str(scratch.evidence())],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('CHECK wiring FAIL', result.stdout)
        self.assertIn('plan-pick-only.py', result.stdout)

    def test_fails_when_the_install_recorded_no_commit(self):
        scratch = Scratch(self)
        (scratch.checkout / 'hooks/guard.py').write_text('#!/usr/bin/env python3\n')
        (scratch.checkout / '.claude/settings.json').write_text(json.dumps({'hooks': {}}))
        commit = scratch.commit('one hook')
        (scratch.home / '.claude/settings.json').write_text(json.dumps({'hooks': {}}))
        scratch.launch_record(commit=commit)

        result = subprocess.run(['python3', str(DOCTOR), '--checkout', str(scratch.checkout),
                                 '--scratch', str(scratch.home), '--evidence',
                                 str(scratch.evidence())],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('CHECK install FAIL', result.stdout)


class LaunchAndDoctor(unittest.TestCase):
    def test_installs_this_checkout_into_a_scratch_home_and_passes(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        evidence = home / 'evidence'
        evidence.mkdir()
        scratch = home / 'scratch'
        scratch.mkdir()
        env = {key: value for key, value in os.environ.items()
               if key not in ('VSTACK_DIR', 'VSTACK_INSTALL_ANYWHERE')}
        launch = subprocess.run(
            ['python3', str(LAUNCH), '--checkout', str(ROOT), '--scratch', str(scratch),
             '--base', 'HEAD', '--evidence', str(evidence)],
            env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(launch.returncode, 0, launch.stdout + launch.stderr)
        record = json.loads((evidence / 'launch.json').read_text())
        self.assertEqual(record['commit'], git(ROOT, 'rev-parse', 'HEAD').strip())
        self.assertTrue((scratch / '.local/state/vstack/install.json').is_file())
        doctor = subprocess.run(
            ['python3', str(DOCTOR), '--checkout', str(ROOT), '--scratch', str(scratch),
             '--evidence', str(evidence)],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        self.assertIn('DOCTOR PASS', doctor.stdout)


class Grade(unittest.TestCase):
    def grade(self, doctor_lines, drive=None):
        evidence = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, evidence, ignore_errors=True)
        (evidence / 'doctor.txt').write_text('\n'.join(doctor_lines) + '\n')
        if drive is not None:
            (evidence / 'drive.txt').write_text(drive + '\n')
        result = subprocess.run(['python3', str(GRADE), str(evidence)],
                                capture_output=True, text=True)
        return result, (evidence / 'verdict.txt').read_text()

    def test_pass_needs_every_doctor_check(self):
        result, verdict = self.grade(
            ['CHECK wiring PASS ok', 'CHECK install PASS ok', 'DOCTOR PASS'],
            'DRIVE PASS chat loaded')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('VERDICT PASS', verdict)

    def test_one_failed_check_fails_the_run(self):
        result, verdict = self.grade(
            ['CHECK wiring FAIL missing hook', 'DOCTOR FAIL'], 'DRIVE PASS chat loaded')
        self.assertEqual(result.returncode, 1)
        self.assertIn('VERDICT FAIL', verdict)

    def test_skipped_drive_does_not_fail_and_does_not_pass_as_drive(self):
        result, verdict = self.grade(
            ['CHECK wiring PASS ok', 'DOCTOR PASS'], 'DRIVE SKIP Claude is ahead of pace')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('drive SKIP', verdict)
        self.assertNotIn('drive PASS', verdict)

    def test_missing_doctor_is_a_failure(self):
        evidence = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, evidence, ignore_errors=True)
        result = subprocess.run(['python3', str(GRADE), str(evidence)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('nothing was checked', result.stdout)


class InstallRecord(unittest.TestCase):
    def test_install_records_the_checkout_commit(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        env = {key: value for key, value in os.environ.items()
               if key not in ('VSTACK_DIR', 'VSTACK_INSTALL_ANYWHERE')}
        env.update(HOME=str(home), VSTACK_INSTALL_ANYWHERE='1',
                   VSTACK_DIR=str(home / '.local/share/vstack'))
        result = subprocess.run(['bash', str(INSTALL)], env=env, capture_output=True,
                                text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads((home / '.local/state/vstack/install.json').read_text())
        self.assertEqual(record['commit'], git(ROOT, 'rev-parse', 'HEAD').strip())
        self.assertEqual(record['root'], str(ROOT.resolve()))


if __name__ == '__main__':
    unittest.main()
