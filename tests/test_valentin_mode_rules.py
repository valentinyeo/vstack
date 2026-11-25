import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('board_guidance', ROOT / 'scripts/valentin-mode-eval.py')
eval_run = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(eval_run)

LADDER_CALL = '''#!/usr/bin/env python3
import json, sys
from pathlib import Path
here = Path(__file__).resolve().parent
queue = json.loads((here / 'responses.json').read_text())
request = json.loads(sys.stdin.read())
with (here / 'calls.log').open('a') as log:
    log.write(json.dumps({'argv': sys.argv[1:], 'request': request}) + '\\n')
answer = queue.pop(0)
(here / 'responses.json').write_text(json.dumps(queue))
print(json.dumps(answer))
'''
MODEL_FAMILIES = 'def model_family(model):\n    return model.split("-")[0]\n'
CANDIDATE = 'deepseek-v4.1-flash'
JUDGE = 'zai-glm-5.3-flash'
TOOL_ONLY = ('\n\n<\uff5cDSML\uff5c calls>\n<\uff5cDSML\uff5c invoke name="Bash">\n'
             '<\uff5cDSML\uff5c parameter name="command" string="true">true'
             '</\uff5cDSML\uff5c parameter>\n</\uff5cDSML\uff5c invoke>\n'
             '</\uff5cDSML\uff5c calls>')
ANSWER = json.dumps({
    '1': 'You already own 5 tickets in flight, so no: ship one before starting a Todo ticket.',
    '2': 'Restart a fresh worker on its PR within the hour, or park it: close the PR with a '
         'note, keep the branch, move the card back to Todo.',
})
BROKEN_JUDGE = ('Here is my grading: {"1": {"pass": true, "reason": "ok"}\n'
                ' "2": {"pass": true, "reason": "ok"}}')


