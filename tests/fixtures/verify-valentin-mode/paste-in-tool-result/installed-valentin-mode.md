---
name: valentin-mode
description: >-
  Work in Valentin's style on top of pstack, on his projects. Starts only
  when invoked with /valentin-mode, never on its own.
disable-model-invocation: true
hooks:
  PreToolUse:
    - matcher: "*"
      hooks:
        - type: command
          command: python3 "$CLAUDE_PLUGIN_ROOT/../responsive-mode/reply-check.py"
  Stop:
    - hooks:
        - type: command
          command: python3 "$CLAUDE_PLUGIN_ROOT/../responsive-mode/said-started.py"
---

# Valentin mode

!`sh "${CLAUDE_SKILL_DIR}/version.sh"`

## Responsive mode (injected by the hook)

!`awk 'c>=2{print} /^---$/{c++}' "${CLAUDE_SKILL_DIR}/../responsive-mode/SKILL.md"`

## Three tools

board login, plan-pick --run, reconcile.
