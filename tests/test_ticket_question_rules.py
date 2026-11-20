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
sweep = load("blocker_sweep", ROOT / "skills/hypertask/scripts/blocker-sweep.py")


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


class SweepStaleTest(unittest.TestCase):
    def test_answered_wins(self):
        self.assertEqual(sweep.classify(True, "ticket sits in Done", True), "ANSWERED")

    def test_done_column_is_stale(self):
        self.assertEqual(sweep.classify(False, "ticket sits in No Flag", True), "STALE")

    def test_question_without_question_line(self):
        self.assertEqual(sweep.classify(False, "", False), "NO-QUESTION")

    def test_real_question_waits(self):
        self.assertEqual(sweep.classify(False, "", True), "WAITING")

    def test_merged_pr_after_the_question_is_stale(self):
        task = {"pullRequests": [
            {"number": 2498, "lifecycle": "merged", "updatedAt": "2026-10-29T15:52:58.823Z"},
        ]}
        self.assertIn("2498", sweep.merged_since(task, "2026-10-24T21:42:54.239Z"))

    def test_merged_pr_before_the_question_is_not_stale(self):
        task = {"pullRequests": [
            {"number": 2115, "lifecycle": "merged", "updatedAt": "2026-10-20T03:38:53.133Z"},
        ]}
        self.assertEqual(sweep.merged_since(task, "2026-10-24T21:42:54.239Z"), "")

    def test_open_pr_is_not_stale(self):
        task = {"pullRequests": [
            {"number": 2500, "lifecycle": "open", "updatedAt": "2026-10-30T15:52:58.823Z"},
        ]}
        self.assertEqual(sweep.merged_since(task, "2026-10-24T21:42:54.239Z"), "")


if __name__ == "__main__":
    unittest.main()
