# Responsive mode load

The `responsive` check proves one thing: responsive mode's rules are in the chat without the chat choosing to fetch them.

## Why the old check passed the wrong test

Valentin mode's body used to carry a shell line that printed responsive mode's body, and the check looked for that body in a user turn. On 22 Nov 2026 a real run (`~/.local/state/verify-valentin-mode/20261122T183203Z`) ran the line itself and the whole body arrived in a Bash result. The grader read only user turns, so it graded FAIL while the rules were in fact in context. The line is a choice either way: a SKILL.md body is plain text, so nothing makes the model run it.

## What replaced it

`skills/valentin-mode/context.py` is a PreToolUse hook declared in the skill's frontmatter. At the chat's first tool call it hands the model the version line and responsive mode's body as `hookSpecificOutput.additionalContext`. Each tool call also adds a reminder there if Valentin's newest message has no reply. No reply check sets `permissionDecision` or denies a tool call. Later calls print `{}` once his newest message has a reply. The harness delivers the context without the chat choosing to fetch it.

## What the check reads

- evidence: `debug.log` holds `Hook PreToolUse (...) provided additionalContext (N chars)` naming `context.py`, and the body's last sentence.
- a `Skill` call for `responsive-mode`, or a user prompt starting `/responsive-mode`, still passes.
- a body that arrives only in a tool result, or a hook that stopped before the last sentence, fails.

`checks loaded` lists every hook the frontmatter declares, so a hook that never ran fails there too. Claude Code registers only one command per hook event from a skill's frontmatter, so `context.py` is the skill's one PreToolUse hook and it also runs responsive mode's reply guard.

Proof: `tests/fixtures/verify-valentin-mode/hook-injected` grades PASS on the hook alone, and `paste-in-tool-result` (the 22 Nov shape) grades FAIL. `tests/test_valentin_mode_context.py` proves the rules arrive once per chat, unanswered messages get reminders without a permission decision, replies stop the reminders, and the hook fails open.
