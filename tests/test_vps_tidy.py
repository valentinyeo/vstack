#!/usr/bin/env python3
"""Tests for skills/vps-tidy/vps-tidy and its verify skill.

Every run is fed a sandbox under VPS_TIDY_ROOT, a fake process table through
--ps-file, and a fake PATH for npm, pnpm, uv and docker. Nothing here touches
this host's /tmp, its caches, its docker or its processes.

The frozen contract these tests hold the tool to:

    vps-tidy [--apply] [--json] [--only PART[,PART...]] [--budget SECONDS]
             [--ps-file FILE] [--proc-root DIR] [--root DIR] [--grace SECONDS]
             [--statvfs-json FILE]

    parts: tmp, caches, docker, evidence, tmux, processes   (files = tmp,caches,docker,evidence)
    exit:  0 ran, 2 usage error, 3 could not run (lock held)
    env:   VPS_TIDY_ROOT, VPS_TIDY_PROC, VPS_TIDY_BOARD_CMD
    log:   <home>/.local/state/vps-tidy/<UTC>.jsonl, kills.log, status.json
"""

import fcntl
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills' / 'vps-tidy' / 'vps-tidy'
VERIFY_RUN = ROOT / '.claude' / 'skills' / 'verify-vps-tidy' / 'run'
UID = os.getuid()
DAY = 86400
MB = 1024 * 1024


