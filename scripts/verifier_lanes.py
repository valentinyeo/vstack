"""verifier_lanes: every lane and model a vstack verifier falls through, in order.

  verifier_lanes.models(workspace, fallback)   every allowed verifier model, from the base checkout's picker
  verifier_lanes.attempts(wanted, env)         (lane, model) pairs, every first-lane attempt first

Lanes, in order: opencode-go with the model id, used only when OPENCODE_API_KEY is set; then
vercel-ai-gateway with the provider id, used only when AI_GATEWAY_API_KEY is set. Every model on the
first lane is tried before the second lane starts.
"""
import os
import re
import subprocess
import sys

LANES = (
    ("opencode-go", "OPENCODE_API_KEY", {}),
    ("vercel-ai-gateway", "AI_GATEWAY_API_KEY", {
        "deepseek-v4.1-flash": "deepseek/deepseek-v4.1-flash",
        "glm-5.3-flash": "zai/glm-5.3-flash",
        "kimi-k3": "moonshotai/kimi-k3",
    }),
)
PICKER = os.path.join("picker-base", "scripts", "pick-verifier-model")
QUOTA = re.compile(r"\b429\b|\bquota\b|rate.?limit|credit balance", re.I)


def models(workspace, fallback):
    """The allowed models the base checkout's picker lists, or [fallback] when it cannot list every one."""
    picker = os.path.join(workspace or "", PICKER)
    if not os.path.isfile(picker):
        return [fallback]
    result = subprocess.run([sys.executable, "-I", picker, "--all"], capture_output=True, text=True)
    found = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return found if result.returncode == 0 and found else [fallback]


def attempts(wanted, env):
    """(lane, model) for every wanted model on each lane that has a key, every first-lane attempt first."""
    return [(lane, ids.get(model, model)) for lane, key, ids in LANES if env.get(key) for model in wanted]
