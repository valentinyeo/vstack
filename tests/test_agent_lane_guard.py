"""The agent lane (`hypertask activity add`) is coordination chatter only (VSTA-249).

Real case: the Seamless Session Transitioning chat put its MUBO-517 done summary in the
agent lane. Results, verdicts, proof, done summaries, and screenshot or video links belong
in a people comment (`comment add --kind done|qa`).
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import pwd
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'hooks/agent-lane-guard.py'
SHIMS = ROOT / 'scripts/worker-shims'
TICKET_LINT = ROOT / 'skills/hypertask/scripts/ticket-lint'

FAKE_HYPERTASK = '''#!/bin/sh
printf '%s\\n' "$*" >> "$HT_LOG"
printf 'ok: %s\\n' "$*"
'''


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


guard = load('agent_lane_guard_mod', HOOK)
ticket_lint = load('ticket_lint_lane_mod', TICKET_LINT)


def run_hook(command, cwd='/tmp'):
    payload = {'tool_name': 'Bash', 'cwd': str(cwd), 'tool_input': {'command': command}}
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=30,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
    )


BLOCKED_TEXTS = (
    'Done: seamless session transitioning fixed and verified. Proof: https://screencast2.com/v/mubo517',
    'MUBO-517 done: session handoff now keeps context across chats',
    'PASS: checks green on head abc1234',
    'QA PASS on staging',
    'QA-PASS',
    'PASS+NOTES: minor spacing tweak',
    'FAIL: login button unresponsive',
    'QA-FAIL: broken redirect',
    'Verified on the live app',
    'Fixed the crash on startup',
    'Confirmed working after deploy',
    'Proof: https://github.com/valentinyeo/vstack/pull/400',
    'Verdict on head abc1234',
    'Evidence attached for review',
    'https://screencast2.com/abc123',
    'https://cdn.example.com/after.png',
    'https://cdn.example.com/walkthrough.mp4',
    'https://cdn.example.com/clip.webm?v=1',
    'https://www.loom.com/share/abc123',
    'https://app.hypertask.ai/attachments/99',
)

ALLOWED_TEXTS = (
    'Next: rebase',
    'Claimed.',
    'Claimed by Vstack Maintainer. Branch: vsta-249-lane-evidence.',
    'Branch/PR: vsta-249-lane-evidence https://github.com/valentinyeo/vstack/pull/400',
    'claude --resume 12345678-abcd-ef00',
    'Released lease. Next: owner picks up review.',
    'Next: fix lint on PR #12',
    'Branch: fix/verified-login. Next: open PR.',
    'Work continues.',
)

MOVE_TEXTS = (
    'VSTA-249 AI Review -> Done | merged and checks green',
    'VSTA-249 Done -> Doing | owner resumes work',
    'VSTA-249 Verifier -> Done | merged with PASS',
    'fleet/reconcile: merged and checks green; AI Review -> Done.',
    'fleet/reconcile: merged with PASS; AI Review -> Done.',
    'fleet/reconcile: merged without PASS: rule break; owner must verify; Doing -> Todo.',
    'fleet/reconcile: merged PR; live proof pending; In Progress -> AI Review.',
    'fleet/reconcile: newer open PR https://github.com/a/b/pull/2 '
    'than the merged PASS; card follows it; Todo -> Checks.',
)


class GuardVerdict(unittest.TestCase):
    def test_refuses_result_like_activity_add_in_one_line(self):
        for text in BLOCKED_TEXTS:
            with self.subTest(text=text):
                why = guard.verdict(f'hypertask activity add VSTA-249 --text "{text}"')
                self.assertIsNotNone(why, text)
                self.assertEqual(len(why.splitlines()), 1, why)
                self.assertIn('comment add --kind done|qa', why)

    def test_allows_coordination_chatter(self):
        for text in ALLOWED_TEXTS:
            with self.subTest(text=text):
                why = guard.verdict(f'hypertask activity add VSTA-249 --text "{text}"')
                self.assertIsNone(why, f'{text} -> {why}')

    def test_allows_reconcile_positional_and_text_flag_shapes(self):
        for text in MOVE_TEXTS:
            for flag in ('', '--text '):
                with self.subTest(text=text, flag=flag):
                    self.assertIsNone(guard.verdict(
                        f'hypertask activity add VSTA-249 {flag}{shlex.quote(text)}'))

    def test_allows_poteto_ticket_claim_and_log_shapes(self):
        self.assertIsNone(guard.verdict('poteto-ticket claim SOFT-99'))
        for text in ALLOWED_TEXTS:
            with self.subTest(text=text):
                self.assertIsNone(guard.verdict(f'poteto-ticket log SOFT-99 {shlex.quote(text)}'))
                self.assertIsNone(guard.verdict(
                    f'hypertask --token private --json activity add SOFT-99 --text {shlex.quote(text)}'))

    def test_allows_vcc_coordination_and_resume_example(self):
        for text in (*ALLOWED_TEXTS, *MOVE_TEXTS):
            with self.subTest(text=text):
                self.assertIsNone(guard.verdict(f'vcc activity add VSTA-249 {shlex.quote(text)}'))
        self.assertIsNone(guard.verdict(
            'hypertask activity add VSTA-249 --text "claude --resume $CLAUDE_CODE_SESSION_ID"'))

    def test_refuses_results_through_aliases_and_positional_text(self):
        for text in BLOCKED_TEXTS:
            for prefix in ('vcc activity add VSTA-249', 'poteto-ticket log SOFT-99',
                           'hypertask activity add VSTA-249'):
                with self.subTest(prefix=prefix, text=text):
                    self.assertIsNotNone(guard.verdict(f'{prefix} {shlex.quote(text)}'))

    def test_move_notes_do_not_hide_results(self):
        texts = (
            'VSTA-249 AI Review -> Done | Fixed the crash',
            'VSTA-249 AI Review -> Done | PASS: verified on staging',
            'VSTA-249 AI Review -> Done | https://screencast2.com/x',
            'VSTA-249 AI Review -> Done | merged with PASS; Fixed the crash',
            'fleet/reconcile: Fixed and verified; AI Review -> Done.',
            'fleet/reconcile: merged with PASS; Fixed it; AI Review -> Done.',
            'fleet/reconcile: https://cdn.example.com/after.png; AI Review -> Done.',
            'fleet/reconcile: merged with PASS; AI Review -> Done.\nDone: fixed',
            'Done: fixed -> verified',
            'merged with PASS',
            'merged PR; live proof pending',
        )
        for text in texts:
            with self.subTest(text=text):
                self.assertIsNotNone(guard.verdict(
                    f'hypertask activity add VSTA-249 --text {shlex.quote(text)}'))

    def test_handles_command_variants_and_wrappers(self):
        forms = (
            'HYPERTASKS_JWT_TOKEN="$T" hypertask --json activity add MUBO-517 --text "PASS"',
            '/home/valentin/.local/bin/hypertask --token "$T" activity add MUBO-517 --text="Fixed it"',
            'timeout 30 hypertask activity add MUBO-517 -t "Verified on prod"',
            'bash -c \'hypertask activity add MUBO-517 --text "Confirmed"\'',
            'echo starting && hypertask activity add MUBO-517 --text "https://screencast2.com/x"',
        )
        for command in forms:
            with self.subTest(command=command):
                why = guard.verdict(command)
                self.assertIsNotNone(why, command)
                self.assertIn('comment add --kind done|qa', why)

    def test_reads_text_file_flag(self):
        with tempfile.TemporaryDirectory() as raw:
            note = Path(raw) / 'note.txt'
            note.write_text('Done: fixed and verified.\n', encoding='utf-8')
            why = guard.verdict('hypertask activity add VSTA-249 --text-file note.txt', cwd=raw)
            self.assertIsNotNone(why)
            self.assertIn('comment add --kind done|qa', why)
            note.write_text('Next: rebase\n', encoding='utf-8')
            self.assertIsNone(guard.verdict('hypertask activity add VSTA-249 --text-file note.txt', cwd=raw))

    def test_ignores_people_comments_reads_help_and_other_commands(self):
        allowed = (
            'hypertask comment add VSTA-249 --kind done --text "<p><b>Fixed and verified.</b></p>"',
            'hypertask comment add VSTA-249 --kind qa --text "<p>PASS https://screencast2.com/x</p>"',
            'hypertask task agent-log VSTA-249',
            'hypertask activity add --help',
            'echo "hypertask activity add VSTA-249 --text PASS"',
        )
        for command in allowed:
            with self.subTest(command=command):
                self.assertIsNone(guard.verdict(command), command)

    def test_hook_cli_exits_2_on_result_and_0_on_chatter(self):
        blocked = run_hook(
            'hypertask activity add MUBO-517 --text '
            '"Done: seamless session transitioning fixed and verified. Proof: https://screencast2.com/v/mubo517"'
        )
        self.assertEqual(blocked.returncode, 2, blocked.stderr)
        self.assertEqual(len(blocked.stderr.strip().splitlines()), 1, blocked.stderr)
        self.assertIn('comment add --kind done|qa', blocked.stderr)

        allowed = run_hook('hypertask activity add VSTA-249 --text "Next: rebase"')
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertEqual(allowed.stderr, '')


class WorkerShim(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.bin = self.dir / 'bin'
        self.bin.mkdir()
        self.log = self.dir / 'calls.log'
        for command in ('hypertask', 'vcc', 'poteto-ticket'):
            fake = self.bin / command
            fake.write_text(FAKE_HYPERTASK, encoding='utf-8')
            fake.chmod(0o755)
        self.shims = self.dir / 'shims'
        result = subprocess.run(
            [sys.executable, str(SHIMS), '--dir', str(self.shims),
             '--path', str(self.bin), '--agent-lane-hook', str(HOOK)],
            text=True,
            capture_output=True,
            timeout=60,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def shim_env(self):
        return dict(
            os.environ,
            HT_LOG=str(self.log),
            PYTHONDONTWRITEBYTECODE='1',
            PATH=f'{self.shims}{os.pathsep}{self.bin}{os.pathsep}{os.environ.get("PATH", "")}',
        )

    def run_shim(self, *args, command='hypertask'):
        return subprocess.run(
            [str(self.shims / command), *args],
            text=True,
            capture_output=True,
            timeout=30,
            env=self.shim_env(),
        )

    def test_shim_refuses_result_without_calling_real_hypertask(self):
        result = self.run_shim('activity', 'add', 'MUBO-517', '--text', 'PASS: verified on staging')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('comment add --kind done|qa', result.stderr)
        self.assertFalse(self.log.exists(), 'real hypertask must not run when refused')

    def test_shim_allows_coordination_chatter(self):
        result = self.run_shim('activity', 'add', 'VSTA-249', '--text', 'Next: rebase')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ok: activity add VSTA-249 --text Next: rebase', result.stdout)
        self.assertTrue(self.log.exists())

    def test_shim_allows_reconcile_moves(self):
        for text in MOVE_TEXTS:
            for flag in ([], ['--text']):
                with self.subTest(text=text, flag=flag):
                    result = self.run_shim('activity', 'add', 'VSTA-249', *flag, text)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(text, self.log.read_text())

    def test_alias_shims_refuse_results_and_allow_coordination(self):
        for command, prefix in (('vcc', ('activity', 'add', 'VSTA-249')),
                                ('poteto-ticket', ('log', 'SOFT-99'))):
            for text in BLOCKED_TEXTS:
                with self.subTest(command=command, text=text):
                    result = self.run_shim(*prefix, text, command=command)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertFalse(self.log.exists())
        for command, args in (('vcc', ('activity', 'add', 'VSTA-249', 'Next: rebase')),
                              ('poteto-ticket', ('claim', 'SOFT-99')),
                              ('poteto-ticket', ('log', 'SOFT-99', 'Work continues.'))):
            result = self.run_shim(*args, command=command)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(' '.join(args), self.log.read_text())

    def test_shell_variables_reach_shim_as_resolved_text(self):
        for command in ('hypertask activity add VSTA-249 --text "$NOTE"',
                        'vcc activity add VSTA-249 "$NOTE"',
                        'poteto-ticket log SOFT-99 "$NOTE"'):
            result = subprocess.run(
                ['bash', '-c', 'NOTE="PASS: verified"; ' + command],
                env=self.shim_env(), capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertFalse(self.log.exists())

    def test_actual_reconcile_moves_through_shim_without_runtime_error(self):
        r = load('agent_lane_reconcile', ROOT / 'skills/hypertask-work/reconcile')
        merged = r.Pull('https://github.com/a/b/pull/1', 'MERGED', 'green', True,
                        merged_at=100, created_at=1)
        unproven = r.Pull('https://github.com/a/b/pull/1', 'MERGED', 'green', False)
        newer = r.Pull('https://github.com/a/b/pull/2', 'OPEN', 'green', False, created_at=200)
        cases = (
            (2060, 'AI Review', (merged,), False, 'Done', 'merged with PASS'),
            (2060, 'Doing', (unproven,), False, 'Todo', 'merged without PASS'),
            (2060, 'Doing', (merged, newer), False, 'AI Review', 'than the merged PASS'),
            (2060, 'Todo', (), True, 'Doing', 'live worker'),
            (2060, 'Doing', (), False, 'Todo', 'no live worker and no PR'),
            (15, 'In Progress', (merged,), False, 'Done', 'merged with PASS'),
            (15, 'QA', (merged,), False, 'Done', 'merged with PASS'),
            (15, 'Backlog', (), True, 'In Progress', 'live worker'),
        )
        for board_id, column, pulls, alive, expected, reason in cases:
            with self.subTest(board=board_id, column=column, reason=reason):
                board = r.BOARDS[board_id]
                key = f'{board.prefix}-249'
                task = {'ticketNumber': key, 'projectId': board_id, 'section': column}
                with patch.dict(os.environ, self.shim_env()), \
                        patch.object(r, 'api') as api, \
                        patch.object(r, 'require_board15_agent'), \
                        contextlib.redirect_stdout(io.StringIO()):
                    result = r.reconcile(task, r.Facts(column, 8000, alive, pulls),
                                         apply=True, board=board)
                self.assertEqual(result, expected)
                api.assert_called_once_with('task', 'move', key, '--section', expected)
                self.assertIn(reason, self.log.read_text())
                self.assertIn(f'{column} -> {expected}.', self.log.read_text())


class TicketLintHintsAndDocs(unittest.TestCase):
    def test_ticket_lint_hints_keep_evidence_in_comment(self):
        bad = ticket_lint.lint('Next: rebase\nSee /tmp/run/log.txt for output.')
        joined = '\n'.join(bad)
        self.assertIn('only coordination chatter goes to the agent lane', joined)
        self.assertIn('rewrite the evidence in plain words with a link', joined)
        self.assertNotIn('belongs in the agent lane', joined)
        self.assertNotIn('use the agent lane', joined)

        result = subprocess.run(
            [sys.executable, str(TICKET_LINT), '-'],
            input='See /tmp/run/log.txt for output.\n',
            text=True,
            capture_output=True,
            timeout=30,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn('rewrite the evidence in plain words with a link, in the comment', result.stderr)
        self.assertIn('Only coordination chatter goes to the agent lane', result.stderr)
        self.assertNotIn('plain comment with no --kind (agent lane)', result.stderr)

    def test_docs_and_rule_tables_reflect_the_rule(self):
        tickets = (ROOT / 'skills/hypertask/references/tickets.md').read_text(encoding='utf-8')
        self.assertNotIn('paths, logs and evidence go here', tickets)
        self.assertNotIn('<p><code>claude --resume', tickets)
        self.assertIn('hypertask activity add <PREFIX-NNN> --text "claude --resume $CLAUDE_CODE_SESSION_ID"', tickets)

        checkup = (ROOT / 'skills/hypertask/references/checkup.md').read_text(encoding='utf-8')
        self.assertNotIn('in the agent lane', checkup)
        self.assertIn('people comment', checkup)

        self.assertIn('hooks/agent-lane-guard.py', (ROOT / 'CLAUDE.md').read_text(encoding='utf-8'))
        self.assertIn('agent-lane-results',
                      (ROOT / 'skills/hypertask/references/board-lint-rules.md').read_text(encoding='utf-8'))


class Wiring(unittest.TestCase):
    def test_install_registers_hook_globally_and_links_codex_skill(self):
        scratch = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        home = scratch / 'home'
        home.mkdir()
        real = Path(pwd.getpwuid(os.getuid()).pw_dir) / '.claude/settings.json'
        before = real.read_bytes() if real.is_file() else None
        env = {k: v for k, v in os.environ.items() if k not in ('VSTACK_DIR', 'VSTACK_INSTALL_ANYWHERE')}
        env.update(HOME=str(home), VSTACK_INSTALL_ANYWHERE='1')
        for _ in range(2):
            result = subprocess.run(['bash', str(ROOT / 'install')], env=env, text=True,
                                    capture_output=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        settings = json.loads((home / '.claude/settings.json').read_text(encoding='utf-8'))
        registered = [
            (group.get('matcher'), hook.get('command', ''))
            for group in settings['hooks']['PreToolUse']
            for hook in group.get('hooks', [])
            if 'agent-lane-guard.py' in hook.get('command', '')
        ]
        self.assertEqual(len(registered), 1, registered)
        self.assertEqual(registered[0][0], 'Bash')
        codex_skill = home / '.codex/skills/hypertask'
        self.assertTrue(codex_skill.is_symlink())
        self.assertEqual(codex_skill.resolve(), (ROOT / 'skills/hypertask').resolve())
        self.assertEqual(real.read_bytes() if real.is_file() else None, before)


if __name__ == '__main__':
    unittest.main()
