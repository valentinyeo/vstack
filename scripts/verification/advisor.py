import json
import os
import re
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

MODEL = os.environ['VERIFIER_MODEL']
OUT = Path('evidence')
OUT.mkdir(exist_ok=True)
prompt = f'''Read {max((Path.home() / ".claude/plugins/cache/cursor-plugins/pstack").glob("*"), key=lambda p: tuple(int(n) for n in p.name.split(".") if n.isdigit()))}/skills/poteto-mode/worker.md before anything else.
Read book/CHECKLIST.md next.
Read .github/briefs/shared-worker-rules.md, the shared worker rules.
{Path(".github/briefs/shared-worker-rules.md").read_text()}
Without service access, report faults in your verdict before workarounds.
Goal: Lauren's setup. vstack publicly owns shared checks.
You are an independent verifier from a different model family than the author, verifying SOFT-2590.
You run on GitHub-hosted Ubuntu. Never edit candidates, push, or merge.
pstack: skills/poteto-mode/playbooks/refactoring.md
Candidate: current checkout. Head SHA: {os.environ['HEAD_SHA']}.
Port ticket: SOFT-2588. Scope: require both fault reporting destinations on one worker brief line.
Read the diff against the PR base, then drive every changed hook.
Run hooks/*.py --self-test and the focused tests named in advisor-checks.
Run the migration tests and installer tests too.
Try three independent break attempts using real stdin/transcripts.
The source PR lives in a private repo. State that limit.
Tests were committed before the fix. Inspect that commit and its parent.
Reproduce failure using the test-only commit in a temporary worktree.
Do not require unrelated private persona content or runtime installation.
Batch related reads and commands. Finish once evidence covers the bar.
Audit CI wiring and the rule table.
No user-facing app changed; feature maps are not applicable.
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
for iteration in range(40):
    if iteration == 39:
        messages.append({'role': 'user', 'content': 'Tool budget exhausted. Return your final JSON verdict now. Use FAIL if evidence is insufficient. Do not invent evidence.'})
    body = {'model': MODEL, 'messages': messages, 'tools': [tool], 'max_tokens': 6500}
    if iteration == 39:
        body['tool_choice'] = 'none'
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
        if not raw.startswith('{'):
            blocks = re.findall(r'^```(?:json)?[ \t]*\r?\n(.*?)^```[ \t]*$', raw, re.M | re.S)
            if len(blocks) != 1:
                raise ValueError('Expected one JSON verdict')
            raw = blocks[0].strip()
        verdict = json.loads(raw)
        assert iteration > 0, 'verifier must drive the code'
        assert verdict['head_sha'] == os.environ['HEAD_SHA'], 'wrong head'
        assert verdict['verdict'] in ('PASS', 'PASS+NOTES', 'FAIL'), 'invalid verdict'
        (OUT / 'verdict.json').write_text(json.dumps(verdict, indent=2))
        (OUT / 'verdict.md').write_text(
            f"{verdict['verdict']}\n\nVerifier model: {MODEL}, independent pstack verifier.\n"
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
