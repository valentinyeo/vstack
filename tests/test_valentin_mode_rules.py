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


class ValentinModeRules(unittest.TestCase):
    def setUp(self):
        self.rows = json.loads((ROOT / 'skills/valentin-mode/board-rules.json').read_text())
        self.skill = (ROOT / 'skills/valentin-mode/SKILL.md').read_text()

    def test_all_seven_rules_are_registered(self):
        self.assertEqual({row['id'] for row in self.rows}, {
            'pr-owner', 'proof-before-merge', 'ticket-cap', 'agent-pr-cap',
            'repo-pr-cap', 'orphan-recovery', 'orphan-first',
        })
        self.assertEqual(len(self.rows), 7)

    def test_every_rule_sentence_is_in_board_rules(self):
        block = self.skill.split('## Board rules\n', 1)[1].split('\n## ', 1)[0]
        for row in self.rows:
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
        self.assertNotIn('expected', json.dumps(request))
        self.assertNotIn('criteria', json.dumps(request))
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
            (cases / 'scenarios.json').write_text('{"1": "This is a test"}')
            with self.assertRaises(ValueError):
                eval_run.organic_request(root)

    def test_expected_answers_cover_every_scenario(self):
        questions = json.loads((eval_run.CASES / 'scenarios.json').read_text())
        guidance = json.loads((eval_run.CASES / 'judge-only.json').read_text())
        self.assertEqual(set(questions), set(guidance['expected']))
        self.assertGreaterEqual(len(questions), 7)
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