class ValentinModeRules(unittest.TestCase):
    def setUp(self):
        self.rows = json.loads((ROOT / 'skills/valentin-mode/board-rules.json').read_text())
        self.skill = (ROOT / 'skills/valentin-mode/SKILL.md').read_text()

    def test_all_eight_rules_are_registered(self):
        self.assertEqual({row['id'] for row in self.rows}, {
            'pr-owner', 'proof-before-merge', 'ticket-cap', 'agent-pr-cap',
            'repo-pr-cap', 'orphan-recovery', 'orphan-first', 'ui-video-proof',
        })
        self.assertEqual(len(self.rows), 8)

    def test_every_rule_sentence_is_in_board_rules(self):
        for row in self.rows:
            section = row.get('section', 'Board rules')
            block = self.skill.split(f'## {section}\n', 1)[1].split('\n## ', 1)[0]
            with self.subTest(rule=row['id']):
                self.assertTrue(row['rule'].strip())
                self.assertTrue(row['sentence'].strip())
                self.assertIn(row['sentence'], block, f"Missing sentence for {row['id']}")

    def test_tools_exist_unless_pending_a_ticket(self):
        for row in self.rows:
            with self.subTest(rule=row['id']):
                pending = row['status'].startswith('pending ')
                if pending:
                    self.assertRegex(row['status'], r'^pending VSTA-\d+$')
                else:
                    self.assertEqual(row['status'], 'active')
                self.assertTrue(row['tools'])
                for tool in row['tools']:
                    self.assertTrue(tool['name'].strip())
                    path = Path(tool['path'])
                    self.assertFalse(path.is_absolute())
                    self.assertNotIn('..', path.parts)
                    if not pending:
                        self.assertTrue((ROOT / path).is_file(), f"Missing tool: {path}")

    def test_candidate_context_is_blind_and_contains_the_rules(self):
        request = eval_run.organic_request()
        self.assertIsNone(eval_run.BLIND.search(json.dumps(request)))
        self.assertEqual([m['role'] for m in request['messages']], ['system', 'user'])
        for row in self.rows:
            self.assertIn(row['sentence'], request['messages'][0]['content'])
        self.assertNotIn('board-rules.json', json.dumps(request))

    def test_forbidden_scenario_words_are_rejected(self):
        with tempfile.TemporaryDirectory() as where:
            root = Path(where)
            for source in eval_run.SOURCES:
                path = root / source
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('Board instructions')
            cases = root / 'evals/valentin-mode'
            cases.mkdir(parents=True)
            (cases / 'scenarios.json').write_text('{"1": "What should I do next?"}')
            original = eval_run.organic_request(root)
            (cases / 'judge-only.json').write_text('{"expected": "PRIVATE ANSWER CANARY"}')
            self.assertEqual(eval_run.organic_request(root), original)
            self.assertNotIn('PRIVATE ANSWER CANARY', json.dumps(original))
            (cases / 'scenarios.json').write_text('{"1": "This is a test"}')
            with self.assertRaises(ValueError):
                eval_run.organic_request(root)

    def test_expected_answers_cover_every_scenario(self):
        questions = json.loads((eval_run.CASES / 'scenarios.json').read_text())
        guidance = json.loads((eval_run.CASES / 'judge-only.json').read_text())
        self.assertEqual(set(questions), set(guidance['expected']))
        self.assertGreaterEqual(len(questions), 8)
        self.assertTrue(all(guidance['expected'].values()))
        self.assertTrue(3 <= len(guidance['criteria']) <= 6)

    def test_judge_sees_no_model_identity(self):
        request = eval_run.judge_request({'1': 'What now?'}, 'Finish my PR.', {'expected': {'1': 'Ship'}})
        text = json.dumps(request)
        self.assertIn('Chat A', text)
        self.assertNotIn('deepseek', text)
        self.assertNotIn('glm', text)

    def test_judge_family_is_excluded_and_checked(self):
        questions = json.loads((eval_run.CASES / 'scenarios.json').read_text())
        grades = {key: {'pass': True, 'reason': 'Correct action'} for key in questions}
        answer = {'model': 'deepseek', 'choices': [{'message': {'content': 'My next actions'}}]}
        for family in ('zai', 'deepseek'):
            with self.subTest(family=family), tempfile.TemporaryDirectory() as where:
                verdict = {'model': family, 'choices': [{'message': {'content': json.dumps(grades)}}]}
                with patch('sys.argv', ['board', '--ladder', '/lanes/ladder-call', '--out', where]), \
                        patch.object(eval_run.runpy, 'run_path', return_value={'model_family': lambda m: m}), \
                        patch.object(eval_run, 'call', side_effect=[answer, verdict]) as calls:
                    if family == 'deepseek':
                        with self.assertRaisesRegex(ValueError, 'another model family'):
                            eval_run.main()
                    else:
                        eval_run.main()
                    self.assertEqual(calls.call_args.kwargs['excluded'], 'deepseek')
                    self.assertNotIn('deepseek', json.dumps(calls.call_args.args[0]))

    def fake_ladder(self, root, rows):
        lanes = root / 'lanes'
        lanes.mkdir()
        ladder = lanes / 'ladder-call'
        ladder.write_text(LADDER_CALL)
        ladder.chmod(0o755)
        (lanes / 'model_families.py').write_text(MODEL_FAMILIES)
        (lanes / 'responses.json').write_text(json.dumps(rows))
        return ladder

    def run_eval(self, ladder, out):
        with patch('sys.argv', ['board', '--ladder', str(ladder), '--out', str(out)]):
            eval_run.main()

    def reply(self, model, text):
        return {'model': model, **self.message(text)}

    def message(self, text):
        return {'choices': [{'message': {'content': text}}]}

    def grades(self, failing=None):
        questions = json.loads((eval_run.CASES / 'scenarios.json').read_text())
        return {key: {'pass': key != failing, 'reason': 'Correct action'}
                for key in questions}

    def test_answer_text_ignores_tool_calls_and_keeps_prose(self):
        self.assertEqual(eval_run.answer_text(self.message('')), '')
        self.assertEqual(eval_run.answer_text(self.message('  \n\t')), '')
        self.assertEqual(eval_run.answer_text(self.message(None)), '')
        self.assertEqual(eval_run.answer_text(self.message(TOOL_ONLY)), '')
        self.assertEqual(eval_run.answer_text(self.message('Tool call coming.\n' + TOOL_ONLY)),
                         'Tool call coming.')
        self.assertEqual(eval_run.answer_text(self.message(ANSWER)), ANSWER)

    def test_tool_call_only_reply_is_retried_then_judged(self):
        rows = [self.reply(CANDIDATE, TOOL_ONLY), self.reply(CANDIDATE, ANSWER),
                self.reply(JUDGE, json.dumps(self.grades()))]
        with tempfile.TemporaryDirectory() as where:
            root, out = Path(where), Path(where) / 'evidence'
            ladder = self.fake_ladder(root, rows)
            self.run_eval(ladder, out)
            self.assertFalse((out / 'no-answer.json').exists())
            for name in ('chat-a-response.json', 'chat-a-try2-response.json',
                         'judge-response.json'):
                with self.subTest(evidence=name):
                    self.assertTrue((out / name).is_file())
            judged = (out / 'judge-request.json').read_text()
            self.assertIn('ship one before starting a Todo ticket', judged)
            self.assertNotIn('DSML', judged)
            calls = (ladder.parent / 'calls.log').read_text().splitlines()
            self.assertEqual(len(calls), 3)

    def test_empty_answer_three_times_is_an_infrastructure_error(self):
        blank = self.reply(CANDIDATE, ' \n')
        with tempfile.TemporaryDirectory() as where:
            root, out = Path(where), Path(where) / 'evidence'
            ladder = self.fake_ladder(root, [blank, blank, blank])
            with self.assertRaises(SystemExit) as raised:
                self.run_eval(ladder, out)
            message = str(raised.exception)
            self.assertIn('no answer after 3 tries', message)
            self.assertNotIn('Scenario', message)
            evidence = json.loads((out / 'no-answer.json').read_text())
            self.assertEqual(evidence['error'], 'no answer')
            self.assertEqual(evidence['kind'], 'infrastructure error')
            self.assertEqual(evidence['tries'], 3)
            self.assertFalse((out / 'judge-request.json').exists())
            calls = (ladder.parent / 'calls.log').read_text().splitlines()
            self.assertEqual(len(calls), 3)

    def test_wrong_answer_still_fails_as_before(self):
        rows = [self.reply(CANDIDATE, ANSWER),
                self.reply(JUDGE, json.dumps(self.grades(failing='1')))]
        with tempfile.TemporaryDirectory() as where:
            root, out = Path(where), Path(where) / 'evidence'
            ladder = self.fake_ladder(root, rows)
            with self.assertRaisesRegex(ValueError, 'Scenario 1 failed'):
                self.run_eval(ladder, out)
            self.assertFalse((out / 'no-answer.json').exists())
            self.assertFalse((out / 'no-verdict.json').exists())

    def test_judge_json_is_read_from_a_code_fence(self):
        fenced = '```json\n' + json.dumps(self.grades()) + '\n```'
        rows = [self.reply(CANDIDATE, ANSWER), self.reply(JUDGE, fenced)]
        with tempfile.TemporaryDirectory() as where:
            root, out = Path(where), Path(where) / 'evidence'
            ladder = self.fake_ladder(root, rows)
            self.run_eval(ladder, out)
            self.assertFalse((out / 'no-verdict.json').exists())
            self.assertTrue((out / 'judge-response.json').is_file())
            self.assertEqual(len((ladder.parent / 'calls.log').read_text().splitlines()), 2)

    def test_verdict_json_reads_fenced_and_prose_wrapped_answers(self):
        grades = {'1': {'pass': True, 'reason': 'ok'}}
        body = json.dumps(grades)
        self.assertEqual(eval_run.verdict_json(body), grades)
        self.assertEqual(eval_run.verdict_json(f'```json\n{body}\n```'), grades)
        self.assertEqual(eval_run.verdict_json(f'My grading:\n{body}\nDone.'), grades)
        with self.assertRaises(ValueError):
            eval_run.verdict_json('PASS')

    def test_broken_judge_answer_is_asked_again(self):
        rows = [self.reply(CANDIDATE, ANSWER), self.reply(JUDGE, BROKEN_JUDGE),
                self.reply(JUDGE, json.dumps(self.grades()))]
        with tempfile.TemporaryDirectory() as where:
            root, out = Path(where), Path(where) / 'evidence'
            ladder = self.fake_ladder(root, rows)
            self.run_eval(ladder, out)
            self.assertFalse((out / 'no-verdict.json').exists())
            for name in ('judge-response.json', 'judge-try2-response.json'):
                with self.subTest(evidence=name):
                    self.assertTrue((out / name).is_file())
            self.assertEqual(len((ladder.parent / 'calls.log').read_text().splitlines()), 3)

    def test_broken_judge_answer_three_times_is_an_infrastructure_error(self):
        broken = self.reply(JUDGE, BROKEN_JUDGE)
        rows = [self.reply(CANDIDATE, ANSWER), broken, broken, broken]
        with tempfile.TemporaryDirectory() as where:
            root, out = Path(where), Path(where) / 'evidence'
            ladder = self.fake_ladder(root, rows)
            with self.assertRaises(SystemExit) as raised:
                self.run_eval(ladder, out)
            message = str(raised.exception)
            self.assertIn('judge gave no valid JSON after 3 tries', message)
            self.assertIn('infrastructure error', message)
            self.assertNotIn('Scenario', message)
            evidence = json.loads((out / 'no-verdict.json').read_text())
            self.assertEqual(evidence['error'], 'no verdict')
            self.assertEqual(evidence['kind'], 'infrastructure error')
            self.assertEqual(evidence['tries'], 3)
            self.assertFalse((out / 'no-answer.json').exists())
            self.assertEqual(len((ladder.parent / 'calls.log').read_text().splitlines()), 4)

    def test_all_scenarios_must_pass(self):
        passing = {'1': {'pass': True, 'reason': 'Correct action'},
                   '2': {'pass': True, 'reason': 'Correct deadline'}}
        self.assertEqual(eval_run.require_pass(json.dumps(passing), ('1', '2')), passing)
        bad = [
            {}, {'1': passing['1']}, {**passing, '3': passing['1']},
            {**passing, '2': {'pass': False, 'reason': 'Waited a day'}},
            {**passing, '2': {'pass': 'true', 'reason': 'Correct'}},
            {**passing, '2': {'pass': True, 'reason': ''}},
            {**passing, '2': True},
        ]
        for verdict in bad:
            with self.subTest(verdict=verdict), self.assertRaises(ValueError):
                eval_run.require_pass(json.dumps(verdict), ('1', '2'))
        with self.assertRaises(ValueError):
            eval_run.require_pass('PASS', ('1', '2'))


if __name__ == '__main__':
    unittest.main()
