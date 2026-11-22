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
          command: python3 "$CLAUDE_PLUGIN_ROOT/context.py"
  Stop:
    - hooks:
        - type: command
          command: python3 "$CLAUDE_PLUGIN_ROOT/../responsive-mode/said-started.py"
---

# Valentin mode

## Responsive mode (injected by the hook)

## Three tools

board login, plan-pick --run, reconcile.
