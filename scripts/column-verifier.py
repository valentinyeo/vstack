"""Run an independent DeepSeek Flash verifier on a GitHub-hosted runner."""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

root = Path.cwd()
sha = os.environ['HEAD_SHA']
scratch = Path(os.environ['RUNNER_TEMP']) / 'column-verifier'
scratch.mkdir(exist_ok=True)
key = os.environ.get('OPENCODE_API_KEY')
if not key:
    sys.exit('Missing existing DeepSeek plan login')
commands = json.loads(os.environ['VERIFY_COMMANDS'])
base = subprocess.check_output(['git', 'merge-base', sha, 'origin/' + os.environ['BASE_REF']], text=True).strip()
brief = f'''Read {root}/scripts/worker.md before anything else.
Goal: prepare board 2060 callers for Building and Verifier, accepting Doing and AI Review until renamed. PR opened -> Checks; green checks -> Verifier; merged -> Verifier pending live proof. current-head PASS, merged, and live proof -> Done. Never rename columns. Other boards keep their names.
You are the independent DeepSeek verifier after the Codex author. Run these commands in {root}: {json.dumps(commands)}.
Read git diff {base}..{sha}. Only diff-induced regressions block. Report unchanged base faults as notes. Reproduce proposed blockers on this base first. Read docs/soft-2446-evidence.md if present.
Try to break aliases, stale verdicts, missing checks, pagination, and preservation of other boards. Inspect comments under pstack no-comments: flag misleading or unnecessary new comments. Do not edit tracked files.
Test the real scripts, not merely syntax. A scoped fixture may replace external writes. No live board credentials are available on GitHub. The author's real-server read-only trace supplies the real-size baseline.
Write your final answer starting exactly VERDICT: PASS, VERDICT: PASS+NOTES or VERDICT: FAIL. State commands run and any remaining faults. A failed command or uncovered requested behavior means FAIL. Do not merge anything.'''
env = {'PATH': os.environ['PATH'], 'HOME': str(scratch / 'home'), 'LANG': 'C.UTF-8',
       'OPENCODE_API_KEY': key}
Path(env['HOME']).mkdir(exist_ok=True)
result = subprocess.run(['npx', '-y', '@earendil-works/pi-coding-agent@1.5.2', '-p',
                         '--no-session', '--no-extensions', '--no-skills', '--no-prompt-templates',
                         '--no-mcp', '--tools', 'read,bash', '--mode', 'json', '--provider', 'opencode-go', '--model',
                         'deepseek-v4.1-flash', '--thinking', 'medium', brief],
                        env=env, text=True, capture_output=True, timeout=1200)
trace = (result.stdout + '\n' + result.stderr).replace(key, '[REDACTED]')
(scratch / 'trace.jsonl').write_text(trace)
answers = []
started = {}
executed = []
for line in result.stdout.splitlines():
    try:
        event = json.loads(line)
    except ValueError:
        continue
    if event.get('type') == 'tool_execution_start' and event.get('toolName') == 'bash':
        started[event['toolCallId']] = (event.get('args') or {}).get('command', '')
    if event.get('type') == 'tool_execution_end' and event.get('toolName') == 'bash' and not event.get('isError'):
        executed.append(started.get(event.get('toolCallId'), ''))
    message = event.get('message') or {}
    if event.get('type') == 'message_end' and message.get('role') == 'assistant':
        answers.append('\n'.join(c.get('text', '') for c in message.get('content', []) if c.get('type') == 'text'))
answer = answers[-1] if answers else ''
match = re.match(r'^VERDICT: (PASS\+NOTES|PASS|FAIL)\b', answer)
def normalize(command):
    try:
        return ' '.join(shlex.split(command))
    except ValueError:
        return ' '.join(command.split())

missing = [command for command in commands if not any(normalize(command) in normalize(actual) for actual in executed)]
clean = subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--']).returncode == 0
verdict = match.group(1) if result.returncode == 0 and match and not missing and clean else 'FAIL'
body = f'pstack-verifier: {verdict} @ {sha}\n\nDeepSeek deepseek-v4.1-flash, GitHub-hosted.\n\n'
body += answer.replace(key, '[REDACTED]') if answer else 'Verifier failed to return a verdict. See the command trace artifact.'
body += '\n\nMissing command evidence: ' + json.dumps(missing) if missing else ''
body += '\n\nVerifier changed tracked files.' if not clean else ''
body += f"\n\nTrace: https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}\n"
comment = scratch / 'comment.md'
comment.write_text(body)
subprocess.run(['gh', 'pr', 'comment', os.environ['PR_NUMBER'], '--repo', os.environ['GITHUB_REPOSITORY'],
                '--body-file', str(comment)], check=True)
print(body)
sys.exit(0 if verdict in ('PASS', 'PASS+NOTES') else 1)
