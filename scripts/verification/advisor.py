import json
import os
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

MODEL = 'deepseek-v4.1-flash'
OUT = Path('evidence')
OUT.mkdir(exist_ok=True)
prompt = f'''Read {max((Path.home() / ".claude/plugins/cache/cursor-plugins/pstack").glob("*"), key=lambda p: tuple(int(n) for n in p.name.split(".") if n.isdigit()))}/skills/poteto-mode/worker.md before anything else.
Read book/CHECKLIST.md next.
Goal: Lauren's setup. vstack publicly owns shared checks.
You are DeepSeek Flash, independently verifying Codex-authored SOFT-2590.
You run on GitHub-hosted Ubuntu. Never edit candidates, push, or merge.
pstack: skills/poteto-mode/playbooks/refactoring.md
Candidate: current checkout. Head SHA: {os.environ['HEAD_SHA']}.
The original hooks came from private advisor self-gate.
The author records baseline equivalence outside this public checkout.
You cannot independently fetch the private original. State that limit.
Sensitive names were removed.
Four hooks must retain exact behavior. book-check's diagnostic path changes.
out-of-bounds uses configured anonymous project names, regex-escaped.
Read the diff and drive all real hooks using run_command.
Run every hook --self-test, the migration tests, and installer tests.
Try three independent break attempts using real stdin/transcripts.
Audit CI wiring, copied checklist, rule table, and correction routing.
Do not require migration of remaining files or runtime hook installation.
No user-facing app changed; feature maps are not applicable.
The author committed migration tests before the fix and saw failures.
Inspect git history. Reproduce their failure in a temporary base worktree.
Before verdict perform pstack no-comments review. Report findings only.
Hold only for failures at this head or bugs introduced here.
Base bugs get notes. No extra gates. Never ask humans questions.
Return only JSON with verdict PASS/PASS+NOTES/FAIL, head_sha,
evidence, break_attempts, notes. No invented test results.
'''
messages = [{'role': 'system', 'content': 'You are an independent skeptical verification agent. Use tools to establish evidence. Never claim unrun tests.'},
            {'role': 'user', 'content': prompt}]
tool = {'type': 'function', 'function': {'name': 'run_command', 'description': 'Run read-only inspection or verification on the GitHub runner. Temporary test files/worktrees allowed. Never push, merge or modify candidate checkouts.',
        'parameters': {'type': 'object', 'properties': {'command': {'type': 'string'}}, 'required': ['command']}}}
for iteration in range(24):
    body = {'model': MODEL, 'messages': messages, 'tools': [tool], 'max_tokens': 6500}
    req = urllib.request.Request('https://opencode.ai/zen/go/v1/chat/completions',
          data=json.dumps(body).encode(), headers={'Authorization': 'Bearer ' + os.environ['OPENCODE_API_KEY'],
                    'Content-Type': 'application/json', 'User-Agent': 'pstack-verifier/1.0',
                    'x-opencode-session': os.environ['GITHUB_RUN_ID']})
    try:
        with urllib.request.urlopen(req, timeout=240) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors='replace').replace(os.environ['OPENCODE_API_KEY'], '<redacted>')
        print('Provider request failed:', exc.code, detail[:1000])
        raise SystemExit(1)
    except Exception as exc:
        print('Provider request failed:', type(exc).__name__)
        raise SystemExit(1)
    msg = result['choices'][0]['message']
    messages.append(msg)
    calls = msg.get('tool_calls') or []
    if not calls:
        content = msg.get('content') or ''
        (OUT / 'verdict.txt').write_text(content)
        raw = content.strip()
        if raw.startswith('```'):
            raw = raw.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        verdict = json.loads(raw)
        assert iteration > 0, 'verifier must drive the code'
        assert verdict['head_sha'] == os.environ['HEAD_SHA'], 'wrong head'
        assert verdict['verdict'] in ('PASS', 'PASS+NOTES', 'FAIL'), 'invalid verdict'
        (OUT / 'verdict.json').write_text(json.dumps(verdict, indent=2))
        (OUT / 'verdict.md').write_text(
            f"{verdict['verdict']}\n\nDeepSeek Flash independent pstack verifier.\n"
            f"Head: `{verdict['head_sha']}`\n\n" + json.dumps(verdict, indent=2) + '\n')
        (OUT / 'transcript.json').write_text(json.dumps(messages, indent=2))
        print(content)
        break
    for call in calls:
        command = json.loads(call['function']['arguments'])['command']
        env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ('TOKEN', 'SECRET', 'KEY'))}
        try:
            run = subprocess.run(['bash', '-lc', command], capture_output=True, text=True, timeout=180, env=env)
            output = f'$ {command}\nexit={run.returncode}\n{run.stdout}{run.stderr}'
        except subprocess.TimeoutExpired:
            output = f'$ {command}\nTIMEOUT after 180 seconds'
        print(output[:24000], flush=True)
        with (OUT / 'commands.log').open('a') as fh:
            fh.write(output + '\n')
        messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': output[:36000]})
    (OUT / 'transcript.json').write_text(json.dumps(messages, indent=2))
else:
    raise SystemExit('Verifier reached tool-turn limit without verdict')
