"""A chat with an open ticket must not end its turn with nothing to wake it.

The fixtures copy the shapes found in a real 2.1.322 transcript: a Bash background result, an async
agent result, a finished `<task-notification>`, and a TaskStop call. The board call always goes to a
fake command, so no test reaches the network.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/responsive-mode'
CHECK = SKILL / 'idle-stop.py'
MESSAGE = ('Ticket {key} is still open and no background job is running, so nothing will wake this chat. '
           'Start the next step as a tracked background job (worker, CI watch or board watcher), or say '
           'what blocks it, then end the turn.')
START = ('Command running in background with ID: bxo4265ry. Output is being written to: '
         '/tmp/claude-1000/tasks/bxo4265ry.output.')


def human(text):
    return {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': text}]}}


def say(text):
    return {'type': 'assistant', 'isSidechain': False,
            'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}}


def background(result, job):
    return {'type': 'user', 'message': {'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': 'toolu_1', 'content': result}]},
        'toolUseResult': {'backgroundTaskId': job}}


def async_agent(job):
    return {'type': 'user', 'message': {'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': 'toolu_2',
         'content': 'Async agent launched successfully.\nagentId: ' + job + ' (internal ID)'}]},
        'toolUseResult': {'isAsync': True, 'status': 'async_launched', 'agentId': job}}


def notification(job, status='completed'):
    return {'type': 'user', 'message': {'role': 'user', 'content': (
        '<task-notification>\n<task-id>' + job + '</task-id>\n<status>' + status +
        '</status>\n</task-notification>')}}


def task_stop(job):
    return {'type': 'assistant', 'message': {'role': 'assistant', 'content': [
        {'type': 'tool_use', 'id': 'toolu_3', 'name': 'TaskStop', 'input': {'task_id': job}}]}}


def agy_human(text):
    return {'type': 'USER_INPUT', 'source': 'USER_EXPLICIT', 'status': 'DONE',
            'content': '<USER_REQUEST>\n' + text + '\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\n'
                       'The current local time is: 2026-11-26T15:39:46+01:00.\n</ADDITIONAL_METADATA>'}


def agy_reply(text, tool_calls=None):
    entry = {'type': 'PLANNER_RESPONSE', 'source': 'MODEL', 'status': 'DONE', 'content': text}
    if tool_calls:
        entry['tool_calls'] = tool_calls
    return entry


def agy_task_started(job):
    return {'type': 'GENERIC', 'source': 'MODEL', 'status': 'RUNNING',
            'content': 'Created At: 2026-11-26T15:39:55+01:00\nTool is running as a background task with '
                       'task id: ' + job + '\nTask Description: ./slow-report.sh\nTask logs are available '
                       'at: file:///tmp/' + job.replace('/', '-') + '.log\n'}


def agy_task_finished(job):
    return {'type': 'SYSTEM_MESSAGE', 'source': 'SYSTEM', 'status': 'DONE',
            'content': 'The following is a <SYSTEM_MESSAGE> not actually sent by the user.\n\n'
                       '<SYSTEM_MESSAGE>\n[Message] timestamp=2026-11-26T15:40:01Z sender=' + job +
                       ' priority=MESSAGE_PRIORITY_HIGH content=Task id "' + job +
                       '" finished with result:\nCommand exited with code 0.\n</SYSTEM_MESSAGE>'}


def agy_reminder():
    return {'type': 'SYSTEM_MESSAGE', 'source': 'SYSTEM', 'status': 'DONE',
            'content': '<SYSTEM_MESSAGE>\nReminder: work efficiently.\n</SYSTEM_MESSAGE>'}


def agy_kill(job):
    return agy_reply('', [{'name': 'manage_task',
                           'args': {'Action': 'kill', 'TaskId': job}}])


def agy_subagent(conversation):
    return {'type': 'GENERIC', 'source': 'MODEL', 'status': 'RUNNING',
            'content': 'Subagent is running in the background.\nconversationId: ' + conversation + '\n'}


def ticket(key, section='Doing', assignee='Idle Stop'):
    return {'ticketNumber': key, 'section': section,
            'assignees': [{'displayName': assignee, 'type': 'agent'}]}


class IdleStop(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.project = self.folder / 'project'
        self.project.mkdir()
        (self.project / 'CLAUDE.md').write_text('# project\n\nHypertask board: 13556, label: Idle Stop\n')
        self.token = self.folder / 'token'
        self.token.write_text('stub-token\n')
        self.calls = self.folder / 'calls.txt'
        self.fake = self.script('hypertask', json.dumps({'tasks': [ticket('VSTA-1')]}))
        self.slow = self.script('slow', '', sleep=30)

    def script(self, name, output, sleep=0):
        path = self.folder / name
        body = '#!/bin/sh\n' + (f'sleep {sleep}\n' if sleep else '') + f'printf %s {json.dumps(output)}\n'
        path.write_text(body)
        path.chmod(0o755)
        return path

    def hook(self, entries=None, cwd=None, transcript=None, payload=None, env=None):
        if transcript is None:
            transcript = str(self.folder / 'transcript.jsonl')
            Path(transcript).write_text(''.join(json.dumps(entry) + '\n' for entry in entries or []))
        if payload is None:
            payload = json.dumps({'hook_name': 'Stop', 'transcript_path': transcript,
                                  'cwd': str(cwd or self.project)})
        run_env = os.environ.copy()
        run_env.update({'HYPERTASK_AGENT_TOKEN_FILE': str(self.token),
                        'HYPERTASK_AGENT_NAME': 'Idle Stop',
                        'IDLE_STOP_CLI': str(self.fake),
                        'IDLE_STOP_TIMEOUT': '5',
                        'BOARD_DRAIN_STATE_DIR': str(self.folder / 'state')})
        if env:
            run_env.update(env)
        return subprocess.run([sys.executable, str(CHECK)], input=payload, text=True,
                              capture_output=True, check=False, env=run_env)

    def assert_allowed(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '', 'a passing turn prints nothing: ' + result.stdout)

    def assert_blocked(self, result, key='VSTA-1'):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'decision': 'block', 'reason': MESSAGE.format(key=key)})
        self.assertEqual(result.stderr, '')

    def test_a_live_background_job_allows(self):
        self.assert_allowed(self.hook([human('ship it'), background(START, 'bxo4265ry'),
                                       say('CI watcher is running.')]))

    def test_a_live_async_agent_allows(self):
        self.assert_allowed(self.hook([human('build it'), async_agent('ad4867cb12c16aa1a'),
                                       say('The worker is running.')]))

    def test_a_finished_job_blocks_with_its_ticket(self):
        entries = [human('ship it'), background(START, 'bxo4265ry'), notification('bxo4265ry'),
                   say('CI is green.')]
        self.assert_blocked(self.hook(entries))

    def test_a_failed_job_also_ends(self):
        entries = [human('ship it'), background(START, 'bxo4265ry'), notification('bxo4265ry', 'failed'),
                   say('The check failed.')]
        self.assert_blocked(self.hook(entries))

    def test_a_stopped_task_ends(self):
        entries = [human('ship it'), background(START, 'bxo4265ry'), task_stop('bxo4265ry'),
                   say('Stopped it.')]
        self.assert_blocked(self.hook(entries))

    def test_a_second_stop_check_in_the_same_turn_allows(self):
        entries = [human('ship it'), say('Nothing running.')]
        payload = json.dumps({'hook_name': 'Stop', 'transcript_path': str(self.folder / 't.jsonl'),
                              'cwd': str(self.project), 'stop_hook_active': True})
        self.assert_allowed(self.hook(entries, payload=payload))

    def test_a_question_allows(self):
        self.assert_allowed(self.hook([human('ship it'), say('One of three is open. Do you want it now?')]))

    def test_a_subagents_question_is_not_this_chats_reply(self):
        worker = {'type': 'assistant', 'isSidechain': True,
                  'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Shall I go on?'}]}}
        self.assert_blocked(self.hook([human('ship it'), worker, say('The worker is done.')]))

    def test_a_board_call_that_times_out_allows(self):
        started = time.monotonic()
        self.assert_allowed(self.hook([human('ship it'), say('Nothing running.')],
                                      env={'IDLE_STOP_CLI': str(self.slow), 'IDLE_STOP_TIMEOUT': '0.3'}))
        self.assertLess(time.monotonic() - started, 10)

    def test_a_failing_board_call_allows(self):
        self.assert_allowed(self.hook([human('ship it'), say('Nothing running.')],
                                      env={'IDLE_STOP_CLI': str(self.fake), 'IDLE_STOP_TIMEOUT': 'nonsense',
                                           'HYPERTASK_AGENT_TOKEN_FILE': str(self.folder / 'missing')}))

    def test_a_missing_board_line_allows(self):
        plain = self.folder / 'plain'
        plain.mkdir()
        self.assert_allowed(self.hook([human('ship it'), say('Nothing running.')], cwd=plain))

    def test_a_board_line_without_a_label_falls_back_to_the_loop_state(self):
        notes = self.folder / 'unlabelled'
        notes.mkdir()
        (notes / 'AGENTS.md').write_text('Hypertask board: 13556\n')
        state = self.folder / 'state'
        state.mkdir()
        (state / 'idle-stop.json').write_text(json.dumps({'name': 'Idle Stop', 'board': 13556,
                                                          'label': 'Idle Stop'}))
        self.assert_blocked(self.hook([human('ship it'), say('Nothing running.')], cwd=notes))

    def test_a_ticket_in_todo_or_another_agent_allows(self):
        for task in (ticket('VSTA-2', 'Todo'), ticket('VSTA-3', 'AI Review', 'Someone Else')):
            with self.subTest(section=task['section'], assignee=task['assignees'][0]['displayName']):
                self.fake = self.script('hypertask-' + task['ticketNumber'], json.dumps({'tasks': [task]}))
                self.assert_allowed(self.hook([human('ship it'), say('Nothing running.')]))

    def test_every_open_section_blocks(self):
        for section in ('Doing', 'In Progress', 'Checks', 'AI Review'):
            with self.subTest(section=section):
                self.fake = self.script('hypertask-' + section.replace(' ', '-'),
                                        json.dumps({'tasks': [ticket('VSTA-9', section)]}))
                self.assert_blocked(self.hook([human('ship it'), say('Nothing running.')]), 'VSTA-9')

    def test_the_board_call_uses_the_chats_own_login(self):
        args_file = self.folder / 'args.txt'
        mine = self.folder / 'record-args'
        mine.write_text('#!/bin/sh\nprintf %s "$*" > ' + str(args_file) + '\n'
                        + 'printf %s ' + json.dumps(json.dumps({'tasks': [ticket('VSTA-1')]})) + '\n')
        mine.chmod(0o755)
        self.assert_blocked(self.hook([human('ship it'), say('Nothing running.')],
                                      env={'IDLE_STOP_CLI': str(mine)}))
        args = args_file.read_text()
        for expected in ('--token stub-token', '--project 13556', '--label Idle Stop',
                         '--assigned-to me', 'task list'):
            self.assertIn(expected, args)

    def test_garbage_input_and_a_missing_transcript_allow(self):
        for payload in ('not json', '', '[1, 2, 3]', 'null', json.dumps({'cwd': str(self.project)})):
            with self.subTest(payload=payload):
                self.assert_allowed(self.hook(payload=payload))
        self.assert_allowed(self.hook(transcript='/nonexistent/transcript.jsonl'))

    def test_self_test_passes(self):
        result = subprocess.run([sys.executable, str(CHECK), '--self-test'], text=True,
                                capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('idle-stop self-test ok', result.stdout)


class AntigravityIdleStop(IdleStop):
    """The same guard on Antigravity, whose transcript.jsonl tracks background tasks its own way."""

    JOB = 'db4bd34a-dd15-4423-95de-28921cd102c5/task-4'

    def test_a_running_antigravity_task_allows(self):
        self.assert_allowed(self.hook([agy_human('ship it'), agy_task_started(self.JOB),
                                       agy_reply('The report job is running.')]))

    def test_a_finished_antigravity_task_blocks(self):
        entries = [agy_human('ship it'), agy_task_started(self.JOB), agy_task_finished(self.JOB),
                   agy_reply('The report is ready.')]
        self.assert_blocked(self.hook(entries))

    def test_a_killed_antigravity_task_blocks(self):
        entries = [agy_human('ship it'), agy_task_started(self.JOB), agy_kill(self.JOB),
                   agy_reply('Stopped it.')]
        self.assert_blocked(self.hook(entries))

    def test_antigravity_reminders_do_not_start_a_job(self):
        entries = [agy_human('ship it'), agy_reminder(), agy_reply('Nothing is running.')]
        self.assert_blocked(self.hook(entries))

    def test_a_finished_task_entry_does_not_count_as_live(self):
        done = dict(agy_task_started(self.JOB), status='DONE')
        self.assert_blocked(self.hook([agy_human('ship it'), done, agy_reply('Done.')]))

    def test_a_running_subagent_allows(self):
        entries = [agy_human('build it'), agy_subagent('conv-7f3c'), agy_reply('The worker is running.')]
        self.assert_allowed(self.hook(entries))

    def test_an_antigravity_question_allows(self):
        self.assert_allowed(self.hook([agy_human('ship it'),
                                       agy_reply('One of three is open. Do you want it now?')]))


class SkillWiring(unittest.TestCase):
    """Loading the skill is what switches the check on, so the wiring is part of the feature."""

    def test_responsive_mode_turns_the_check_on(self):
        text = (SKILL / 'SKILL.md').read_text()
        self.assertIn('command: python3 "$CLAUDE_PLUGIN_ROOT/idle-stop.py"', text)
        self.assertIn('command: python3 "$CLAUDE_PLUGIN_ROOT/said-started.py"', text)
        self.assertIn('Loading this skill turns on four checks in this chat', text)

    def test_valentin_mode_turns_the_check_on(self):
        text = (ROOT / 'skills/valentin-mode/SKILL.md').read_text()
        self.assertIn('command: python3 "$CLAUDE_PLUGIN_ROOT/../responsive-mode/idle-stop.py"', text)
        self.assertIn('command: python3 "$CLAUDE_PLUGIN_ROOT/../responsive-mode/said-started.py"', text)

    def test_the_check_sits_beside_the_skill(self):
        self.assertTrue(CHECK.is_file(), 'idle-stop.py is missing from the skill folder')


if __name__ == '__main__':
    unittest.main()
