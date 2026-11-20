#!/usr/bin/env python3
"""Drive one headless Claude Code chat over stream-json input.

Sends each planned message at its offset and logs every output event with its
arrival time, so grade.py can measure reply latency. stdin stays open until the
chat has been idle with no background task running, or the timeout hits.

Usage: drive.py PLAN.json LOG.jsonl
PLAN: {"cwd", "claude", "args": [...], "messages": [{"at": s, "text": ...}],
       "idle_close": s, "timeout": s}
"""
import json
import subprocess
import sys
import threading
import time

plan = json.load(open(sys.argv[1]))
log = open(sys.argv[2], 'w')
lock = threading.Lock()
t0 = time.time()
state = {'last': t0, 'results': 0, 'open': set()}


def write(record):
    with lock:
        record['t'] = round(time.time() - t0, 2)
        log.write(json.dumps(record) + '\n')
        log.flush()


proc = subprocess.Popen(
    [plan['claude'], '-p', '--input-format', 'stream-json',
     '--output-format', 'stream-json', '--verbose', *plan['args']],
    cwd=plan['cwd'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    stderr=open(sys.argv[2] + '.stderr', 'w'), text=True)


def reader():
    for line in proc.stdout:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        state['last'] = time.time()
        kind, subtype = event.get('type'), event.get('subtype')
        if kind == 'result':
            state['results'] += 1
        if kind == 'system' and subtype == 'task_started':
            state['open'].add(event.get('task_id'))
        if kind == 'system' and subtype == 'task_notification':
            state['open'].discard(event.get('task_id'))
        write({'ev': event})


threading.Thread(target=reader, daemon=True).start()

for message in plan['messages']:
    while time.time() - t0 < message['at']:
        time.sleep(0.2)
    proc.stdin.write(json.dumps({'type': 'user', 'message': {
        'role': 'user', 'content': message['text']}}) + '\n')
    proc.stdin.flush()
    write({'sent': message['text']})

reason = 'timeout'
while time.time() - t0 < plan['timeout']:
    if proc.poll() is not None:
        reason = 'chat exited'
        break
    idle = time.time() - state['last']
    if state['results'] and not state['open'] and idle > plan['idle_close']:
        reason = 'idle with no background task'
        break
    time.sleep(1)
proc.stdin.close()
try:
    proc.wait(timeout=60)
except subprocess.TimeoutExpired:
    proc.kill()
write({'closed': reason, 'exit': proc.returncode, 'open_tasks': sorted(state['open'])})
