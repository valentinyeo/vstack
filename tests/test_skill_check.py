#!/usr/bin/env python3
"""Drive scripts/skill-check.py and the nightly wrapper against throwaway homes."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/skill-check.py'
NIGHTLY = ROOT / 'scripts/skill-check-nightly'

FAKE_HYPERTASK = '''#!/usr/bin/env python3
import json, os, pathlib, sys
path = pathlib.Path(os.environ['FAKE_HYPERTASK_STATE'])
state = json.loads(path.read_text())
args = sys.argv[1:]
if '--token' in args:
    index = args.index('--token')
    assert args[index + 1] == 'private-test-token'
    del args[index:index + 2]
if state.get('fail'):
    print('fake hypertask failed', file=sys.stderr)
    sys.exit(1)
state['calls'].append(args)
path.write_text(json.dumps(state))
print(json.dumps({'success': True}))
'''


def frontmatter(name=None, description=None, extra=''):
    lines = ['---']
    if name is not None:
        lines.append('name: ' + name)
    if description is not None:
        lines.append('description: ' + description)
    if extra:
        lines.extend(extra.rstrip('\n').split('\n'))
    lines.append('---')
    return '\n'.join(lines) + '\n'


def skill_md(name, description='short description'):
    return frontmatter(name=name, description=description) + '\n# ' + name + '\n\nBody.\n'


def run(*args, env=None):
    if env is None:
        env = {'PATH': os.environ['PATH'], 'HOME': os.environ.get('HOME', '/tmp')}
    return subprocess.run([sys.executable, str(SCRIPT), *[str(a) for a in args]],
                          capture_output=True, text=True, env=env)


class HomeCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.home = self.base / 'home'
        self.skills = self.home / '.claude/skills'
        self.commands = self.home / '.claude/commands'
        self.plugins = self.home / '.claude/plugins'
        self.installed = {}
        self.enabled = {}
        self.retired = self.base / 'retired.txt'
        self.retired.write_text('# retired terms\n')
        self.allow = self.base / 'allow.txt'
        self.allow.write_text('# allowed\n')

    def add_skill(self, name, description='short description', body=None, text=None):
        folder = self.skills / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'SKILL.md').write_text(
            text if text is not None else skill_md(name, description))
        return folder

    def add_command(self, name, description='command description', text=None):
        self.commands.mkdir(parents=True, exist_ok=True)
        path = self.commands / (name + '.md')
        path.write_text(text if text is not None
                        else frontmatter(name=name, description=description) + '\nDo it.\n')
        return path

    def add_plugin(self, key, enabled=True, skills=(), commands=(), install=None):
        plugin = self.base / 'plugin-installs' / key.split('@')[0]
        plugin = install or plugin
        for name, description in skills:
            folder = plugin / 'skills' / name
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'SKILL.md').write_text(skill_md(name, description))
        for name, description in commands:
            folder = plugin / 'commands'
            folder.mkdir(parents=True, exist_ok=True)
            (folder / (name + '.md')).write_text(
                frontmatter(name=name, description=description) + '\nDo it.\n')
        self.installed[key] = [{'installPath': str(plugin)}]
        self.enabled[key] = enabled
        self.write_plugin_json()
        return plugin

    def write_plugin_json(self):
        self.plugins.mkdir(parents=True, exist_ok=True)
        (self.plugins / 'installed_plugins.json').write_text(
            json.dumps({'version': 2, 'plugins': self.installed}))
        (self.home / '.claude/settings.json').write_text(
            json.dumps({'enabledPlugins': self.enabled}))

    def check(self, *args):
        return run('--home', self.home, '--host-label', 'testhost',
                   '--retired-file', self.retired, '--allow-file', self.allow, *args)

    def report(self, *args):
        result = self.check('--json', *args)
        return result, json.loads(result.stdout)

    def kinds(self, report):
        return [f['kind'] for f in report['findings']]


class CleanAndEmpty(HomeCase):
    def test_a_clean_home_exits_zero(self):
        self.add_skill('clean-skill')
        self.add_command('clean-command')
        result, report = self.report()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report['findings'], [])
        self.assertEqual(report['host'], 'testhost')

    def test_an_empty_home_exits_zero(self):
        self.home.mkdir(parents=True)
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('0 findings', result.stdout.splitlines()[-1])

    def test_the_plain_line_names_findings_bytes_and_counts(self):
        self.add_skill('one', 'desc')
        result = self.check()
        line = result.stdout.splitlines()[-1]
        self.assertRegex(line, r'^skill-check testhost: 0 findings, \d+ visible description '
                              r'bytes \(budget 20000\), 1 visible, 0 hidden$')

    def test_a_bad_budget_is_a_usage_error(self):
        result = self.check('--budget', 'many')
        self.assertEqual(result.returncode, 2)


class Crashes(HomeCase):
    def test_an_unexpected_failure_exits_two_and_prints_one_line(self):
        self.add_skill('one')
        blocker = self.base / 'blocker'
        blocker.write_text('a plain file, not a directory\n')
        result = self.check('--out', blocker / 'report.json')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(len(result.stderr.strip().splitlines()), 1, result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertFalse((blocker / 'report.json').exists())


class DeadLinks(HomeCase):
    def test_a_dead_symlink_in_skills_is_a_finding(self):
        self.skills.mkdir(parents=True)
        (self.skills / 'gone').symlink_to(self.base / 'missing-dir')
        result, report = self.report()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.kinds(report), ['dead-link'])
        self.assertEqual(report['findings'][0]['subject'], 'gone')

    def test_the_detail_holds_the_link_path_and_its_target(self):
        self.skills.mkdir(parents=True)
        link = self.skills / 'gone'
        link.symlink_to(self.base / 'missing-dir')
        result, report = self.report()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report['findings'][0]['detail'],
                         '%s -> %s' % (link, self.base / 'missing-dir'))

    def test_a_dead_symlink_in_commands_is_a_finding(self):
        self.commands.mkdir(parents=True)
        (self.commands / 'gone.md').symlink_to(self.base / 'missing.md')
        result, report = self.report()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.kinds(report), ['dead-link'])
        self.assertIn('gone', report['findings'][0]['subject'])

    def test_a_live_symlink_is_not_a_finding(self):
        target = self.base / 'real-skill'
        target.mkdir(parents=True)
        (target / 'SKILL.md').write_text(skill_md('linked'))
        self.skills.mkdir(parents=True)
        (self.skills / 'linked').symlink_to(target)
        result, report = self.report()
        self.assertEqual(result.returncode, 0, report['findings'])
        self.assertEqual(report['totals']['visible_items'], 1)


class Duplicates(HomeCase):
    def test_a_user_skill_and_an_enabled_plugin_skill_share_a_name(self):
        self.add_skill('shared')
        self.add_plugin('demo@one', skills=[('shared', 'plugin copy')])
        result, report = self.report()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.kinds(report), ['duplicate-name'])
        self.assertEqual(report['findings'][0]['subject'], 'shared')
        detail = report['findings'][0]['detail']
        self.assertIn('user skills', detail)
        self.assertIn('demo@one', detail)

    def test_a_disabled_plugin_with_the_same_name_is_not_a_duplicate(self):
        self.add_skill('shared')
        self.add_plugin('demo@one', enabled=False, skills=[('shared', 'plugin copy')])
        result, report = self.report()
        self.assertEqual(result.returncode, 0, report['findings'])
        self.assertEqual(report['totals']['visible_items'], 1)

    def test_an_old_version_in_the_cache_is_never_read(self):
        self.add_skill('shared')
        self.add_plugin('demo@one')
        stale = self.home / '.claude/plugins/cache/demo/9.9.9'
        stale_skill = stale / 'skills/shared'
        stale_skill.mkdir(parents=True)
        (stale_skill / 'SKILL.md').write_text(skill_md('shared'))
        result, report = self.report()
        self.assertEqual(result.returncode, 0, report['findings'])

    def test_two_enabled_plugins_may_share_a_name(self):
        self.add_plugin('one@a', skills=[('twin', 'a')])
        self.add_plugin('two@b', skills=[('twin', 'b')])
        result, report = self.report()
        self.assertEqual(result.returncode, 0, report['findings'])

    def test_the_allow_file_silences_a_duplicate(self):
        self.add_skill('shared')
        self.add_plugin('demo@one', skills=[('shared', 'plugin copy')])
        self.allow.write_text('duplicate-name:shared\n')
        result, report = self.report()
        self.assertEqual(result.returncode, 0, report['findings'])

    def test_a_missing_settings_file_means_no_plugins(self):
        self.add_skill('shared')
        self.installed['demo@one'] = [{'installPath': str(self.base / 'nowhere')}]
        self.plugins.mkdir(parents=True)
        (self.plugins / 'installed_plugins.json').write_text(
            json.dumps({'plugins': self.installed}))
        result, report = self.report()
        self.assertEqual(result.returncode, 0, report['findings'])


class RetiredTerms(HomeCase):
    def setUp(self):
        super().setUp()
        self.retired.write_text('# retired\nToken-Ladder\nhouse-rules\n')

    def test_a_retired_term_in_a_skill_is_a_finding(self):
        self.add_skill('old', text=frontmatter(name='old', description='d') +
                       '\nRun the token-ladder now.\n')
        result, report = self.report()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.kinds(report), ['retired-term'])
        self.assertEqual(report['findings'][0]['subject'], 'old')
        self.assertIn('token-ladder', report['findings'][0]['detail'].lower())
        self.assertIn('line 6', report['findings'][0]['detail'])

    def test_a_retired_term_in_a_command_is_a_finding(self):
        self.add_command('legacy', text=frontmatter(name='legacy', description='d') +
                         '\nSee house-rules.\n')
        result, report = self.report()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.kinds(report), ['retired-term'])
        self.assertEqual(report['findings'][0]['subject'], 'legacy')

    def test_the_allow_file_silences_one_term(self):
        self.add_skill('old', text=frontmatter(name='old', description='d') +
                       '\nRun the token-ladder now.\n')
        self.allow.write_text('retired-term:old:token-ladder\n')
        result, report = self.report()
        self.assertEqual(result.returncode, 0, report['findings'])

    def test_plugin_files_are_never_scanned(self):
        plugin = self.base / 'plugin-installs/demo'
        folder = plugin / 'skills/old'
        folder.mkdir(parents=True)
        (folder / 'SKILL.md').write_text(
            frontmatter(name='old-plugin', description='d') + '\nRun token-ladder.\n')
        self.add_plugin('demo@one', install=plugin)
        result, report = self.report()
        self.assertEqual(result.returncode, 0, report['findings'])

    def test_orchestrator_board_drain_sentence_is_retired(self):
        self.retired.write_text('# retired\norchestrator\ncentral watcher\n')
        self.add_skill('valentin-mode', text=frontmatter(name='valentin-mode', description='d') +
                       '\norchestrators loop until their board is drained.\n')
        result, report = self.report()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.kinds(report), ['retired-term'])
        self.assertIn('orchestrator', report['findings'][0]['detail'].lower())


class Budget(HomeCase):
    def test_a_total_under_the_budget_passes(self):
        self.add_skill('a', 'b' * 10)
        result, report = self.report('--budget', '100')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(report['totals']['visible_bytes'], len('a' + 'b' * 10))
        self.assertEqual(report['totals']['budget'], 100)

    def test_a_total_over_the_budget_fails(self):
        self.add_skill('a', 'b' * 10)
        result, report = self.report('--budget', '5')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.kinds(report), ['over-budget'])

    def test_the_detail_names_the_budget_not_the_overage(self):
        self.add_skill('a', 'b' * 29)
        result, report = self.report('--budget', '10')
        self.assertEqual(result.returncode, 1)
        detail = report['findings'][0]['detail']
        self.assertIn('over the budget of 10 bytes', detail)
        self.assertNotIn('20', detail)
        self.assertEqual(report['totals']['visible_bytes'], 30)

    def test_two_runs_whose_overage_differs_share_one_digest(self):
        self.add_skill('a', 'b' * 10)
        first = self.report('--budget', '5')[1]
        self.add_skill('second', 'c' * 90)
        second = self.report('--budget', '5')[1]
        self.assertEqual(self.kinds(first), ['over-budget'])
        self.assertEqual(self.kinds(second), ['over-budget'])
        self.assertNotEqual(first['totals']['visible_bytes'],
                            second['totals']['visible_bytes'])
        self.assertEqual(first['digest'], second['digest'])

    def test_hidden_items_cost_nothing(self):
        self.add_skill('shown', 'b' * 4)
        self.add_skill('hidden-one', 'b' * 400, text=frontmatter(
            name='hidden-one', description='b' * 400,
            extra='disable-model-invocation: true') + '\nBody.\n')
        result, report = self.report('--budget', '50')
        self.assertEqual(result.returncode, 0, report['findings'])
        self.assertEqual(report['totals']['visible_bytes'], len('shown' + 'b' * 4))
        self.assertEqual(report['totals']['visible_items'], 1)
        self.assertEqual(report['totals']['hidden_items'], 1)
        plain = self.check('--budget', '50')
        self.assertIn('1 visible, 1 hidden', plain.stdout.splitlines()[-1])

    def test_the_top_ten_lists_the_largest_first(self):
        self.add_skill('small', 'x')
        self.add_skill('large', 'y' * 50)
        result, report = self.report()
        top = report['totals']['top']
        self.assertEqual(top[0]['name'], 'large')
        self.assertLessEqual(len(top), 10)

    def test_plugin_bytes_are_counted_per_source(self):
        self.add_skill('user-one', 'u' * 3)
        self.add_plugin('demo@one', skills=[('plug-one', 'p' * 5)])
        result, report = self.report()
        self.assertEqual(report['totals']['by_source']['user skills'],
                         len('user-one' + 'u' * 3))
        self.assertEqual(report['totals']['by_source']['plugins'],
                         len('plug-one' + 'p' * 5))


class Parsing(HomeCase):
    def test_folded_and_quoted_descriptions_keep_exact_bytes(self):
        self.add_skill('folded', text='---\nname: folded\ndescription: >\n  one two\n  three\n'
                                      '---\n\nBody.\n')
        self.add_skill('quoted', text='---\nname: quoted\n'
                                      'description: "with: a colon"\n---\n\nBody.\n')
        self.add_skill('literal', text='---\nname: literal\ndescription: |\n  line one\n'
                                       '  line two\n---\n\nBody.\n')
        result, report = self.report()
        self.assertEqual(result.returncode, 0, report['findings'])
        total = (len('folded' + 'one two three')
                 + len('quoted' + 'with: a colon')
                 + len('literal' + 'line one\nline two'))
        self.assertEqual(report['totals']['visible_bytes'], total)

    def test_broken_frontmatter_does_not_crash(self):
        self.add_skill('broken', text='---\nname: [unclosed\ndescription: "unterminated\n'
                                      '---\nFirst body line.\n')
        result, report = self.report()
        self.assertIn(result.returncode, (0, 1), result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(report['totals']['visible_items'], 1)

    def test_no_frontmatter_uses_the_directory_name_and_first_body_line(self):
        self.add_skill('bare', text='# Bare\n\nDo the thing.\n')
        result, report = self.report()
        self.assertEqual(result.returncode, 0, report['findings'])
        top = report['totals']['top'][0]
        self.assertEqual(top['name'], 'bare')
        self.assertEqual(report['totals']['visible_bytes'],
                         len('bare' + '# Bare'))


class Output(HomeCase):
    def test_json_shape(self):
        self.add_skill('one')
        result, report = self.report()
        self.assertEqual(sorted(report), ['digest', 'findings', 'home', 'host', 'time',
                                          'totals'])
        self.assertEqual(sorted(report['totals']),
                         ['budget', 'by_source', 'hidden_items', 'top', 'visible_bytes',
                          'visible_items'])
        self.assertRegex(report['time'], r'^\d{4}-\d{2}-\d{2}T.+Z$')
        self.assertRegex(report['digest'], r'^[0-9a-f]{64}$')
        self.assertEqual(report['home'], str(self.home))

    def test_out_writes_json_even_when_clean(self):
        self.add_skill('one')
        out = self.base / 'nested/dir/report.json'
        result = self.check('--out', out)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(out.is_file())
        report = json.loads(out.read_text())
        self.assertEqual(report['findings'], [])
        self.assertEqual(report['host'], 'testhost')

    def test_one_line_per_finding(self):
        self.add_skill('shared')
        self.add_plugin('demo@one', skills=[('shared', 'plugin copy')])
        result = self.check()
        self.assertEqual(result.returncode, 1)
        first = result.stdout.splitlines()[0]
        self.assertTrue(first.startswith('duplicate-name: shared: '), first)


class Nightly(HomeCase):
    def nightly(self, *args, env=None):
        if env is None:
            env = {'PATH': os.environ['PATH'], 'HOME': str(self.home)}
        return subprocess.run(
            ['bash', str(NIGHTLY),
             '--state-dir', str(self.base / 'state'), '--check', str(SCRIPT), *args],
            capture_output=True, text=True, env=env)

    def test_without_a_ticket_it_only_writes_the_state_report(self):
        self.add_skill('one')
        state = self.base / 'state'
        result = self.nightly()
        self.assertEqual(result.returncode, 0, result.stderr)
        latest = json.loads((state / 'latest.json').read_text())
        self.assertEqual(latest['findings'], [])
        self.assertFalse((state / 'posted.digest').exists())

    def test_the_host_label_reaches_the_state_report(self):
        self.add_skill('one')
        state = self.base / 'state'
        result = self.nightly('--host-label', 'hetzner')
        self.assertEqual(result.returncode, 0, result.stderr)
        latest = json.loads((state / 'latest.json').read_text())
        self.assertEqual(latest['host'], 'hetzner')

    def test_the_host_label_defaults_to_the_hostname(self):
        self.add_skill('one')
        state = self.base / 'state'
        result = self.nightly()
        self.assertEqual(result.returncode, 0, result.stderr)
        latest = json.loads((state / 'latest.json').read_text())
        self.assertEqual(latest['host'], socket.gethostname())

    def test_the_usage_names_the_host_label(self):
        result = self.nightly('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--host-label', result.stdout)

    def test_a_crashing_check_leaves_no_stale_report(self):
        state = self.base / 'state'
        state.mkdir(parents=True)
        stale = state / 'latest.json'
        stale.write_text(json.dumps({'host': 'last-night', 'findings': []}))
        broken = self.base / 'crashing-check'
        broken.write_text('import sys\nsys.exit(3)\n')
        result = self.nightly('--check', str(broken))
        self.assertEqual(result.returncode, 1)
        self.assertIn('exit 3', result.stderr)
        self.assertFalse(stale.exists())


class NightlyHypertask(HomeCase):
    """Drive the nightly wrapper against a fake hypertask that records its argv."""

    def setUp(self):
        super().setUp()
        self.add_skill('one')
        self.bin = self.base / 'bin'
        self.bin.mkdir(parents=True)
        fake = self.bin / 'hypertask'
        fake.write_text(FAKE_HYPERTASK)
        fake.chmod(0o755)
        self.token = self.base / 'token'
        self.token.write_text('private-test-token\n')
        self.state = self.base / 'state'
        self.record = self.base / 'calls.json'

    def nightly(self, *args, fail=False, env=None):
        self.record.write_text(json.dumps({'calls': [], 'fail': fail}))
        full = {'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
                'HOME': str(self.home),
                'FAKE_HYPERTASK_STATE': str(self.record)}
        full.update(env or {})
        return subprocess.run(
            ['bash', str(NIGHTLY), '--state-dir', str(self.state), '--check', str(SCRIPT),
             '--token-file', str(self.token), '--ticket', 'VSTA-36',
             '--project', '13556', *[str(a) for a in args]],
            capture_output=True, text=True, env=full)

    def fake_ssh_serving(self, payload):
        fake = self.bin / 'ssh'
        fake.write_text('#!/usr/bin/env bash\ncat ' + str(payload) + '\n')
        fake.chmod(0o755)

    def test_an_unreadable_remote_age_counts_as_a_missing_report(self):
        payload = self.base / 'remote.json'
        payload.write_text(json.dumps(
            {'host': 'hetzner', 'time': 'whenever',
             'findings': [{'kind': 'dead-link', 'subject': 'gone',
                           'detail': '/x/gone -> /x/missing'}],
             'totals': {}}))
        self.fake_ssh_serving(payload)
        # A python that dies inside the age snippet prints no age at all.
        mute = self.bin / 'python-mute-age'
        mute.write_text('#!/usr/bin/env bash\n'
                        'if [ "$1" = "-" ] && [ "$#" -eq 2 ]; then exit 0; fi\n'
                        'exec ' + sys.executable + ' "$@"\n')
        mute.chmod(0o755)
        result = self.nightly('--remote', 'box:%s' % payload,
                              env={'PYTHON': str(mute)})
        self.assertEqual(result.returncode, 0, result.stderr)
        body = (self.state / 'comment.html').read_text()
        self.assertIn('remote-report: missing', body)
        self.assertNotIn('/x/missing', body)

    def test_a_fresh_remote_report_is_reported(self):
        payload = self.base / 'remote.json'
        stamp = subprocess.run(
            [sys.executable, '-c',
             'import datetime; print(datetime.datetime.now(datetime.timezone.utc)'
             '.strftime("%Y-%m-%dT%H:%M:%SZ"))'],
            capture_output=True, text=True, check=True).stdout.strip()
        payload.write_text(json.dumps(
            {'host': 'hetzner', 'time': stamp,
             'findings': [{'kind': 'dead-link', 'subject': 'gone',
                           'detail': '/x/gone -> /x/missing'}],
             'totals': {}}))
        self.fake_ssh_serving(payload)
        result = self.nightly('--remote', 'box:%s' % payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        body = (self.state / 'comment.html').read_text()
        self.assertIn('/x/missing', body)
        self.assertNotIn('remote-report: missing', body)

    def calls(self, verb):
        return [call for call in json.loads(self.record.read_text())['calls']
                if call[:2] == [verb, 'add']]

    def test_the_comment_carries_kind_qa(self):
        result = self.nightly()
        self.assertEqual(result.returncode, 0, result.stderr)
        comments = self.calls('comment')
        self.assertEqual(len(comments), 1, comments)
        comment = comments[0]
        self.assertIn('--kind', comment, comment)
        self.assertEqual(comment[comment.index('--kind') + 1], 'qa', comment)
        self.assertIn('--file', comment, comment)

    def test_the_activity_log_stays_without_a_kind(self):
        result = self.nightly()
        self.assertEqual(result.returncode, 0, result.stderr)
        logs = self.calls('activity')
        self.assertEqual(len(logs), 1, logs)
        self.assertNotIn('--kind', logs[0], logs[0])

    def test_the_token_is_never_printed(self):
        result = self.nightly()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('private-test-token', result.stdout + result.stderr)

    def test_a_failed_comment_leaves_the_digest_unstored(self):
        result = self.nightly(fail=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.state / 'posted.digest').exists())

    def test_a_second_run_with_the_same_findings_posts_nothing(self):
        self.assertEqual(self.nightly().returncode, 0)
        self.assertTrue((self.state / 'posted.digest').exists())
        result = self.nightly()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls('comment')), 0)
        self.assertIn('nothing new to post', result.stdout)


if __name__ == '__main__':
    unittest.main()
