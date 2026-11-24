#!/usr/bin/env python3
"""video_proof_gate: refuse PASS on a user-visible UI diff without a before/after video link.

  video_proof_gate --changed-files PATH [--body-file PATH | --event PATH] [--verdict PASS|PASS+NOTES|FAIL]
  video_proof_gate --base REF [--head REF] [--body-file PATH | --event PATH] [--verdict PASS|PASS+NOTES|FAIL]
  video_proof_gate --changed-files PATH --list
  video_proof_gate --self-test

Exit 0 when the verdict stands, 1 when it was demoted to FAIL, 2 on a usage or file error.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

PASSING = ('PASS', 'PASS+NOTES')
DEMOTED = 'FAIL'
NAMED = 10

NON_UI_TEST = re.compile(
    r'(?:^|/)(?:tests?|__tests__|specs?|fixtures|__fixtures__|__snapshots__)/'
    r'|(?:^|/)(?:test|spec)_[^/]+$'
    r'|\.(?:test|spec)\.[^/]+$',
    re.I,
)
NON_UI_DATA = re.compile(
    r'\.(?:md|mdx|txt|rst|json|ya?ml|toml|lock|ini|cfg|env|map)$',
    re.I,
)
UI_EXTENSIONS = re.compile(
    r'\.(?:tsx|jsx|vue|svelte|astro|css|scss|sass|less|html|htm|'
    r'ejs|hbs|handlebars|pug|njk|jinja|jinja2|j2|erb|twig|liquid|mustache|tmpl|'
    r'storyboard|xib|xaml)$',
    re.I,
)
UI_PATH = re.compile(
    r'(?:^|/)(?:templates|screens|res/layout)/'
    r'|(?:^|/)[^/]*Screen\.(?:ts|js|kt|java|swift|dart)$',
    re.I,
)
FENCE_OPEN = re.compile(r'^ {0,3}(`{3,}|~{3,})')
URL = re.compile(r'https?://[^\s<>()"\'`]+')
MD_IMAGE = re.compile(r'!\[[^\]]*\]\((https?://[^\s<>()"\'`]+)\)')
MD_LINK = re.compile(r'(?<!!)\[([^\]]*)\]\((https?://[^\s<>()"\'`]+)\)')
VIDEO_TAG = re.compile(
    r'<video\b[^>]*\bsrc=["\'](https?://[^"\']+)["\']'
    r'|<video\b[^>]*>.*?<source\b[^>]*\bsrc=["\'](https?://[^"\']+)["\']',
    re.I | re.S,
)
IMG_TAG = re.compile(r'<img\b[^>]*>', re.I)
VIDEO_EXT = re.compile(r'\.(?:mp4|webm|mov|m4v|mkv|ogv)$', re.I)
IMAGE_EXT = re.compile(r'\.(?:png|jpe?g|gif|webp|svg|bmp|ico|avif)$', re.I)
VIDEO_HOST = re.compile(
    r'^(?:www\.)?(?:loom\.com|youtu\.be|youtube\.com|vimeo\.com|streamable\.com|'
    r'videodelivery\.net|stream\.mux\.com|share\.zight\.com|share\.descript\.com)$'
    r'|(?:^|\.)(?:cleanshot\.cloud|cloudflarestream\.com)$',
    re.I,
)
GITHUB_ASSET = re.compile(r'^https?://github\.com/user-attachments/assets/[A-Za-z0-9-]+/?$', re.I)
NON_VIDEO_PAGE = re.compile(
    r'^https?://(?:app\.hypertask\.ai/'
    r'|github\.com/[^/]+/[^/]+/(?:pull|issues|actions|commit|compare|blob|tree)/)',
    re.I,
)
VIDEO_LABEL = re.compile(r'\b(?:video|recording|screencast|demo\s+clip)\b', re.I)


def is_ui_file(path):
    cleaned = str(path or '').strip().replace('\\', '/').lstrip('./')
    if not cleaned or NON_UI_TEST.search(cleaned):
        return False
    if UI_EXTENSIONS.search(cleaned):
        return True
    if NON_UI_DATA.search(cleaned):
        return False
    return bool(UI_PATH.search(cleaned))


def ui_files(paths):
    unique = {str(path).strip().replace('\\', '/').lstrip('./')
              for path in (paths or ()) if str(path or '').strip()}
    return sorted(path for path in unique if is_ui_file(path))


def strip_fenced_code(body):
    kept = []
    fence = None
    for line in (body or '').replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        if fence:
            closing = line.strip()
            if closing and set(closing) == {fence[0]} and len(closing) >= len(fence):
                fence = None
            continue
        opening = FENCE_OPEN.match(line)
        if opening:
            fence = opening.group(1)
            continue
        kept.append(line)
    return '\n'.join(kept)


def _clean_url(raw):
    return (raw or '').rstrip('.,;:!?')


def _is_image_url(url):
    return bool(IMAGE_EXT.search(urlsplit(url).path))


def _is_direct_video_url(url):
    if _is_image_url(url):
        return False
    parts = urlsplit(url)
    if VIDEO_EXT.search(parts.path):
        return True
    host = (parts.hostname or '').lower()
    if VIDEO_HOST.search(host) and parts.path not in ('', '/'):
        return True
    return bool(GITHUB_ASSET.match(url))


def video_links(body):
    text = strip_fenced_code(body)
    found = []
    seen = set()

    def record(raw):
        url = _clean_url(raw)
        if url and url not in seen and not _is_image_url(url):
            seen.add(url)
            found.append(url)

    for match in VIDEO_TAG.finditer(text):
        record(match.group(1) or match.group(2))

    for line in text.splitlines():
        cleaned = IMG_TAG.sub('', MD_IMAGE.sub('', line))
        for label, raw in MD_LINK.findall(cleaned):
            url = _clean_url(raw)
            if _is_direct_video_url(url):
                record(url)
            elif VIDEO_LABEL.search(label) and not NON_VIDEO_PAGE.match(url):
                record(url)
        line_has_label = bool(VIDEO_LABEL.search(cleaned))
        for raw in URL.findall(cleaned):
            url = _clean_url(raw)
            if _is_direct_video_url(url):
                record(url)
            elif line_has_label and not NON_VIDEO_PAGE.match(url):
                record(url)
    return found


def has_video_link(body):
    return bool(video_links(body))


def reason(paths):
    named = ', '.join(paths[:NAMED])
    if len(paths) > NAMED:
        named += f' and {len(paths) - NAMED} more'
    return (
        f'{DEMOTED}: UI diff touches {named} without a before/after video link in the PR body. '
        f'Link a short before and after video from /verify-<app> in the PR body, then re-run.'
    )


def gate(changed_paths, body, verdict='PASS'):
    if verdict not in PASSING:
        return verdict, ''
    touched = ui_files(changed_paths)
    if not touched:
        return verdict, ''
    if has_video_link(body):
        return verdict, ''
    return DEMOTED, reason(touched)


def read_changed_files(path=None, base=None, head='HEAD', cwd=None):
    if path:
        try:
            return Path(path).read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError as problem:
            raise SystemExit(f'video_proof_gate: cannot read changed files {path}: {problem}')
    if base:
        result = subprocess.run(
            ['git', 'diff', '--name-only', f'{base}...{head}'],
            capture_output=True,
            text=True,
            cwd=cwd,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or 'git diff failed').strip()
            raise SystemExit(f'video_proof_gate: {detail}')
        return result.stdout.splitlines()
    raise SystemExit('video_proof_gate: pass --changed-files PATH or --base REF')


def read_body(body_file=None, event_path=None, allow_missing=False):
    if body_file:
        try:
            return Path(body_file).read_text(encoding='utf-8', errors='replace')
        except OSError as problem:
            raise SystemExit(f'video_proof_gate: cannot read PR body {body_file}: {problem}')
    if event_path:
        try:
            event = json.loads(Path(event_path).read_text(encoding='utf-8', errors='replace'))
        except (OSError, ValueError) as problem:
            if allow_missing:
                return ''
            raise SystemExit(f'video_proof_gate: cannot read event {event_path}: {problem}')
        return (event.get('pull_request') or {}).get('body') or ''
    if allow_missing:
        return ''
    raise SystemExit('video_proof_gate: pass --body-file PATH or --event PATH (or set GITHUB_EVENT_PATH)')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--changed-files', metavar='PATH',
                        help='newline-separated changed file paths')
    parser.add_argument('--base', metavar='REF',
                        help='git base ref to diff against --head')
    parser.add_argument('--head', default='HEAD', metavar='REF',
                        help='git head ref when using --base (default: HEAD)')
    parser.add_argument('--body-file', metavar='PATH',
                        help='file holding the pull request body')
    parser.add_argument('--event', default=os.environ.get('GITHUB_EVENT_PATH'), metavar='PATH',
                        help='GitHub event JSON holding pull_request.body (default: $GITHUB_EVENT_PATH)')
    parser.add_argument('--verdict', default='PASS', metavar='TOKEN',
                        help='verdict to check: PASS, PASS+NOTES or FAIL (default: PASS)')
    parser.add_argument('--list', action='store_true',
                        help='print matched UI files, one per line')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args(argv)
    if args.self_test:
        return subprocess.call([sys.executable, '-m', 'unittest', 'tests.test_video_proof_gate'],
                               cwd=Path(__file__).resolve().parents[1])
    if not args.changed_files and not args.base:
        parser.error('pass --changed-files PATH or --base REF')
    changed = read_changed_files(args.changed_files, args.base, args.head)
    if args.list:
        for path in ui_files(changed):
            print(path)
        return 0
    body = read_body(args.body_file, args.event)
    standing, why = gate(changed, body, args.verdict)
    print(standing, flush=True)
    if why:
        print(why, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
