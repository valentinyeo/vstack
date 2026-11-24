import importlib.machinery
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


lint_mod = load("ticket_lint", ROOT / "skills/hypertask/scripts/ticket-lint")


class SentenceStyleTest(unittest.TestCase):
    def test_a_whole_sentence_over_twelve_words_is_allowed(self):
        text = 'The update keeps your saved reports available while the next report finishes loading in the background.'
        self.assertEqual(lint_mod.lint(text), [])

    def test_a_needed_exact_path_is_allowed(self):
        self.assertEqual(lint_mod.lint('Read skills/hypertask/SKILL.md before changing the board.'), [])

    def test_a_sentence_over_twenty_five_words_needs_splitting(self):
        self.assertTrue(any('max 25' in error for error in lint_mod.lint('word ' * 26 + '.')))


class QuestionLintTest(unittest.TestCase):
    def bad(self, body):
        return "\n".join(lint_mod.question_rules(body))

    def test_money_ask_without_amount_is_refused(self):
        body = "Question: **Should we keep the paid plan?**\n\nMy recommendation: Yes.\n\nWhy: it saves money."
        self.assertIn("no amount", self.bad(body))

    def test_money_ask_with_amount_passes(self):
        body = "What this is: the paid plan for storing monthly reports. It needs your spending approval before renewal. Yes keeps the reports online. No cancels storage after this month.\n\nQuestion: **Should we keep the paid plan at $20 a month?**\n\nMy recommendation: Yes.\n\nWhy: it saves money."
        self.assertEqual(self.bad(body), "")

    def test_free_is_an_amount(self):
        body = "What this is: the log storage for our app errors. It needs your approval to move live data. Yes moves logs into free storage. No keeps the current paid bucket.\n\nQuestion: **Should we move the logs to the free bucket?**\n\nMy recommendation: Yes.\n\nWhy: no charge."
        self.assertEqual(self.bad(body), "")

    # Real asks from SOFT-2293, SOFT-2290, SOFT-1878 and SOFT-2308 that sat in his blockers until 2026-11-15.
    def test_design_pick_asks_are_refused(self):
        ctx = "What this is: the phone look for opening a chat table big. Desktop has it, the phone does not. It reached you because the design needs your pick. Yes builds it, no leaves it.\n\n"
        for q in [
            "Question: Build the table sheet with the expand button (B)?\n\nMy recommendation: Yes.",
            "Question: Add the skill pill to the kit and build option A?\n\nMy recommendation: Yes.",
            "Question: build A?\n\nMy recommendation: Yes, build A.",
            "Question: Which look do we build, A, B or C?\n\nMy recommendation: A.",
        ]:
            self.assertIn("design pick", self.bad(ctx + q), q)

    def test_money_option_ask_is_not_a_design_pick(self):
        body = ("What this is: the photo model for the calorie app. It reached you because it costs money per photo. "
                "Yes turns it on, no keeps the app without photo reading for now.\n\n"
                "Question: Pay for option A at $5 a month?\n\nMy recommendation: Yes.")
        self.assertNotIn("design pick", self.bad(body))

    def test_plain_decision_ask_is_not_a_design_pick(self):
        body = ("What this is: the old bank key copies in the data. It reached you because deleting live data is your call. "
                "Yes deletes them after a backup, no keeps them where they are today.\n\n"
                "Question: Delete the old key copies?\n\nMy recommendation: Yes.")
        self.assertNotIn("design pick", self.bad(body))

    def test_once_ask_is_refused(self):
        body = "Question: **Should this go live once the checks pass?**\n\nMy recommendation: Yes."
        self.assertIn("once X", self.bad(body))

    def test_his_own_words_are_not_refused(self):
        body = 'What this is: the paid calls for reading receipt photos. It needs your spending approval before renewal. Yes removes the paid photo reading. No keeps the monthly photo charges.\n\nQuestion: **Should we cut the paid calls?**\n\nMy recommendation: Yes.\n\n> "this costs money once a month"\n\nWhy: no charge.'
        self.assertEqual(self.bad(body), "")

    def test_plain_comment_is_not_checked(self):
        self.assertEqual(self.bad("Money is tight and we pay a lot once a week."), "")



if __name__ == '__main__':
    unittest.main()
