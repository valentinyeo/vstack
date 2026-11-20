import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / '.claude/skills/verify-board-drain'
GRADE = SKILL / 'grade.py'
RUN = SKILL / 'run'
FIXTURES = ROOT / 'tests/fixtures/verify-board-drain'


class VerifyBoardDrainGrade(unittest.TestCase):
    def temp_dir(self):
        temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, temp, ignore_errors=True)
        return temp

    def copy_fixture(self, case):
        target = self.temp_dir() / case
        shutil.copytree(FIXTURES / case, target)
        return target

    def grade(self, target):
        result = subprocess.run([sys.executable, str(GRADE), str(target)],
                                capture_output=True, text=True, check=False)
        return result.returncode, result.stdout, target

    def grade_fixture(self, case):
        return self.grade(self.copy_fixture(case))

    def assert_check(self, output, verdict, check):
        lines = output.splitlines()
        self.assertIn('VERDICT ' + verdict, lines, output)
        expected = ('PASS ' if verdict == 'PASS' else 'FAIL ') + check + ':'
        self.assertTrue(any(line.startswith(expected) for line in lines),
                        'expected a %r line, got:\n%s' % (expected, output))

    def rewrite_stream(self, target, change):
        path = target / 'stream.jsonl'
        events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        path.write_text('\n'.join(json.dumps(event) for event in change(events)) + '\n')

    def test_pass_fixture_grades_pass(self):
        """A restarted chat that reads, arms, records, syncs and checks passes every check."""
        code, output, target = self.grade_fixture('pass')
        self.assertEqual(code, 0, output)
        for check in ('loaded', 'status-read', 'armed', 'recorded', 'synced',
                      'checked', 'no-writes'):
            self.assert_check(output, 'PASS', check)
        self.assertIn('PASS armed: CronCreate armed the loop every 15 minutes', output)
        self.assertIn('PASS recorded: armed in this run, expires in about 7 days, '
                      'job 7f3a91c2 recorded', output)
        self.assertFalse(any(line.startswith('FAIL ') for line in output.splitlines()), output)
        verdict = json.loads((target / 'verdict.json').read_text())
        self.assertEqual(verdict['verdict'], 'PASS')
        self.assertEqual(verdict['session_id'], 'sid-vbd')
        self.assertEqual([check['name'] for check in verdict['checks']],
                         ['loaded', 'status-read', 'armed', 'recorded', 'synced',
                          'checked', 'no-writes'])
        self.assertEqual((target / 'verdict.txt').read_text(), output)

    def test_no_board_drain_fixture_fails_every_loop_check(self):
        """The chat that never loaded board drain left its expired loop untouched."""
        code, output, _target = self.grade_fixture('no-board-drain')
        self.assertEqual(code, 1, output)
        for check in ('loaded', 'status-read', 'armed', 'recorded', 'synced', 'checked'):
            self.assert_check(output, 'FAIL', check)
        self.assertIn('FAIL loaded: board-drain not loaded: no Skill call and '
                      'no /board-drain prompt', output)
        self.assertIn('FAIL armed: the chat never armed a loop', output)
        self.assertIn('FAIL recorded: the state file was not armed in this run', output)
        self.assertIn('FAIL synced: the chat never ran ./sync', output)
        self.assertIn('PASS no-writes: no ticket moves, no comments, no plan-pick workers', output)
        self.assertFalse(any('Traceback' in line for line in output.splitlines()), output)

    def test_slash_prompt_alone_passes_loaded(self):
        """The prompt starting with /board-drain is enough to prove the skill loaded."""
        target = self.copy_fixture('pass')

        def drop_skill(events):
            return [event for event in events
                    if not (event.get('message', {}).get('content')
                            and any(block.get('name') == 'Skill'
                                    for block in event['message']['content']))]
        self.rewrite_stream(target, drop_skill)
        code, output, _target = self.grade(target)
        self.assertEqual(code, 0, output)
        self.assertIn('PASS loaded: the chat was started with /board-drain', output)

    def test_loop_skill_call_passes_armed_without_a_job_check(self):
        """Claude Code's /loop carries the interval and prompt when CronCreate is not used."""
        target = self.copy_fixture('pass')

        def swap_arm(events):
            kept = []
            for event in events:
                content = event.get('message', {}).get('content') or []
                names = {block.get('name') for block in content if isinstance(block, dict)}
                if names & {'CronCreate'}:
                    continue
                if any(block.get('type') == 'tool_result'
                       and block.get('tool_use_id') == 't2' for block in content):
                    continue
                kept.append(event)
                if names & {'Skill'}:
                    kept.append({'type': 'assistant', 'session_id': 'sid-vbd', 'message': {
                        'role': 'assistant', 'content': [{
                            'type': 'tool_use', 'id': 't9', 'name': 'Skill',
                            'input': {'skill': 'loop', 'args':
                                      '15m /pstack:poteto-mode full autopilot on this queue: '
                                      'every workable ticket in my view '
                                      'https://app.hypertask.ai/view/vbd-test. done when '
                                      'skills/board-drain/drain-check --board 2060 '
                                      '--label vvm-test passes.'}}]}})
            return kept
        self.rewrite_stream(target, swap_arm)
        state_path = target / 'state.json'
        state = json.loads(state_path.read_text())
        state.pop('job')
        state_path.write_text(json.dumps(state, indent=2) + '\n')
        code, output, _target = self.grade(target)
        self.assertEqual(code, 0, output)
        self.assertIn('PASS armed: /loop armed the loop every 15 minutes', output)
        self.assertIn('PASS recorded: armed in this run, expires in about 7 days', output)

    def test_wrong_job_fails_recorded(self):
        """An arming the chat never recorded is not an armed loop."""
        target = self.copy_fixture('pass')
        state_path = target / 'state.json'
        state = json.loads(state_path.read_text())
        state['job'] = 'something-else'
        state_path.write_text(json.dumps(state, indent=2) + '\n')
        code, output, _target = self.grade(target)
        self.assertEqual(code, 1, output)
        self.assertIn('FAIL recorded: the state file holds job something-else, '
                      'not the arming job 7f3a91c2', output)

    def test_short_expiry_fails_recorded(self):
        """A re-arm shorter than the 7-day cron limit is not the documented loop."""
        target = self.copy_fixture('pass')
        state_path = target / 'state.json'
        state = json.loads(state_path.read_text())
        state['expires_at'] = '2026-11-21T10:01:12Z'
        state_path.write_text(json.dumps(state, indent=2) + '\n')
        code, output, _target = self.grade(target)
        self.assertEqual(code, 1, output)
        self.assertIn('FAIL recorded: expires_at is not about 7 days after armed_at', output)

    def test_failed_sync_fails_synced(self):
        """A sync that recorded a failure stays a finding, however the chat reports it."""
        target = self.copy_fixture('pass')
        state_path = target / 'state.json'
        state = json.loads(state_path.read_text())
        state['last_sync'] = {'at': '2026-11-20T10:02:00Z', 'ok': False,
                              'reason': 'preview printed: usage: reconcile'}
        state_path.write_text(json.dumps(state, indent=2) + '\n')
        code, output, _target = self.grade(target)
        self.assertEqual(code, 1, output)
        self.assertIn('FAIL synced: the last sync failed: preview printed: usage: reconcile', output)

    def test_ticket_write_fails_no_writes(self):
        """The test chat may never move a ticket or start a code worker."""
        target = self.copy_fixture('pass')

        def add_move(events):
            return events + [{'type': 'assistant', 'session_id': 'sid-vbd', 'message': {
                'role': 'assistant', 'content': [{
                    'type': 'tool_use', 'id': 't7', 'name': 'Bash',
                    'input': {'command': 'hypertask task move SOFT-2849 --to Doing'}}]}}]
        self.rewrite_stream(target, add_move)
        code, output, _target = self.grade(target)
        self.assertEqual(code, 1, output)
        self.assertIn('FAIL no-writes: the chat ran task move', output)

    def test_plan_pick_run_fails_no_writes(self):
        target = self.copy_fixture('pass')

        def add_worker(events):
            return events + [{'type': 'assistant', 'session_id': 'sid-vbd', 'message': {
                'role': 'assistant', 'content': [{
                    'type': 'tool_use', 'id': 't8', 'name': 'Bash',
                    'input': {'command': '~/.local/bin/plan-pick --run --brief brief.txt'}}]}}]
        self.rewrite_stream(target, add_worker)
        code, output, _target = self.grade(target)
        self.assertEqual(code, 1, output)
        self.assertIn('FAIL no-writes: the chat ran plan-pick --run', output)

    def test_one_shot_cron_fails_armed(self):
        """A job that fires once never turns the loop back on."""
        target = self.copy_fixture('pass')

        def one_shot(events):
            for event in events:
                for block in event.get('message', {}).get('content') or []:
                    if isinstance(block, dict) and block.get('name') == 'CronCreate':
                        block['input']['recurring'] = False
            return events
        self.rewrite_stream(target, one_shot)
        code, output, _target = self.grade(target)
        self.assertEqual(code, 1, output)
        self.assertIn('FAIL armed: armed a one-shot job instead of a recurring loop', output)

    def test_hourly_cron_fails_armed(self):
        target = self.copy_fixture('pass')

        def hourly(events):
            for event in events:
                for block in event.get('message', {}).get('content') or []:
                    if isinstance(block, dict) and block.get('name') == 'CronCreate':
                        block['input']['cron'] = '0 * * * *'
            return events
        self.rewrite_stream(target, hourly)
        code, output, _target = self.grade(target)
        self.assertEqual(code, 1, output)
        self.assertIn('FAIL armed: armed a job that does not fire every 15 minutes: 0 * * * *',
                      output)

    def test_offset_quarter_hour_cron_passes_armed(self):
        """A measured /loop arm used 7,22,37,52: 15 minutes apart, off the hour."""
        target = self.copy_fixture('pass')

        def offset(events):
            for event in events:
                for block in event.get('message', {}).get('content') or []:
                    if isinstance(block, dict) and block.get('name') == 'CronCreate':
                        block['input']['cron'] = '7,22,37,52 * * * *'
            return events
        self.rewrite_stream(target, offset)
        code, output, _target = self.grade(target)
        self.assertEqual(code, 0, output)
        self.assert_check(output, 'PASS', 'armed')

    def test_quarter_hour_list_passes_armed(self):
        """Any minute expression on the quarter hour counts as every 15 minutes."""
        target = self.copy_fixture('pass')

        def listed(events):
            for event in events:
                for block in event.get('message', {}).get('content') or []:
                    if isinstance(block, dict) and block.get('name') == 'CronCreate':
                        block['input']['cron'] = '0,15,30,45 * * * *'
            return events
        self.rewrite_stream(target, listed)
        code, output, _target = self.grade(target)
        self.assertEqual(code, 0, output)
        self.assert_check(output, 'PASS', 'armed')

    def arm_with_watcher(self, target, board='2060', label='vvm-test', safety='0 */6 * * *',
                         background=True, script='skills/board-drain/watch'):
        """The pass stream with a tracked background watcher instead of a 15-minute cron."""
        job = 'safe4c1d2'
        state_path = target / 'state.json'
        state = json.loads(state_path.read_text())
        state['every'] = '6h'
        if safety is None:
            state.pop('job', None)
        else:
            state['job'] = job
        state_path.write_text(json.dumps(state, indent=2) + '\n')
        watcher = {'type': 'assistant', 'session_id': 'sid-vbd', 'message': {
            'role': 'assistant', 'content': [{
                'type': 'tool_use', 'id': 'w1', 'name': 'Bash',
                'input': {'command': '%s --board %s --label "%s" '
                                     '--name "VBD Test Chat" --every 180'
                                     % (script, board, label),
                          'description': 'Watch the view', 'run_in_background': background,
                          'timeout': 7200000}}]}}
        safety_events = []
        if safety is not None:
            prompt = ('/pstack:poteto-mode full autopilot on this queue: every workable ticket '
                      'in my view https://app.hypertask.ai/view/vbd-test. each item is '
                      'independent. done when skills/board-drain/drain-check --board 2060 '
                      '--label vvm-test passes.')
            safety_events = [
                {'type': 'assistant', 'session_id': 'sid-vbd', 'message': {
                    'role': 'assistant', 'content': [{
                        'type': 'tool_use', 'id': 'c1', 'name': 'CronCreate',
                        'input': {'cron': safety, 'prompt': prompt, 'recurring': True}}]}},
                {'type': 'user', 'session_id': 'sid-vbd', 'message': {
                    'role': 'user', 'content': [{
                        'type': 'tool_result', 'tool_use_id': 'c1',
                        'content': 'Scheduled recurring job %s (Every 6 hours). Session-only.'
                                   % job, 'is_error': False}]}}]

        def swap(events):
            kept = []
            for event in events:
                content = event.get('message', {}).get('content') or []
                names = {block.get('name') for block in content if isinstance(block, dict)}
                if 'CronCreate' in names:
                    continue
                if any(block.get('type') == 'tool_result' and block.get('tool_use_id') == 't2'
                       for block in content if isinstance(block, dict)):
                    continue
                kept.append(event)
            return kept + [watcher] + safety_events
        self.rewrite_stream(target, swap)

    def test_background_watcher_with_a_safety_cron_passes_armed(self):
        """A tracked watcher job on this view, plus a safety cron, is an armed loop."""
        target = self.copy_fixture('pass')
        self.arm_with_watcher(target)
        code, output, _target = self.grade(target)
        self.assertEqual(code, 0, output)
        self.assert_check(output, 'PASS', 'armed')
        self.assertIn('PASS armed: a background watcher on this view, with a safety cron', output)
        self.assertIn('PASS recorded: armed in this run, expires in about 7 days, '
                      'job safe4c1d2 recorded', output)

    def test_a_local_watch_call_passes_armed(self):
        """A chat run from the skill directory starts the watcher as ./watch."""
        target = self.copy_fixture('pass')
        self.arm_with_watcher(target, script='./watch')
        code, output, _target = self.grade(target)
        self.assertEqual(code, 0, output)
        self.assert_check(output, 'PASS', 'armed')

    def test_a_watcher_without_a_safety_cron_fails_armed(self):
        """Nothing restarts the loop when the watcher dies without a safety cron."""
        target = self.copy_fixture('pass')
        self.arm_with_watcher(target, safety=None)
        code, output, _target = self.grade(target)
        self.assertEqual(code, 1, output)
        self.assertIn('FAIL armed: armed a watcher with no safety cron', output)

    def test_a_watch_call_for_another_board_fails_armed(self):
        """A watcher polling someone else's view never wakes this chat."""
        target = self.copy_fixture('pass')
        self.arm_with_watcher(target, board='9999')
        code, output, _target = self.grade(target)
        self.assertEqual(code, 1, output)
        self.assertIn('FAIL armed: armed a watch job for another view', output)

    def test_a_foreground_watch_call_fails_armed(self):
        """A watcher the chat waits on is not a loop; the call must run in the background."""
        target = self.copy_fixture('pass')
        self.arm_with_watcher(target, background=False)
        code, output, _target = self.grade(target)
        self.assertEqual(code, 1, output)
        self.assertIn('FAIL armed: armed a watch call that did not run in the background',
                      output)

    def test_a_daily_safety_cron_fails_armed(self):
        """A safety net that fires once a day leaves the queue idle for almost a day."""
        target = self.copy_fixture('pass')
        self.arm_with_watcher(target, safety='0 0 * * *')
        code, output, _target = self.grade(target)
        self.assertEqual(code, 1, output)
        self.assertIn('FAIL armed: armed a safety job that does not fire within 6 hours: '
                      '0 0 * * *', output)

    def test_var_path_fixture_reads_loop_state(self):
        """loop-state called through a shell variable is still a status read."""
        target = self.copy_fixture('pass')

        def var_path(events):
            for event in events:
                for block in event.get('message', {}).get('content') or []:
                    if not isinstance(block, dict) or block.get('name') != 'Bash':
                        continue
                    command = block['input'].get('command', '')
                    if 'loop-state status' in command:
                        block['input']['command'] = (
                            'S=skills/board-drain/loop-state; $S status --name "VBD Test Chat"')
                    if 'drain-check --board' in command:
                        block['input']['command'] = (
                            'D=skills/board-drain/drain-check; $D --board 2060 '
                            '--label vvm-test --state-name "VBD Test Chat"')
            return events
        self.rewrite_stream(target, var_path)
        code, output, _target = self.grade(target)
        self.assertEqual(code, 0, output)
        self.assert_check(output, 'PASS', 'status-read')
        self.assert_check(output, 'PASS', 'checked')

    def test_loop_prompt_needs_the_board(self):
        """An arm whose prompt does not name this chat's view is not the queue."""
        target = self.copy_fixture('pass')

        def vague(events):
            for event in events:
                for block in event.get('message', {}).get('content') or []:
                    if isinstance(block, dict) and block.get('name') == 'CronCreate':
                        block['input']['prompt'] = 'full autopilot on this queue'
            return events
        self.rewrite_stream(target, vague)
        code, output, _target = self.grade(target)
        self.assertEqual(code, 1, output)
        self.assertIn('FAIL armed: armed a job whose prompt is not the board-drain loop prompt',
                      output)

    def test_missing_evidence_dir_exits_2(self):
        missing = self.temp_dir() / 'does-not-exist'
        result = subprocess.run([sys.executable, str(GRADE), str(missing)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_missing_stream_exits_2(self):
        target = self.copy_fixture('pass')
        (target / 'stream.jsonl').unlink()
        result = subprocess.run([sys.executable, str(GRADE), str(target)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2, result.stderr)


class VerifyBoardDrainRunScript(unittest.TestCase):
    def test_run_script_parses(self):
        result = subprocess.run(['bash', '-n', str(RUN)], capture_output=True, text=True,
                                check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def break_branch(self):
        lines = RUN.read_text().splitlines()
        starts = [i for i, line in enumerate(lines)
                  if line.strip() == 'if [ -n "$BREAK" ]; then']
        self.assertEqual(len(starts), 1, 'expected one break branch in run')
        ends = [i for i in range(starts[0] + 1, len(lines))
                if lines[i].strip() in ('else', 'fi')]
        self.assertTrue(ends, 'the break branch is never closed')
        return lines[starts[0] + 1:ends[0]]

    def test_run_script_keeps_the_hooks(self):
        text = RUN.read_text()
        self.assertNotIn('setting-sources', text, 'a run must never drop user hooks')

    def test_run_script_builds_both_prompts(self):
        text = RUN.read_text()
        self.assertEqual(text.count("printf '/board-drain %s\\n' \"$JOB\""), 1,
                         'the normal run must start the prompt with /board-drain')
        branch = '\n'.join(self.break_branch())
        self.assertIn("printf '%s\\n' \"$JOB\"", branch,
                      'the break must build the job-only prompt')
        self.assertNotIn('/board-drain', branch,
                         'the break must never tell the chat /board-drain')

    def test_break_removes_board_drain_itself(self):
        """Dropping the command alone cannot fail: the skill loads on a restart prompt."""
        branch = '\n'.join(self.break_branch())
        self.assertIn('CLAUDE_ARGS+=(--disable-slash-commands)', branch,
                      'the break must take the skills away, else it cannot fail')
        normal = RUN.read_text().split('else', 1)[1]
        self.assertNotIn('--disable-slash-commands', normal,
                         'the real run must keep its skills')

    def test_run_script_seeds_a_dead_loop(self):
        text = RUN.read_text()
        self.assertIn('BOARD_DRAIN_STATE_DIR="$W/state"', text)
        self.assertIn('status --name "$NAME"', text)
        self.assertIn('if [ "$seed_exit" -ne 2 ]', text,
                      'the run must prove the seeded loop reads as not armed')

    def test_run_script_sets_the_chat_environment(self):
        text = RUN.read_text()
        for setting in ('BOARD_DRAIN_STATE_DIR="$W/state"', 'HT_TOKEN="$TOKEN"',
                        'SHIP_SESSION_NAME="$NAME"'):
            self.assertIn(setting, text)

    def test_run_script_never_prints_the_token(self):
        text = RUN.read_text()
        self.assertIn('TOKEN=$(cat "$TOKEN_FILE")', text)
        self.assertNotIn('echo "$TOKEN"', text)
        self.assertNotIn('printf \'%s\\n\' "$TOKEN"', text)

    def test_run_script_scrubs_and_grades(self):
        text = RUN.read_text()
        self.assertIn('REDACTED', text)
        self.assertIn('"$GRADE" "$E" --board "$BOARD"', text)

    def test_grade_script_has_shebang(self):
        self.assertEqual(GRADE.read_text().splitlines()[0], '#!/usr/bin/env python3')

    def test_scripts_are_executable(self):
        self.assertTrue(GRADE.stat().st_mode & 0o111, '%s is not executable' % GRADE)
        self.assertTrue(RUN.stat().st_mode & 0o111, '%s is not executable' % RUN)


if __name__ == '__main__':
    unittest.main()