def load_script():
    loader = importlib.machinery.SourceFileLoader('vps_tidy', str(SCRIPT))
    spec = importlib.util.spec_from_loader('vps_tidy', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def age(path, seconds, follow=True):
    """Backdate a path so the age rules have something to measure."""
    when = time.time() - seconds
    os.utime(str(path), (when, when), follow_symlinks=follow)


class Sandbox:
    """A throwaway root: tmp, home with caches and state, a proc root and a PATH."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='vps-tidy-')
        self.root = pathlib.Path(self._tmp.name)
        self.tmp = self.root / 'tmp'
        self.home = self.root / 'home'
        self.state = self.home / '.local' / 'state'
        self.proc = self.root / 'proc'
        self.bin = self.root / 'bin'
        self.ps_file = self.root / 'ps.txt'
        self.docker_log = self.root / 'docker.log'
        for path in (self.tmp, self.home, self.state, self.proc, self.bin):
            path.mkdir(parents=True, exist_ok=True)
        self.slept = []
        self.rows = []
        self._write_tool('npm', 'npm')
        self._write_tool('pnpm', 'pnpm')
        self._write_tool('uv', 'uv')
        self._write_tool('docker', 'docker')
        self.ps_file.write_text(self.ps_text())
        self.board_cmd = None
        self.tmux_servers = []
        self.tmux_dir = self.tmp / 'tmux-{}'.format(UID)

    # -- layout helpers ---------------------------------------------------
    def make(self, relative, body='x', seconds_old=None, base=None):
        path = (base or self.root) / relative.lstrip('/')
        if body is None:
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        if seconds_old is not None:
            age(path, seconds_old)
        return path

    def make_tree(self, relative, seconds_old, files=('deep/file',)):
        """A tree whose every entry but the top directory is `seconds_old` old."""
        top = self.root / relative.lstrip('/')
        for name in files:
            path = top / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('x')
        for dirpath, dirnames, filenames in os.walk(top):
            for name in filenames:
                age(os.path.join(dirpath, name), seconds_old)
            for name in dirnames:
                child = os.path.join(dirpath, name)
                if child != str(top):
                    age(child, seconds_old)
        return top

    def _write_tool(self, name, tool):
        body = ["#!/bin/sh",
                "printf '%s %s\\n' '" + tool + "' \"$*\" >> '" + str(self.docker_log) + "'",
                'case "$1 $2" in',
                '  "system df") echo \'{"Type":"Images","Size":"7.5GB","Reclaimable":"4.7GB"}\' ;;',
                '  "image ls") echo "sha256:aaaa 1.2GB" ;;',
                '  "volume ls") echo "ht-smoke-build-1"; echo "ht-smoke-state-2" ;;',
                '  "ps -a") echo "" ;;',
                '  *) : ;;',
                'esac',
                'exit 0']
        script = self.bin / name
        script.write_text("\n".join(body) + "\n")
        script.chmod(0o755)

    def tool_calls(self):
        if not self.docker_log.exists():
            return []
        return [line.strip() for line in self.docker_log.read_text().splitlines() if line.strip()]

    # -- process fixtures -------------------------------------------------
    def spawn(self, argv=None, cwd=None, home=None, ignore_term=False):
        code = 'import signal,time\n'
        if ignore_term:
            code += 'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
        code += 'time.sleep(300)\n'
        argv = argv or [sys.executable, '-c', code]
        proc = subprocess.Popen(argv, cwd=str(cwd) if cwd else None, start_new_session=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.slept.append(proc)
        return proc

    def add_process(self, pid, ppid, args, etimes=60, uid=None, cwd=None, home=None,
                    stat='S', rss=1024, cpu=0.0):
        self.rows.append({'pid': pid, 'ppid': ppid, 'uid': UID if uid is None else uid,
                          'rss': rss, 'cpu': cpu, 'etimes': etimes, 'stat': stat,
                          'args': args})
        case = self.proc / str(pid)
        case.mkdir(parents=True, exist_ok=True)
        for link in ('cwd', 'root'):
            target = case / link
            if target.exists() or target.is_symlink():
                target.unlink()
        os.symlink(str(cwd or self.root), case / 'cwd')
        os.symlink('/', case / 'root')
        env = 'HOME={}\0'.format(home or self.home)
        (case / 'environ').write_bytes(env.encode())
        # pid 1 is always present so a ppid chain can end somewhere real.
        init = self.proc / '1'
        init.mkdir(parents=True, exist_ok=True)
        if not (init / 'cwd').exists():
            os.symlink('/', init / 'cwd')
            os.symlink('/', init / 'root')
        self.ps_file.write_text(self.ps_text())

    def ps_text(self):
        lines = ['  PID  PPID   UID   RSS %CPU ELAPSED STAT COMMAND',
                 '    1     0     0  1024  0.0       1 Ss   /sbin/init']
        for row in self.rows:
            lines.append('{:>5} {:>5} {:>5} {:>5} {:>4} {:>7} {:<4} {}'.format(
                row['pid'], row['ppid'], row['uid'], row['rss'], row['cpu'],
                row['etimes'], row['stat'], row['args']))
        return '\n'.join(lines) + '\n'

    # -- run --------------------------------------------------------------
    def board_script(self, body):
        """One script that answers the board read the way a test needs."""
        path = self.root / 'board.sh'
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)
        return path

    def env(self, board_cmd=None, tmux_ages=None):
        env = dict(os.environ)
        env['HOME'] = str(self.home)
        env['VPS_TIDY_ROOT'] = str(self.root)
        env['VPS_TIDY_PROC'] = str(self.proc)
        env['PATH'] = str(self.bin) + os.pathsep + env.get('PATH', '')
        if board_cmd is not None:
            env['VPS_TIDY_BOARD_CMD'] = str(self.board_script(board_cmd))
        for key, value in (tmux_ages or {}).items():
            env[key] = str(value)
        return env

    def tmux_socket(self, name):
        self.tmux_dir.mkdir(parents=True, exist_ok=True)
        return str(self.tmux_dir / name)

    def start_tmux(self, sock, session='s1', command='sleep 600'):
        if shutil.which('tmux') is None:
            raise unittest.SkipTest('tmux is not installed')
        cmd = ['tmux', '-S', sock, 'new', '-d', '-s', session]
        if command is not None:
            cmd.append(command)
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.tmux_servers.append(sock)

    def seed_cmdline(self, pid, argv):
        proc_dir = self.proc / str(pid)
        proc_dir.mkdir(parents=True, exist_ok=True)
        (proc_dir / 'cmdline').write_bytes(
            '\0'.join(argv).encode() + (b'\0' if argv else b''))

    def pane_pid(self, sock, session):
        out = subprocess.run(
            ['tmux', '-S', sock, 'list-panes', '-t', session, '-F', '#{pane_pid}'],
            capture_output=True, text=True, check=True)
        return int(out.stdout.strip().splitlines()[0])

    def dead_tmux_socket(self, name, seconds_old=7200):
        import socket as socket_mod
        self.tmux_dir.mkdir(parents=True, exist_ok=True)
        path = self.tmux_dir / name
        handle = socket_mod.socket(socket_mod.AF_UNIX)
        try:
            if path.exists():
                path.unlink()
            handle.bind(str(path))
        finally:
            handle.close()
        age(path, seconds_old)
        return str(path)

    def run(self, *args, timeout=120, statvfs=None, env=None, tmux_ages=None):
        cmd = [sys.executable, str(SCRIPT), '--root', str(self.root),
               '--proc-root', str(self.proc), '--ps-file', str(self.ps_file)]
        cmd += list(args)
        if statvfs is not None:
            path = self.root / 'statvfs.json'
            path.write_text(json.dumps(statvfs))
            cmd += ['--statvfs-json', str(path)]
        return subprocess.run(cmd, env=env or self.env(tmux_ages=tmux_ages),
                              capture_output=True, text=True, timeout=timeout)

    def payload(self, *args, tmux_ages=None, **kwargs):
        done = self.run('--json', *args, tmux_ages=tmux_ages, **kwargs)
        assert done.returncode == 0, done.stdout + done.stderr
        return json.loads(done.stdout)

    def run_logs(self):
        directory = self.state / 'vps-tidy'
        if not directory.is_dir():
            return []
        return sorted(directory.glob('*.jsonl'))

    def log_records(self):
        records = []
        for path in self.run_logs():
            records.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
        return records

    def cleanup(self):
        for proc in self.slept:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass
        for sock in self.tmux_servers:
            try:
                subprocess.run(['tmux', '-S', sock, 'kill-server'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=10)
            except (OSError, subprocess.SubprocessError):
                pass
        self._tmp.cleanup()


def by_path(items):
    return {item.get('path'): item for item in items if item.get('path')}


class Base(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)

    def items_for(self, payload, part=None):
        return [item for item in payload['items'] if part is None or item['part'] == part]

    def assertRemoved(self, payload, path):
        item = by_path(self.items_for(payload)).get(str(path))
        self.assertIsNotNone(item, 'no item for {}'.format(path))
        self.assertEqual(item['action'], 'remove', item)
        self.assertEqual(item.get('result'), 'removed', item)

    def assertKept(self, payload, path, reason=None):
        item = by_path(self.items_for(payload)).get(str(path))
        self.assertIsNotNone(item, 'no item for {}'.format(path))
        self.assertEqual(item['action'], 'keep', item)
        if reason:
            self.assertIn(reason, item['reason'])


class TmpRules(Base):
    def test_stale_tmp_is_removed_and_fresh_tmp_survives(self):
        stale = self.box.make('tmp/stale/file', seconds_old=5 * DAY)
        fresh = self.box.make('tmp/fresh/file')
        payload = self.box.payload('--only', 'tmp', '--apply')
        self.assertRemoved(payload, stale.parent)
        self.assertFalse(stale.parent.exists())
        self.assertTrue(fresh.parent.exists())

    def test_newest_mtime_inside_the_tree_decides(self):
        # The top directory looks fresh, everything inside is old: the tree is stale.
        inner_old = self.box.make('tmp/oldinner/deep/file', seconds_old=5 * DAY)
        age(inner_old.parent, 5 * DAY)
        age(inner_old.parent.parent, 0)
        # The top directory looks old, a file inside is fresh: the tree is alive.
        inner_fresh = self.box.make('tmp/live/deep/file', seconds_old=5 * DAY)
        age(inner_fresh.parent, 5 * DAY)
        age(inner_fresh, 0)
        payload = self.box.payload('--only', 'tmp', '--apply')
        self.assertRemoved(payload, inner_old.parent.parent)
        self.assertKept(payload, inner_fresh.parent.parent)

    def test_tmp_exclusions_keep_claude_tmux_x11_and_systemd(self):
        kept = [self.box.make('tmp/claude-{}/x/file'.format(UID), seconds_old=9 * DAY).parent.parent,
                self.box.make('tmp/tmux-0/file', seconds_old=9 * DAY).parent,
                self.box.make('tmp/.X11-unix/X0', seconds_old=9 * DAY).parent,
                self.box.make('tmp/systemd-private-abc/file', seconds_old=9 * DAY).parent]
        payload = self.box.payload('--only', 'tmp', '--apply')
        for parent in kept:
            self.assertKept(payload, parent, 'excluded')
            self.assertTrue(parent.exists())

    def test_global_rules_are_pure_and_checked(self):
        module = load_script()

        class Stat:
            def __init__(self, uid=UID, dev=7):
                self.st_uid = uid
                self.st_dev = dev

        self.assertTrue(module.owned_by_us(Stat(), UID))
        self.assertFalse(module.owned_by_us(Stat(uid=UID + 1), UID))
        self.assertTrue(module.same_filesystem(Stat(), 7))
        self.assertFalse(module.same_filesystem(Stat(dev=8), 7))
        for path in ('/home/x/.local/state/gh-shared-cache/a',
                     '/home/x/.local/state/gh-shared-cache-app/a',
                     '/home/x/.config/x', '/home/x/repo/.git/objects',
                     '/home/x/.ssh/id_ed25519', '/home/x/.claude/settings.json',
                     '/home/x/.codex/x', '/home/x/projects/worktrees/wt-a/x'):
            self.assertTrue(module.never_touch(path), path)
        self.assertFalse(module.never_touch('/tmp/ordinary'))

    def test_symlink_is_never_followed(self):
        target = self.box.make('home/.local/state/gh-shared-cache/repo/big', seconds_old=9 * DAY)
        link = self.box.tmp / 'escape'
        os.symlink(str(self.box.state / 'gh-shared-cache'), link)
        age(link, 9 * DAY, follow=False)
        payload = self.box.payload('--only', 'tmp', '--apply')
        self.assertTrue(link.exists())
        self.assertTrue(target.exists())
        self.assertKept(payload, link)

    def test_claude_scratch_needs_a_uuid_and_the_24h_rule(self):
        session = self.box.make('tmp/claude-{}/proj/{}/file'.format(UID, uuid.uuid4()),
                                seconds_old=2 * DAY)
        other_uuid = self.box.make('tmp/claude-{}/proj/{}/file'.format(UID, uuid.uuid4()))
        not_uuid = self.box.make('tmp/claude-{}/proj/not-a-uuid/file'.format(UID),
                                 seconds_old=2 * DAY)
        hypertask = self.box.make(
            'tmp/claude-{}/my-hypertask/{}/file'.format(UID, uuid.uuid4()), seconds_old=2 * DAY)
        marketing = self.box.make(
            'tmp/claude-{}/acme-ht-marketing/{}/file'.format(UID, uuid.uuid4()), seconds_old=2 * DAY)
        payload = self.box.payload('--only', 'tmp', '--apply')
        self.assertRemoved(payload, session.parent)
        self.assertFalse(session.parent.exists())
        self.assertTrue(other_uuid.exists())
        self.assertTrue(not_uuid.parent.exists())
        self.assertTrue(hypertask.parent.exists())
        self.assertTrue(marketing.parent.exists())

    def test_scratch_prefixes_and_agent_template_stage(self):
        stale = [self.box.make('tmp/igsh123/file', seconds_old=2 * DAY),
                 self.box.make('tmp/wazi1/file', seconds_old=2 * DAY),
                 self.box.make('tmp/mpa-9/file', seconds_old=2 * DAY),
                 self.box.make('tmp/tmp.abc/file', seconds_old=2 * DAY),
                 self.box.make('tmp/agent-template-stage.zz/file', seconds_old=2 * DAY)]
        fresh = [self.box.make('tmp/igsh999/file'), self.box.make('tmp/agent-template-stage.ok/file'),
                 self.box.make('tmp/tmp.fresh/file')]
        payload = self.box.payload('--only', 'tmp', '--apply')
        for path in stale:
            self.assertRemoved(payload, path.parent)
        for path in fresh:
            self.assertKept(payload, path.parent)

    def test_dry_run_deletes_nothing(self):
        stale = self.box.make('tmp/stale/file', seconds_old=5 * DAY)
        payload = self.box.payload('--only', 'tmp')
        self.assertIn(str(stale.parent), [item['path'] for item in payload['items']])
        item = by_path(payload['items'])[str(stale.parent)]
        self.assertEqual(item['action'], 'remove')
        self.assertEqual(item.get('result'), 'would-remove')
        self.assertTrue(stale.exists())
        self.assertEqual(payload['mode'], 'dry-run')
        self.assertGreater(payload['summary']['would_free_bytes'], 0)

    def test_time_budget_stops_the_scan(self):
        self.box.make('tmp/stale/file', seconds_old=5 * DAY)
        payload = self.box.payload('--only', 'tmp', '--apply', '--budget', '0')
        self.assertTrue(payload['summary']['time_budget_reached'])
        self.assertEqual(payload['summary']['removed'], 0)
        self.assertTrue((self.box.tmp / 'stale').exists())

    def test_dev_protected_names_inside_tmp_are_kept(self):
        for nested in ('.git/config', '.ssh/id', '.config/x', '.claude/settings.json', '.codex/x'):
            keepme = self.box.tmp / 'keepme'
            self.box.make('tmp/keepme/' + nested, seconds_old=9 * DAY)
            age(keepme / nested.split('/')[0], 9 * DAY)
            age(keepme, 9 * DAY)
            payload = self.box.payload('--only', 'tmp', '--apply')
            self.assertKept(payload, keepme, 'protected')
            self.assertTrue((keepme / nested).exists())
            shutil.rmtree(keepme)


class EvidenceAndCaches(Base):
    def test_vcc_evidence_children_go_at_thirty_days(self):
        old = self.box.make_tree('home/.local/state/vcc-evidence/VSTA-OLD', 40 * DAY,
                                files=('run-old/out.txt',))
        fresh = self.box.make('home/.local/state/vcc-evidence/VSTA-2/run-new/out.txt')
        payload = self.box.payload('--only', 'evidence', '--apply')
        self.assertRemoved(payload, old)
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())

    def test_evidence_builds_go_at_two_days(self):
        base = 'home/.local/state/vcc-evidence/VSTA-1'
        run = self.box.make(base + '/run-build/state.json')
        build = self.box.make_tree(base + '/run-build/app/.next', 3 * DAY,
                                  files=('build/index.js',))
        modules = self.box.make_tree(base + '/run-build/app/node_modules', 3 * DAY,
                                     files=('x/y/index.js',))
        fresh_build = self.box.make_tree(base + '/run-fresh/app/.next', 0,
                                         files=('live/index.js',))
        payload = self.box.payload('--only', 'evidence', '--apply')
        self.assertRemoved(payload, build)
        self.assertRemoved(payload, modules)
        self.assertTrue(fresh_build.exists())
        self.assertTrue(run.exists())
        self.assertTrue((build.parent).exists(), 'the app folder itself stays')

    def test_evidence_videos_need_a_successful_board_read(self):
        video = self.box.make('home/.local/state/vcc-evidence/VSTA-7/run-1/demo.mp4',
                              seconds_old=20 * DAY)
        board_fails = self.box.env("exit 1")
        payload = self.box.payload('--only', 'evidence', '--apply', env=board_fails)
        self.assertKept(payload, video)
        self.assertTrue(video.exists())

        board_ok = self.box.env('echo closed')
        payload = self.box.payload('--only', 'evidence', '--apply', env=board_ok)
        self.assertRemoved(payload, video)
        self.assertFalse(video.exists())

        board_open = self.box.env('echo open')
        video2 = self.box.make('home/.local/state/vcc-evidence/VSTA-7/run-2/demo.mp4',
                               seconds_old=20 * DAY)
        payload = self.box.payload('--only', 'evidence', '--apply', env=board_open)
        self.assertKept(payload, video2)
        self.assertTrue(video2.exists())

    def test_state_tmp_dirs_need_a_known_parent(self):
        known = self.box.make_tree('home/.local/state/hax/tmp', 3 * DAY)
        unknown = self.box.make_tree('home/.local/state/mystery/tmp', 3 * DAY)
        payload = self.box.payload('--only', 'evidence', '--apply')
        self.assertRemoved(payload, known)
        self.assertTrue(unknown.exists())

    def test_npx_cache_ages_at_seven_days(self):
        old = self.box.make_tree('home/.npm/_npx/abc', 8 * DAY, files=('node_modules/x/index.js',))
        fresh = self.box.make_tree('home/.npm/_npx/def', 0, files=('node_modules/x/index.js',))
        payload = self.box.payload('--only', 'caches', '--apply')
        self.assertRemoved(payload, old)
        self.assertTrue(fresh.exists())

    def test_tool_caches_age_at_two_days_and_playwright_keeps_current(self):
        old_cache = self.box.make_tree('home/.cache/go-build', 3 * DAY, files=('aa/bb',))
        fresh_cache = self.box.make_tree('home/.cache/zig', 0, files=('aa/bb',))
        oldest = self.box.make_tree('home/.cache/ms-playwright/chromium-1000', 9 * DAY,
                                    files=('chrome',))
        newest = self.box.make_tree('home/.cache/ms-playwright/chromium-1200', 9 * DAY,
                                    files=('chrome',))
        payload = self.box.payload('--only', 'caches', '--apply')
        self.assertRemoved(payload, old_cache)
        self.assertTrue(fresh_cache.exists())
        self.assertRemoved(payload, oldest)
        self.assertKept(payload, newest, 'current')

    def test_playwright_version_referenced_by_a_link_is_kept(self):
        install = self.box.make('home/node_modules/playwright-core/package.json',
                                '{"version":"1"}')
        browsers = install.parent / 'browsers.json'
        browsers.write_text(json.dumps({'browsers': [{'name': 'firefox', 'revision': '1400'}]}))
        # The real .links mechanism: a link file points at the install that needs the build.
        ms = self.box.home / '.cache' / 'ms-playwright'
        referenced = self.box.make_tree('home/.cache/ms-playwright/firefox-1400', 9 * DAY,
                                        files=('firefox',))
        stale = self.box.make_tree('home/.cache/ms-playwright/firefox-1300', 9 * DAY,
                                   files=('firefox',))
        linkdir = ms / '.links'
        linkdir.mkdir(parents=True, exist_ok=True)
        (linkdir / 'abc').write_text(str(install.parent))
        payload = self.box.payload('--only', 'caches', '--apply')
        self.assertKept(payload, referenced)
        self.assertRemoved(payload, stale)

    def test_repo_target_needs_a_cachedir_tag(self):
        tagged = self.box.make_tree('home/projects/repo/target', 3 * DAY, files=('debug/x',))
        (tagged / 'CACHEDIR.TAG').write_text('Signature: 8a477f597d28d172789f06886806bc55\n')
        age(tagged / 'CACHEDIR.TAG', 3 * DAY)
        untagged = self.box.make_tree('home/projects/other/target', 3 * DAY, files=('debug/x',))
        zig = self.box.make_tree('home/projects/repo/.zig-cache', 3 * DAY, files=('o/x',))
        nextcache = self.box.make_tree('home/projects/repo/.next/cache', 3 * DAY, files=('aa',))
        payload = self.box.payload('--only', 'caches', '--apply')
        self.assertRemoved(payload, tagged)
        self.assertTrue(untagged.exists())
        self.assertRemoved(payload, zig)
        self.assertRemoved(payload, nextcache)

    def test_ceo_runs_keeps_small_proof_files(self):
        big = self.box.make('home/projects/ceo/runs/big.txt', 'x' * (6 * MB), seconds_old=3 * DAY)
        small = self.box.make('home/projects/ceo/runs/small.json', '{}', seconds_old=3 * DAY)
        payload = self.box.payload('--only', 'caches', '--apply')
        self.assertRemoved(payload, big)
        self.assertTrue(small.exists())

    def test_gh_shared_cache_and_worktrees_are_never_touched(self):
        cache = self.box.make('home/.local/state/gh-shared-cache/repos/a/pack', seconds_old=40 * DAY)
        app_cache = self.box.make('home/.local/state/gh-shared-cache-app/repos/a/pack',
                                  seconds_old=40 * DAY)
        worktree = self.box.make('home/projects/worktrees/wt-a/node_modules/x/index.js',
                                 seconds_old=40 * DAY)
        worktree_git = self.box.make('home/projects/worktrees/wt-a/.git/config', seconds_old=40 * DAY)
        payload = self.box.payload('--apply')
        for path in (cache, app_cache, worktree, worktree_git):
            self.assertTrue(path.exists(), 'touched {}'.format(path))
        for item in payload['items']:
            if item.get('path'):
                self.assertNotIn('gh-shared-cache', item['path'])
                self.assertNotIn('projects/worktrees/wt-', item['path'])

    def test_tool_caches_clean_only_when_the_tool_is_idle(self):
        self.box.make('home/.cache/go-build/aa', seconds_old=3 * DAY)
        busy = self.box.spawn()
        self.box.add_process(busy.pid, 1, 'npm exec some-tool', etimes=30)
        payload = self.box.payload('--only', 'caches', '--apply')
        self.assertIn('keep', [item['action'] for item in payload['items']
                               if item['rule'] == 'npm-clean'])
        busy.kill()
        busy.wait(timeout=10)

    def test_npm_uv_and_pnpm_are_run_when_idle(self):
        payload = self.box.payload('--only', 'caches', '--apply')
        calls = self.box.tool_calls()
        self.assertTrue(any(call.startswith('npm cache clean') for call in calls), calls)
        self.assertTrue(any(call.startswith('uv cache clean') for call in calls), calls)
        self.assertTrue(any(call.startswith('pnpm store prune') for call in calls), calls)
        self.assertEqual(payload['summary']['failed'], 0)

    def test_docker_prunes_dangling_only_above_eighty_percent(self):
        low = {'total': 100 * 1024 ** 3, 'free': 40 * 1024 ** 3}
        payload = self.box.payload('--only', 'docker', '--apply', statvfs=low)
        calls = [call for call in self.box.tool_calls() if call.startswith('docker image prune')]
        self.assertEqual(calls, [])
        self.assertTrue(any(item['rule'] == 'docker-images-80' for item in payload['items']))

        self.box.docker_log.unlink()
        high = {'total': 100 * 1024 ** 3, 'free': 10 * 1024 ** 3}
        self.box.payload('--only', 'docker', '--apply', statvfs=high)
        calls = self.box.tool_calls()
        self.assertTrue(any(call.startswith('docker image prune -f') for call in calls), calls)
        self.assertTrue(any(call.startswith('docker builder prune') for call in calls), calls)
        self.assertIn('until=72h', ' '.join(calls))
        self.assertFalse(any(call.startswith('docker volume prune') for call in calls))

    def test_docker_volumes_only_leaked_smoke_volumes(self):
        payload = self.box.payload('--only', 'docker', '--apply')
        removes = [call for call in self.box.tool_calls() if call.startswith('docker volume rm')]
        self.assertEqual(removes, ['docker volume rm ht-smoke-build-1', 'docker volume rm ht-smoke-state-2'],
                         payload['items'])
        self.assertFalse(any('docker volume prune' in call for call in self.box.tool_calls()))


class ProcessRules(Base):
    def worktree(self, name='wt-bombadil'):
        return self.box.make('home/projects/worktrees/{}/app/package.json'.format(name),
                             '{}').parent

    def test_orphan_dev_server_is_stopped_with_term_then_kill_after_grace(self):
        worktree = self.worktree()
        proc = self.box.spawn(cwd=worktree)
        self.box.add_process(proc.pid, 1, 'node /x/node_modules/.bin/next dev',
                             etimes=3 * 3600, cwd=worktree)
        payload = self.box.payload('--only', 'processes', '--apply', '--grace', '1')
        item = payload['items'][0]
        self.assertEqual(item['action'], 'kill', item)
        self.assertEqual(item['kind'], 'dev-server')
        self.assertEqual(item['result'], 'killed')
        proc.wait(timeout=15)
        self.assertIsNotNone(proc.returncode)

    def test_dev_server_with_a_live_claude_in_the_same_worktree_survives(self):
        worktree = self.worktree()
        dev = self.box.spawn(cwd=worktree)
        chat = self.box.spawn(cwd=worktree)
        self.box.add_process(dev.pid, 1, 'next dev', etimes=3 * 3600, cwd=worktree)
        self.box.add_process(chat.pid, 1, 'claude -p hello', etimes=60, cwd=worktree)
        payload = self.box.payload('--only', 'processes', '--apply')
        dev_item = [item for item in payload['items'] if item.get('pid') == dev.pid][0]
        self.assertEqual(dev_item['action'], 'keep')
        self.assertIn('claude', dev_item['reason'])
        self.assertIsNone(dev.poll())

    def test_dev_server_outside_a_worktree_or_under_two_hours_survives(self):
        plain = self.box.make('home/projects/plain/app/package.json', '{}').parent
        young = self.worktree('wt-young')
        a = self.box.spawn(cwd=plain)
        b = self.box.spawn(cwd=young)
        self.box.add_process(a.pid, 1, 'next dev', etimes=3 * 3600, cwd=plain)
        self.box.add_process(b.pid, 1, 'next dev', etimes=600, cwd=young)
        payload = self.box.payload('--only', 'processes', '--apply')
        for pid in (a.pid, b.pid):
            item = [row for row in payload['items'] if row.get('pid') == pid][0]
            self.assertEqual(item['action'], 'keep', item)
        self.assertIsNone(a.poll())
        self.assertIsNone(b.poll())

    def test_never_kill_list_survives_every_rule(self):
        worktree = self.worktree()
        protected = {}
        for name in ('claude', 'tmux', 'codex', 'pi'):
            proc = self.box.spawn(cwd=worktree)
            protected[name] = proc
            self.box.add_process(proc.pid, 1, '{} something'.format(name),
                                 etimes=99 * 3600, cwd=self.box.state / 'hypertask-x')
        payload = self.box.payload('--only', 'processes', '--apply')
        for name, proc in protected.items():
            item = [row for row in payload['items'] if row.get('pid') == proc.pid]
            self.assertTrue(item, 'no item for {}'.format(name))
            self.assertEqual(item[0]['action'], 'keep', item[0])
            self.assertIn('protected', item[0]['reason'])
            self.assertIsNone(proc.poll())

    def test_a_tree_holding_a_protected_child_is_kept_whole(self):
        worktree = self.worktree()
        parent = self.box.spawn(cwd=worktree)
        self.box.add_process(parent.pid, 1, 'next dev', etimes=3 * 3600, cwd=worktree)
        child = self.box.spawn(cwd=worktree)
        self.box.add_process(child.pid, parent.pid, 'claude --resume', etimes=30, cwd=worktree)
        payload = self.box.payload('--only', 'processes', '--apply')
        item = [row for row in payload['items'] if row.get('pid') == parent.pid][0]
        self.assertEqual(item['action'], 'keep')
        self.assertIn('claude', item['reason'])
        self.assertIsNone(parent.poll())
        self.assertIsNone(child.poll())

    def test_another_users_processes_are_never_touched(self):
        worktree = self.worktree()
        foreign = self.box.spawn(cwd=worktree)
        self.box.add_process(foreign.pid, 1, 'chrome --headless', etimes=9 * 3600,
                             uid=UID + 1, cwd=worktree)
        payload = self.box.payload('--only', 'processes', '--apply')
        item = [row for row in payload['items'] if row.get('pid') == foreign.pid][0]
        self.assertEqual(item['action'], 'keep')
        self.assertIn('uid', item['reason'])
        self.assertIsNone(foreign.poll())

    def test_headless_browser_and_agent_browser_age_at_two_hours(self):
        worktree = self.worktree()
        old = self.box.spawn(cwd=worktree)
        young = self.box.spawn(cwd=worktree)
        self.box.add_process(old.pid, 1, 'chrome --headless --dump-dom', etimes=3 * 3600, cwd=worktree)
        self.box.add_process(young.pid, 1, 'chrome --headless --dump-dom', etimes=600, cwd=worktree)
        payload = self.box.payload('--only', 'processes', '--apply', '--grace', '1')
        self.assertEqual([row for row in payload['items'] if row.get('pid') == old.pid][0]['action'], 'kill')
        self.assertEqual([row for row in payload['items'] if row.get('pid') == young.pid][0]['action'], 'keep')
        old.wait(timeout=15)
        self.assertIsNone(young.poll())

    def test_provider_needs_the_agent_state_dir_proof(self):
        proven = self.box.spawn()
        unproven = self.box.spawn()
        self.box.add_process(proven.pid, 1, 'hax run', etimes=3600,
                             cwd=self.box.state / 'hypertask-run-1')
        self.box.add_process(unproven.pid, 1, 'hax run', etimes=3600, cwd=self.box.home)
        payload = self.box.payload('--only', 'processes', '--apply', '--grace', '1')
        proven_item = [row for row in payload['items'] if row.get('pid') == proven.pid][0]
        unproven_item = [row for row in payload['items'] if row.get('pid') == unproven.pid][0]
        self.assertEqual(proven_item['action'], 'kill')
        self.assertEqual(unproven_item['action'], 'keep')
        proven.wait(timeout=15)
        self.assertIsNone(unproven.poll())

    def test_chroma_mcp_and_agent_browser_chrome_orphans(self):
        worktree = self.worktree()
        chroma = self.box.spawn(cwd=worktree)
        attached = self.box.spawn(cwd=worktree)
        self.box.add_process(chroma.pid, 1, 'python3 chroma-mcp', etimes=9000, cwd=worktree)
        self.box.add_process(attached.pid, 1, 'python3 chroma-mcp', etimes=9000,
                             cwd=worktree, )
        # The attached one has a live parent, not init.
        self.box.rows[-1]['ppid'] = os.getpid()
        self.box.ps_file.write_text(self.box.ps_text())
        payload = self.box.payload('--only', 'processes', '--apply', '--grace', '1')
        self.assertEqual([row for row in payload['items'] if row.get('pid') == chroma.pid][0]['action'], 'kill')
        self.assertEqual([row for row in payload['items'] if row.get('pid') == attached.pid][0]['action'], 'keep')
        chroma.wait(timeout=15)
        self.assertIsNone(attached.poll())

    def test_zombies_are_reported_never_killed(self):
        zombie = self.box.spawn()
        self.box.add_process(zombie.pid, 1, 'node next dev', etimes=5 * 3600, stat='Z')
        payload = self.box.payload('--only', 'processes', '--apply')
        item = payload['items'][0]
        self.assertEqual(item['action'], 'report')
        self.assertEqual(item['kind'], 'zombie')
        self.assertIsNone(zombie.poll())
        self.assertEqual(payload['summary']['zombies'], 1)

    def test_ignores_term_and_is_killed_after_the_grace(self):
        worktree = self.worktree()
        stubborn = self.box.spawn(cwd=worktree, ignore_term=True)
        self.box.add_process(stubborn.pid, 1, 'chrome --headless', etimes=9 * 3600, cwd=worktree)
        payload = self.box.payload('--only', 'processes', '--apply', '--grace', '1')
        item = payload['items'][0]
        self.assertEqual(item['signals'], ['SIGTERM', 'SIGKILL'], item)
        stubborn.wait(timeout=20)
        self.assertIsNotNone(stubborn.returncode)

    def test_every_kill_is_logged_with_pid_kind_reason_and_cwd(self):
        worktree = self.worktree()
        proc = self.box.spawn(cwd=worktree)
        self.box.add_process(proc.pid, 1, 'next dev', etimes=3 * 3600, cwd=worktree)
        self.box.payload('--only', 'processes', '--apply', '--grace', '1')
        proc.wait(timeout=15)
        records = [r for r in self.box.log_records() if r.get('event') == 'kill']
        self.assertTrue(records, self.box.log_records())
        record = records[0]
        self.assertEqual(record['pid'], proc.pid)
        self.assertEqual(record['kind'], 'dev-server')
        self.assertTrue(record['reason'])
        self.assertEqual(record['cwd'], str(worktree))
        self.assertIn(record['signal'], ('SIGTERM', 'SIGKILL'))
        kills_log = (self.box.state / 'vps-tidy' / 'kills.log')
        self.assertTrue(kills_log.exists())
        self.assertIn(str(proc.pid), kills_log.read_text())

    def test_processes_part_does_nothing_in_a_dry_run(self):
        worktree = self.worktree()
        proc = self.box.spawn(cwd=worktree)
        self.box.add_process(proc.pid, 1, 'next dev', etimes=3 * 3600, cwd=worktree)
        payload = self.box.payload('--only', 'processes')
        self.assertEqual(payload['items'][0]['action'], 'kill')
        self.assertEqual(payload['items'][0]['result'], 'would-kill')
        self.assertIsNone(proc.poll())

    def test_only_processes_touches_no_files(self):
        self.box.make('tmp/stale/file', seconds_old=9 * DAY)
        payload = self.box.payload('--only', 'processes', '--apply')
        self.assertEqual([item for item in payload['items'] if item['part'] != 'processes'], [])
        self.assertTrue((self.box.tmp / 'stale').exists())


class TmuxRules(Base):
    AGES = {'VPS_TIDY_TMUX_SERVER_AGE': 1, 'VPS_TIDY_TMUX_DEAD_SOCKET_AGE': 1,
            'VPS_TIDY_TMUX_SESSION_AGE': 1}

    def setUp(self):
        super().setUp()
        if shutil.which('tmux') is None:
            self.skipTest('tmux is not installed')

    def test_stale_idle_private_server_is_closed_on_apply(self):
        sock = self.box.tmux_socket('delta-test-stale')
        self.box.start_tmux(sock, command='sleep 600')
        time.sleep(1.2)
        payload = self.box.payload('--only', 'tmux', '--apply', tmux_ages=self.AGES)
        item = next(i for i in payload['items'] if i.get('socket') == sock)
        self.assertEqual(item['action'], 'close-server')
        self.assertEqual(item['result'], 'closed')
        self.assertFalse(tmux_alive(sock))

    def test_young_private_server_is_kept(self):
        sock = self.box.tmux_socket('delta-test-young')
        self.box.start_tmux(sock, command='sleep 600')
        ages = dict(self.AGES)
        ages['VPS_TIDY_TMUX_SERVER_AGE'] = DAY
        payload = self.box.payload('--only', 'tmux', tmux_ages=ages)
        item = next(i for i in payload['items'] if i.get('socket') == sock)
        self.assertEqual(item['action'], 'keep')
        self.assertTrue(tmux_alive(sock))

    def test_private_server_with_busy_pane_is_kept(self):
        sock = self.box.tmux_socket('delta-test-busy')
        self.box.start_tmux(sock, command='python3 -c "import time; time.sleep(600)"')
        time.sleep(1.2)
        payload = self.box.payload('--only', 'tmux', tmux_ages=self.AGES)
        item = next(i for i in payload['items'] if i.get('socket') == sock)
        self.assertEqual(item['action'], 'keep')
        self.assertTrue(tmux_alive(sock))

    def test_dead_socket_is_removed_on_apply(self):
        path = self.box.dead_tmux_socket('delta-test-dead')
        payload = self.box.payload('--only', 'tmux', '--apply', tmux_ages=self.AGES)
        item = next(i for i in payload['items'] if i.get('path') == path)
        self.assertEqual(item['action'], 'remove')
        self.assertEqual(item['result'], 'removed')
        self.assertFalse(os.path.exists(path))

    def test_default_session_protected_prefix_is_kept(self):
        sock = self.box.tmux_socket('default')
        self.box.start_tmux(sock, session='live-test-protected', command='sleep 600')
        time.sleep(1.2)
        payload = self.box.payload('--only', 'tmux', tmux_ages=self.AGES)
        item = next(i for i in payload['items'] if i.get('session') == 'live-test-protected')
        self.assertEqual(item['action'], 'keep')

    def test_old_idle_default_session_closes_on_apply(self):
        sock = self.box.tmux_socket('default')
        self.box.start_tmux(sock, session='stale-idle-shell', command=None)
        time.sleep(2.0)
        pane_pid = self.box.pane_pid(sock, 'stale-idle-shell')
        self.box.seed_cmdline(pane_pid, ['/bin/bash'])
        payload = self.box.payload('--only', 'tmux', '--apply', tmux_ages=self.AGES)
        item = next(i for i in payload['items'] if i.get('session') == 'stale-idle-shell')
        self.assertEqual(item['action'], 'close-session')
        self.assertEqual(item['result'], 'closed')
        out = subprocess.run(['tmux', '-S', sock, 'has-session', '-t', 'stale-idle-shell'],
                             capture_output=True)
        self.assertNotEqual(out.returncode, 0)

    def test_dry_run_reports_would_close_without_acting(self):
        sock = self.box.tmux_socket('delta-test-dry')
        self.box.start_tmux(sock, command='sleep 600')
        time.sleep(1.2)
        payload = self.box.payload('--only', 'tmux', tmux_ages=self.AGES)
        item = next(i for i in payload['items'] if i.get('socket') == sock)
        self.assertEqual(item['result'], 'would-close')
        self.assertTrue(tmux_alive(sock))
        self.assertGreaterEqual(payload['summary']['removed'], 1)

    def test_attached_private_server_is_kept(self):
        sock = self.box.tmux_socket('delta-test-attached')
        self.box.start_tmux(sock, session='follow', command='sleep 600')
        time.sleep(1.2)
        mod = load_script()
        ctx_opts = {'apply': False, 'json': False, 'parts': ['tmux'], 'budget': 120,
                    'ps_file': str(self.box.ps_file), 'proc_root': str(self.box.proc),
                    'root': str(self.box.root), 'grace': 10, 'statvfs_json': None,
                    'caller': None}
        ctx = mod.Context(ctx_opts)
        real_rows = mod.tmux_session_rows

        def rows(side_ctx, side_sock):
            sessions, err = real_rows(side_ctx, side_sock)
            if err:
                return sessions, err
            patched = []
            for row in sessions:
                row = dict(row)
                if row.get('name') == 'follow':
                    row['attached'] = 1
                patched.append(row)
            return patched, None

        with unittest.mock.patch.object(mod, 'tmux_session_rows', side_effect=rows):
            mod.scan_tmux(ctx)
        item = next(i for i in ctx.items if i.get('socket') == sock)
        self.assertEqual(item['action'], 'keep')
        self.assertIn('attached', item['reason'].lower())
        self.assertTrue(tmux_alive(sock))

    def test_private_server_tail_follow_is_kept(self):
        log = self.box.make('build.log', body='line\n')
        sock = self.box.tmux_socket('delta-test-tail')
        self.box.start_tmux(sock, command='tail -f {}'.format(log))
        time.sleep(1.2)
        payload = self.box.payload('--only', 'tmux', tmux_ages=self.AGES)
        item = next(i for i in payload['items'] if i.get('socket') == sock)
        self.assertEqual(item['action'], 'keep')

    def test_unreadable_proc_keeps_stale_sleep_server(self):
        sock = self.box.tmux_socket('delta-test-proc')
        self.box.start_tmux(sock, command='sleep 600')
        time.sleep(1.2)
        mode = self.box.proc.stat().st_mode
        os.chmod(self.box.proc, 0)
        try:
            payload = self.box.payload('--only', 'tmux', tmux_ages=self.AGES)
        finally:
            os.chmod(self.box.proc, mode)
        item = next(i for i in payload['items'] if i.get('socket') == sock)
        self.assertEqual(item['action'], 'keep')
        self.assertTrue(tmux_alive(sock))

    def test_old_socket_on_live_server_not_removed_on_apply(self):
        sock = self.box.tmux_socket('delta-test-live-sock')
        self.box.start_tmux(sock, command='sleep 600')
        time.sleep(1.2)
        age(sock, 7200)
        mod = load_script()
        calls = []

        def fake_command(ctx, target_sock, extra, timeout=10):
            calls.append(extra)
            if extra == ['list-sessions']:
                return None, 'timed out'
            return mod.tmux_command(ctx, target_sock, extra, timeout=timeout)

        ctx_opts = {'apply': True, 'json': False, 'parts': ['tmux'], 'budget': 120,
                    'ps_file': str(self.box.ps_file), 'proc_root': str(self.box.proc),
                    'root': str(self.box.root), 'grace': 10, 'statvfs_json': None,
                    'caller': None}
        ctx = mod.Context(ctx_opts)
        with unittest.mock.patch.object(mod, 'tmux_command', side_effect=fake_command):
            mod.scan_tmux(ctx)
        actions = [item['action'] for item in ctx.items if item.get('socket') == sock]
        self.assertNotIn('remove', actions)
        self.assertTrue(tmux_alive(sock))


class TmuxProbeContract(unittest.TestCase):
    def test_confirmed_dead_rejects_timeout_only(self):
        mod = load_script()
        ctx = mod.Context(self._ctx_opts())
        plan = [(None, 'timed out'), (None, 'error connecting to /tmp/x')]
        with unittest.mock.patch.object(mod, 'tmux_command', side_effect=plan):
            self.assertFalse(mod.tmux_server_confirmed_dead(ctx, '/tmp/x'))

    def test_confirmed_dead_needs_two_no_server_probes(self):
        mod = load_script()
        ctx = mod.Context(self._ctx_opts())
        msg = 'error connecting to /tmp/x'
        plan = [(None, msg), (None, msg)]
        with unittest.mock.patch.object(mod, 'tmux_command', side_effect=plan):
            self.assertTrue(mod.tmux_server_confirmed_dead(ctx, '/tmp/x'))

    def test_confirmed_dead_stops_when_server_answers(self):
        mod = load_script()
        ctx = mod.Context(self._ctx_opts())
        plan = [(None, 'no server running on /tmp/x'), ('', None)]
        with unittest.mock.patch.object(mod, 'tmux_command', side_effect=plan):
            self.assertFalse(mod.tmux_server_confirmed_dead(ctx, '/tmp/x'))

    def _ctx_opts(self):
        return {'apply': False, 'json': False, 'parts': ['tmux'], 'budget': 120,
                'ps_file': None, 'proc_root': '/proc', 'root': None, 'grace': 10,
                'statvfs_json': None, 'caller': None}


def tmux_alive(sock):
    return subprocess.run(['tmux', '-S', sock, 'list-sessions'],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


class Shape(Base):
    def test_json_summary_and_log(self):
        stale = self.box.make('tmp/stale/file', seconds_old=5 * DAY)
        payload = self.box.payload('--only', 'tmp', '--apply')
        self.assertEqual(payload['mode'], 'apply')
        self.assertEqual(payload['parts'], ['tmp'])
        self.assertIn('used_percent', payload['disk'])
        self.assertEqual(payload['summary']['removed'], 1)
        self.assertGreaterEqual(payload['summary']['freed_bytes'], 0)
        self.assertTrue(self.box.run_logs())
        summary = [r for r in self.box.log_records() if r.get('event') == 'summary']
        self.assertEqual(len(summary), 1)
        self.assertIn('used_percent', summary[0])
        self.assertIn('would_free_bytes', summary[0])
        self.assertIn('removed', summary[0])
        status = json.loads((self.box.state / 'vps-tidy' / 'status.json').read_text())
        self.assertIn('finished_at', status)
        self.assertNotIn('verdict', status)

    def test_human_report_names_a_keep_reason_for_every_candidate(self):
        self.box.make('tmp/fresh/file')
        self.box.make('tmp/claude-{}/x/file'.format(UID), seconds_old=9 * DAY)
        done = self.box.run('--only', 'tmp')
        self.assertEqual(done.returncode, 0, done.stderr)
        for line in done.stdout.splitlines():
            if line.startswith(('remove ', 'keep ', 'kill ', 'report ')):
                self.assertIn('(', line)
        self.assertIn('keep', done.stdout)

    def test_usage_errors(self):
        bad_part = self.box.run('--only', 'nonsense')
        self.assertEqual(bad_part.returncode, 2)
        bad_flag = self.box.run('--nonsense')
        self.assertEqual(bad_flag.returncode, 2)

    def test_lock_held_refuses_the_run(self):
        lock = self.box.state / 'vps-tidy' / 'lock'
        lock.parent.mkdir(parents=True, exist_ok=True)
        with open(lock, 'w') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            done = self.box.run('--only', 'tmp')
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertIn('another run', done.stdout + done.stderr)

    def test_caller_is_recorded(self):
        payload = self.box.payload('--only', 'tmp')
        self.assertTrue(payload['caller'])
        self.assertNotEqual(payload['caller'], 'unknown')

    def test_board_alarm_is_reported_never_posted(self):
        high = {'total': 100 * 1024 ** 3, 'free': 8 * 1024 ** 3}
        payload = self.box.payload('--only', 'tmp', statvfs=high)
        self.assertTrue(payload['alarm']['needed'])
        self.assertIn('85', payload['alarm']['text'])
        self.assertFalse(any('hypertask' in call for call in self.box.tool_calls()))


class VerifySkill(unittest.TestCase):
    def test_run_is_executable_and_has_features(self):
        self.assertTrue(VERIFY_RUN.is_file(), VERIFY_RUN)
        self.assertTrue(os.access(VERIFY_RUN, os.X_OK), 'run is not executable')
        features = ROOT / '.claude' / 'skills' / 'verify-vps-tidy' / 'features'
        self.assertTrue((features / 'README.md').is_file())
        self.assertGreaterEqual(len(list(features.glob('*.md'))), 3)

    def test_grader_fails_when_the_stale_item_still_exists(self):
        loader = importlib.machinery.SourceFileLoader('verify_vps_tidy_run', str(VERIFY_RUN))
        spec = importlib.util.spec_from_loader('verify_vps_tidy_run', loader)
        module = importlib.util.module_from_spec(spec)
        try:
            loader.exec_module(module)
        except AttributeError:
            self.skipTest('run holds no grade to call')
        grade = getattr(module, 'grade', None)
        if grade is None:
            self.skipTest('run holds no grade to call')
        self.assertEqual(grade({'stale_gone': True, 'fresh_alive': True,
                                'orphan_gone': True, 'protected_alive': True,
                                'untouched_alive': True}), 'PASS')
        self.assertEqual(grade({'stale_gone': False, 'fresh_alive': True,
                                'orphan_gone': True, 'protected_alive': True,
                                'untouched_alive': True}), 'FAIL')
        self.assertEqual(grade({'stale_gone': True, 'fresh_alive': True,
                                'orphan_gone': True, 'protected_alive': False,
                                'untouched_alive': True}), 'FAIL')


if __name__ == '__main__':
    unittest.main()
