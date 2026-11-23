#!/usr/bin/env python3
"""Drive: one fresh headless chat in the scratch HOME loads /valentin-mode and runs one command.

The chat is the user path. A hook that errors, or a hook that blocks, is the failure this
skill exists to catch, so the run reads the harness's own hook lines, never the chat's words.

pstack create-verification-skill, "Drive": the harness recipe with real commands, and
poteto-mode/playbooks/shipping.md step 1 ("runs the change the way a user would").
Root cause: VSTA-137, https://app.hypertask.ai/detail/project-13556/137

drive.py --checkout DIR --scratch DIR --evidence DIR
Exit 0 PASS, 1 FAIL, 3 skipped (no live chat possible on this host).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

VERSION_LINE = re.compile(r'valentin-mode v\d+[^\n]*')
HOOK_ERROR = re.compile(r'Hooks?: .*finished with status ([1-9]\d*)')
HOOK_BLOCK = re.compile(r'(?i)hook .{0,120}\bblocked\b')
PROMPT = ('/valentin-mode Run exactly one Bash command in this folder: '
          'echo vstack-verify-ok > drove.txt . '
          'Then reply with the version line you were given.')


def skip(reason, evidence):
    (evidence / 'drive.txt').write_text(f'DRIVE SKIP {reason}\n')
    print(f'DRIVE SKIP {reason}')
    return 3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', required=True)
    parser.add_argument('--scratch', required=True)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    checkout, scratch = Path(args.checkout).resolve(), Path(args.scratch).resolve()
    evidence = Path(args.evidence)
    evidence.mkdir(parents=True, exist_ok=True)

    plan_pick = Path.home() / '.local/bin/plan-pick'
    if plan_pick.is_file():
        gate = subprocess.run([str(plan_pick), '--claude-helper'], capture_output=True, text=True)
        if gate.returncode != 0:
            return skip('Claude is ahead of pace: ' + ' '.join(gate.stdout.split())[:200], evidence)
    claude = shutil.which('claude')
    if not claude:
        return skip('no claude binary on PATH', evidence)
    if not os.environ.get('ANTHROPIC_API_KEY'):
        return skip('a live chat in the scratch HOME needs its own credentials, and Launch '
                    'copies no tokens; set ANTHROPIC_API_KEY to run Drive', evidence)

    workspace = scratch / 'chat' / 'vstack'
    workspace.mkdir(parents=True, exist_ok=True)
    archive = subprocess.run(['git', '-C', str(checkout), 'archive', 'HEAD'],
                             capture_output=True, check=True)
    subprocess.run(['tar', '-x', '-C', str(workspace)], input=archive.stdout, check=True)

    (evidence / 'drive-prompt.txt').write_text(PROMPT + '\n')
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('MULTIPROMPT_', 'HYPERTASK_'))
           and key not in ('HT_TOKEN', 'PLAN_PICK_WORKER')}
    env['HOME'] = str(scratch)
    command = [claude, '-p', PROMPT, '--model', 'sonnet', '--permission-mode',
               'bypassPermissions', '--output-format', 'stream-json', '--verbose',
               '--debug-file', str(evidence / 'debug.log'), '--max-turns', '12']
    with open(evidence / 'stream.jsonl', 'w') as out, \
            open(evidence / 'drive-stderr.txt', 'w') as err:
        try:
            finished = subprocess.run(command, cwd=str(workspace), env=env, stdout=out,
                                      stderr=err, timeout=900)
            code = finished.returncode
        except subprocess.TimeoutExpired:
            code = 124
    (evidence / 'drive-exit.txt').write_text(f'{code}\n')

    debug = (evidence / 'debug.log').read_text(errors='replace') if (evidence / 'debug.log').exists() else ''
    stream = (evidence / 'stream.jsonl').read_text(errors='replace')
    hook_errors = HOOK_ERROR.findall(debug)
    blocked = HOOK_BLOCK.findall(debug)
    for name in ('/home/valentin', str(Path.home())):
        stream = stream.replace(name, 'REDACTED')
    (evidence / 'stream.jsonl').write_text(stream)
    version = VERSION_LINE.search(stream)
    drove = (workspace / 'drove.txt').is_file()

    problems = []
    if code != 0:
        problems.append(f'chat exit {code}')
    if not drove:
        problems.append('drove.txt was not written, so the Bash command did not run')
    if hook_errors:
        problems.append(f'{len(hook_errors)} hook command(s) exited non-zero')
    if blocked:
        problems.append(f'{len(blocked)} hook block(s)')

    lines = [
        f'DRIVE {"FAIL" if problems else "PASS"} ' + ('; '.join(problems) or 'chat loaded, one Bash command ran, no hook errored'),
        f'drive-version: {version.group(0) if version else "no version line in the reply"}',
        f'drive-hook-errors: {len(hook_errors)}',
        f'drive-hook-blocks: {len(blocked)}',
    ]
    (evidence / 'drive.txt').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
