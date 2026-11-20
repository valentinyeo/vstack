#!/usr/bin/env python3
"""Is valentin-mode loaded in the chat that sent this hook input?

The lane hooks read this so they can be wired once in the global ~/.claude/settings.json and still act only in
a valentin-mode chat. A transcript from Claude Code 2.1 shows a load in one of three shapes:
  - a user turn carrying <command-name>/valentin-mode</command-name>
  - a Skill tool call whose input names the skill valentin-mode
  - the skill body's own first line, "Base directory for this skill: <path>/valentin-mode"

The transcript is read in 1 MiB chunks, because a long chat's transcript runs to hundreds of megabytes, and
only bytes near the word valentin-mode are parsed, so a plain chat's scan stays cheap. A missing, empty or
unreadable transcript means False, so every caller allows the tool call.

valentin_mode_loaded.py --self-test
"""
import re
from pathlib import Path
import sys
import tempfile

CHUNK = 1 << 20
KEEP = 512
WORD = b"valentin-mode"
COMMAND = re.compile(rb"<command-name>/valentin-mode</command-name>")
SKILL_CALL = re.compile(rb'"skill"\s*:\s*"valentin-mode"')
BASE_DIR = re.compile(rb"Base directory for this skill:\s*([^\s\"\\]+)")


def found(buffer):
    if COMMAND.search(buffer) or SKILL_CALL.search(buffer):
        return True
    return any(match.group(1).endswith(b"/valentin-mode") for match in BASE_DIR.finditer(buffer))


def loaded(transcript_path):
    if not isinstance(transcript_path, str) or not transcript_path:
        return False
    try:
        with open(transcript_path, "rb") as handle:
            carry = b""
            while True:
                chunk = handle.read(CHUNK)
                if not chunk:
                    return False
                buffer = carry + chunk
                at = buffer.find(WORD)
                while at != -1:
                    if found(buffer[max(0, at - KEEP):at + KEEP]):
                        return True
                    at = buffer.find(WORD, at + 1)
                carry = buffer[-KEEP:]
    except (OSError, TypeError):
        return False


def self_test():
    with tempfile.TemporaryDirectory() as where:
        def transcript(name, text):
            path = Path(where, name)
            path.write_text(text)
            return str(path)

        command = transcript("command.jsonl",
                             '{"type":"user","message":{"role":"user","content":'
                             '"<command-message>valentin-mode</command-message>\\n'
                             '<command-name>/valentin-mode</command-name>"}}\n')
        skill_call = transcript("skill-call.jsonl",
                                '{"type":"assistant","message":{"content":[{"type":"tool_use",'
                                '"name":"Skill","input":{"skill":"valentin-mode"}}]}}\n')
        base_dir = transcript("base-dir.jsonl",
                              '{"type":"user","message":{"content":[{"type":"tool_result",'
                              '"content":"Base directory for this skill: '
                              '/home/valentin/.claude/skills/valentin-mode\\n\\n# Valentin mode"}]}}\n')
        plain = transcript("plain.jsonl",
                           '{"type":"user","message":{"content":"should we load valentin-mode here? '
                           'the /valentin-mode skill it names"}}\n'
                           '{"type":"assistant","message":{"content":[{"type":"tool_use",'
                           '"name":"Bash","input":{"command":"ls"}}]}}\n')
        straddle = transcript("straddle.jsonl", "x" * (CHUNK - 10) +
                              '<command-name>/valentin-mode</command-name>\n')
        empty = transcript("empty.jsonl", "")
        assert loaded(command), "a /valentin-mode command turn is a load"
        assert loaded(skill_call), "a Skill tool call for valentin-mode is a load"
        assert loaded(base_dir), "the skill's base directory line is a load"
        assert loaded(straddle), "a marker across a chunk boundary is a load"
        assert not loaded(plain), "a chat that only talks about valentin-mode runs no valentin-mode"
        assert not loaded(empty), "an empty transcript allows"
        assert not loaded(str(Path(where, "gone.jsonl"))), "a missing transcript allows"
        assert not loaded(where), "an unreadable transcript allows"
        assert not loaded(None), "no transcript allows"
        assert not loaded(42), "a transcript that is not a path allows"
    print("valentin-mode-loaded self-test ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        sys.exit(0)
    sys.exit(0 if loaded(sys.stdin.read().strip()) else 1)
