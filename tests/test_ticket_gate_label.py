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


lint_mod = load("ticket_lint_gate", ROOT / "skills/hypertask/scripts/ticket-lint")


class GateLabelLintTest(unittest.TestCase):
    def robot_lines(self, body):
        return [bad for bad in lint_mod.lint(body) if "robot status" in bad]

    def test_heading_ending_in_gate_passes(self):
        for body in (
            "Observation gate: the page loaded fine.",
            "Acceptance gate: both cases answered.",
            "Full-day observation gate: steady overnight.",
        ):
            self.assertEqual(self.robot_lines(body), [], body)

    def test_bare_gate_label_opening_a_line_is_refused(self):
        for body in ("Gate: shipped and clean", "Gates: 3 of 5", "  Gate: indented"):
            self.assertTrue(self.robot_lines(body), body)

    def test_other_status_labels_are_still_refused(self):
        for label in ("Next", "Helpers", "Outputs", "Claimed", "Released", "Resume"):
            self.assertTrue(self.robot_lines(f"{label}: anything here"), label)


if __name__ == "__main__":
    unittest.main()
