#!/usr/bin/env python3
"""Aggregate reply lengths without emitting transcript text or identifiers.

Default: the last 72 hours in ~/.claude/projects/*/*.jsonl, after a user
invokes /valentin-mode. Use --until to freeze a baseline for reruns.
Words are whitespace tokens containing a letter or digit. p90 is nearest-rank.
Only end_turn assistant text counts, not thinking, tools or pre-tool commentary.
Split API blocks are joined by message id; transcript UUIDs are deduplicated.

Categories overlap. Notification attribution follows the latest human/automated
input, ignoring tool results and skill expansions. It does NOT imply the reply
was unnecessary. Running tails and exact repeated status sentences are conservative
text heuristics, not semantic judgments. Changed numbers are not repetitions.
No counterfactual after-number: new rules need a day of live use.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import statistics

LOAD = re.compile(r'<command-name>/valentin-mode</command-name>')
AUTOMATED = re.compile(
    r'<task-notification\b|<teammate-message\b|<cross-session|'
    r'\[SYSTEM NOTIFICATION|\[Message from|\[Cross.session|(?:^|\n)\[from |'
    r'hasn[\u2019\']t heard from you|has not heard from you|'
    r'(?:^|\n)(?:Cross-session message|Message from (?:session|chat))', re.I)
RUNNING = re.compile(
    r'^(?:still running\b|running(?: jobs)?\s*:|in.flight\s*:|background jobs\s*:)|'
    r'\b(?:worker|watcher|job|CI|pacer)\b.*\b(?:running|watching|in flight)\b', re.I)
STATUS = re.compile(
    r'\b(?:running|waiting|blocked|watching|pending|CI|PR|ticket|worker|job|'
    r'merged|pushed|checks|done|finished|shipped)\b', re.I)


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(b.get('text', '') for b in content
                         if isinstance(b, dict) and b.get('type') == 'text')
    return ''


def words(text):
    return sum(any(c.isalnum() for c in token) for token in text.split())


def normalized(text):
    return ' '.join(re.sub(r'[*_`#>]', '', text).lower().split())


def status_parts(text):
    return [part.strip() for part in re.split(r'(?<=[.!?])\s+|\n', text) if part.strip()]


def category_counts(text, previous):
    # Only the final paragraph can be a mandatory running-jobs tail.
    tail = re.split(r'\n\s*\n', text.strip())[-1]
    running = words(tail) if RUNNING.search(normalized(tail)) else 0
    old = {normalized(part) for part in status_parts(previous)}
    repeated = sum(words(part) for part in status_parts(text)
                   if words(part) >= 4 and STATUS.search(part) and normalized(part) in old)
    return running, repeated


def input_kind(entry):
    """Tool results, skill expansions and generic meta reminders never reset attribution."""
    kind = entry.get('type')
    if kind == 'attachment':
        attachment = entry.get('attachment') or {}
        if attachment.get('type') != 'queued_command':
            return None
        text = text_of(attachment.get('prompt'))
    elif kind == 'user':
        text = text_of((entry.get('message') or {}).get('content'))
    else:
        return None
    if not text.strip():
        return None
    if AUTOMATED.search(text):
        return 'notification'
    if entry.get('isMeta') or text.lstrip().startswith(
            ('Base directory for this skill', '<system-reminder', '<local-command')):
        return None
    return 'human'


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def read_replies(path, since, until, seen, diagnostics):
    loaded, origin, previous = False, None, ''
    pending = None

    def finish():
        nonlocal previous
        if not pending:
            return None
        text = '\n'.join(pending['text'])
        result = None
        if pending['loaded'] and pending['stop'] == 'end_turn' and text.strip():
            when = pending['when']
            if when is not None and since <= when < until:
                a, c = category_counts(text, previous)
                result = (words(text), a, words(text) if pending['origin'] == 'notification' else 0, c)
                diagnostics['notification_replies' if pending['origin'] == 'notification'
                            else 'human_or_unattributed_replies'] += 1
            previous = text
        return result

    with path.open(errors='replace') as stream:
        for line in stream:
            try:
                entry = json.loads(line)
            except ValueError:
                diagnostics['malformed_lines'] += 1
                continue
            if not isinstance(entry, dict) or entry.get('isSidechain'):
                continue
            kind = entry.get('type')
            message = entry.get('message') or {}
            if not isinstance(message, dict):
                continue
            # A full assistant API response may occupy several JSONL rows.
            key = message.get('id') or entry.get('uuid')
            if pending and (kind != 'assistant' or key != pending['id']):
                reply = finish()
                if reply is not None:
                    yield reply
                pending = None
            uid = entry.get('uuid')
            if kind == 'assistant' and uid:
                if uid in seen:
                    diagnostics['duplicate_entries'] += 1
                    continue
                seen.add(uid)
            source = input_kind(entry)
            if source:
                origin = source
            if kind == 'user' and LOAD.search(text_of(message.get('content'))):
                loaded = True
            if kind == 'assistant':
                text = text_of(message.get('content'))
                if pending is None:
                    pending = {'id': key, 'text': [], 'stop': None, 'when': None,
                               'loaded': loaded, 'origin': origin}
                if text:
                    pending['text'].append(text)
                pending['stop'] = message.get('stop_reason') or pending['stop']
                pending['when'] = timestamp(entry.get('timestamp')) or pending['when']
                if loaded and text and message.get('stop_reason') == 'tool_use':
                    when = timestamp(entry.get('timestamp'))
                    if when and since <= when < until:
                        diagnostics['pre_tool_text_blocks'] += 1
                        diagnostics['pre_tool_text_words'] += words(text)
            # Count hook denials separately, never as user-facing assistant replies.
            if kind == 'user' and loaded:
                content = message.get('content')
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get('type') == 'tool_result':
                            when = timestamp(entry.get('timestamp'))
                            if (when and since <= when < until and
                                    "Valentin's newest message has no reply yet" in
                                    str(block.get('content', ''))):
                                diagnostics['reply_guard_denials'] += 1
    reply = finish()
    if reply is not None:
        yield reply
    if loaded:
        diagnostics['loaded_transcripts'] += 1


def summarize(replies):
    lengths = sorted(row[0] for row in replies)
    total = sum(lengths)
    return {
        'reply_count': len(lengths), 'words': total,
        'median_words': statistics.median(lengths) if lengths else 0,
        'p90_words': lengths[math.ceil(len(lengths) * .9) - 1] if lengths else 0,
        'categories': {name: {'words': sum(row[i] for row in replies),
                              'share_pct': round(100 * sum(row[i] for row in replies) / total, 2)
                              if total else 0}
                       for i, name in enumerate(('running_tail', 'notification_reply',
                                                 'exact_repeated_status'), 1)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.home() / '.claude/projects')
    parser.add_argument('--until', type=timestamp, default=datetime.now(timezone.utc))
    parser.add_argument('--since', type=timestamp)
    args = parser.parse_args()
    if args.until is None:
        parser.error('--until must be an ISO timestamp')
    since = args.since or args.until - timedelta(days=3)
    if since >= args.until:
        parser.error('--since must precede --until')
    diagnostics, seen, replies = Counter(), set(), []
    for path in sorted(args.root.glob('*/*.jsonl')):
        # Old files cannot have newly appended replies; parse timestamps inside recent files.
        if path.stat().st_mtime < since.timestamp():
            continue
        diagnostics['scanned_transcripts'] += 1
        replies.extend(read_replies(path, since, args.until, seen, diagnostics))
    print(json.dumps({'since': since.isoformat(), 'until': args.until.isoformat(),
                      **summarize(replies), 'diagnostics': dict(diagnostics)}, indent=2))


if __name__ == '__main__':
    main()
