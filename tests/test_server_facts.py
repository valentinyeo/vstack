#!/usr/bin/env python3
"""One true description of our servers, and a check that keeps it that way (VSTA-146).

A Multi Bot chat read ~/.claude/reference/tools.md, which called Hetzner the
primary server and Contabo-UK the secondary one, and told Valentin that only
inne runs on Hetzner. A Multi Bot default had already pointed 14 tabs at
Hetzner, so they showed "Chat not available".

docs/servers.md is the one description every chat reads. config/servers.json
holds the same facts for tools. This test fails when the two disagree, and when
any file a chat can load (this repo's docs, skills, hooks, scripts, install line,
or the installed reference notes) says Hetzner is primary, Contabo-UK secondary,
or Hetzner runs only inne.

tests/ is skipped on purpose: the fixture below quotes the old wording.
"""

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs' / 'servers.md'
FACTS = ROOT / 'config' / 'servers.json'
OLD_NOTES = ROOT / 'tests' / 'fixtures' / 'server-facts' / 'old-tools.md'
INSTALL = ROOT / 'install'

HETZNER = re.compile(r'hetzner', re.I)
CONTABO = re.compile(r'contabo|vmi3202882', re.I)
PRIMARY = re.compile(r'\b(primary|main)\b', re.I)
SECONDARY = re.compile(r'\bsecondary\b', re.I)
SERVER_WORD = re.compile(r'\b(server|servers|vps|machine|host|box)\b', re.I)
INNE_ONLY = re.compile(r'\b(?:only|just)\b[^.;]{0,40}\binne\b'
                       r'|\binne[-\s]+only\b'
                       r'|\binne\b[^.;]{0,25}\bonly\b', re.I)
# "Hetzner is a shared server, not the main one" corrects the old claim; it is
# not the claim. A line that negates it stays quiet.
NEGATED = re.compile(r"\b(never|not|no longer|do not|does not|isn't|aren't|don't"
                     r"|doesn't|wrong|incorrect)\b", re.I)

TEXT_SUFFIXES = ('.md', '.json', '.txt', '.py', '.sh', '.yml', '.yaml', '.toml')
SKIP_DIRS = {'.git', 'tests', 'node_modules', '__pycache__', 'worktrees'}
MAX_BYTES = 1_000_000


def wrong_claims(text):
    """Return (line number, what is wrong) for each bad claim in text.

    A claim counts only inside one sentence naming the server, except the inne
    phrase, which the old note wrote as its own sentence after naming Hetzner.
    """
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        sentences = [s for s in re.split(r'(?<=[.!?])\s+', line.strip()) if s]
        for sentence in sentences:
            if NEGATED.search(sentence):
                continue
            if HETZNER.search(sentence) and PRIMARY.search(sentence) and SERVER_WORD.search(sentence):
                findings.append((number, 'calls Hetzner the primary server'))
            if CONTABO.search(sentence) and SECONDARY.search(sentence):
                findings.append((number, 'calls Contabo-UK the secondary server'))
        if (HETZNER.search(line) and INNE_ONLY.search(line)
                and not NEGATED.search(line)):
            findings.append((number, 'says only inne runs on Hetzner'))
    return findings


def scan_text(name, text):
    """Return "file:line: problem" lines for one file's text."""
    return ['%s:%d: %s' % (name, number, problem)
            for number, problem in wrong_claims(text)]


def repo_files():
    """Every tracked text file a chat can load from this checkout.

    Tracked only: tests/ and a chat's scratch brief.txt quote the old wording on
    purpose, and neither is a file another chat reads as server facts.
    """
    tracked = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-z'],
                             capture_output=True, text=True)
    if tracked.returncode != 0:
        return
    for name in tracked.stdout.split('\0'):
        if not name:
            continue
        path = ROOT / name
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in Path(name).parts):
            continue
        if path.suffix not in TEXT_SUFFIXES and path.name != 'install':
            continue
        if path.stat().st_size > MAX_BYTES:
            continue
        yield path


def reference_dirs():
    """Where installed reference notes live: the override first, then the real one."""
    dirs = []
    override = os.environ.get('VSTACK_REFERENCE_DIR')
    if override:
        dirs.append(Path(override))
    real = Path.home() / '.claude' / 'reference'
    if real not in dirs:
        dirs.append(real)
    return dirs


class TheCheckItself(unittest.TestCase):
    def test_fails_on_the_old_tools_md_lines(self):
        # The exact wording that sent 14 Multi Bot tabs to Hetzner.
        findings = wrong_claims(OLD_NOTES.read_text())
        self.assertEqual(findings, [
            (5, 'calls Hetzner the primary server'),
            (5, 'says only inne runs on Hetzner'),
            (6, 'calls Contabo-UK the secondary server'),
        ])

    def test_catches_the_claim_in_another_order(self):
        findings = wrong_claims('The primary server we use is Hetzner.')
        self.assertEqual(findings, [(1, 'calls Hetzner the primary server')])

    def test_catches_the_inne_phrase_alone(self):
        findings = wrong_claims('Hetzner is where the inne chats only run.')
        self.assertEqual(findings, [(1, 'says only inne runs on Hetzner')])

    def test_stays_quiet_on_a_correction(self):
        self.assertEqual(wrong_claims(
            'Hetzner is a shared server, not the main one.'), [])

    def test_stays_quiet_on_the_facts_file(self):
        self.assertEqual(wrong_claims(DOCS.read_text()), [])


class EveryFileAgrees(unittest.TestCase):
    def test_no_loaded_file_carries_a_wrong_claim(self):
        found = []
        for path in repo_files():
            found.extend(scan_text(str(path.relative_to(ROOT)),
                                   path.read_text(encoding='utf-8', errors='replace')))
        self.assertEqual(found, [], 'old server wording came back:\n' + '\n'.join(found))

    def test_installed_reference_notes_carry_no_wrong_claim(self):
        found = []
        checked = []
        for directory in reference_dirs():
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob('*.md')):
                checked.append(str(path))
                found.extend(scan_text(str(path),
                                       path.read_text(encoding='utf-8', errors='replace')))
        self.assertEqual(found, [], 'an installed reference note is wrong:\n' + '\n'.join(found))

    def test_the_scan_reaches_an_installed_note(self):
        # CI has no ~/.claude/reference; this proves the scan covers that folder.
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / 'tools.md').write_text('# old notes\n' + OLD_NOTES.read_text())
            found = []
            for note in sorted(directory.glob('*.md')):
                found.extend(scan_text(note.name, note.read_text()))
            self.assertEqual(len(found), 3, found)

    def test_the_override_directory_wins(self):
        override = os.environ.get('VSTACK_REFERENCE_DIR')
        self.addCleanup(os.environ.pop, 'VSTACK_REFERENCE_DIR', None)
        os.environ['VSTACK_REFERENCE_DIR'] = '/tmp/example-reference'
        self.assertEqual(reference_dirs()[0], Path('/tmp/example-reference'))
        if override is not None:
            os.environ['VSTACK_REFERENCE_DIR'] = override


class DocsAndJsonAgree(unittest.TestCase):
    def setUp(self):
        self.facts = json.loads(FACTS.read_text())
        self.docs = DOCS.read_text()
        self.sections = {}
        for part in re.split(r'^## ', self.docs, flags=re.M)[1:]:
            title, _, body = part.partition('\n')
            self.sections[title.strip()] = body

    def section(self, server_id):
        for title, body in self.sections.items():
            if title.lower().startswith(server_id.lower()):
                return title, body
        self.fail('docs/servers.md has no section for %r' % server_id)

    def test_every_server_in_the_json_has_a_section(self):
        matched = set()
        for server in self.facts['servers']:
            title, _ = self.section(server['id'])
            matched.add(title)
        self.assertEqual(len(matched), len(self.facts['servers']),
                         'two servers share one section heading')

    def test_no_section_documents_a_server_the_json_lacks(self):
        ids = [server['id'].lower() for server in self.facts['servers']]
        for title in self.sections:
            with self.subTest(section=title):
                if title.lower() == 'reading it':
                    continue
                self.assertTrue(any(title.lower().startswith(i) for i in ids),
                                'docs/servers.md documents %r but the json does not' % title)

    def test_ip_hostname_users_and_aliases_match(self):
        for server in self.facts['servers']:
            title, body = self.section(server['id'])
            text = title + '\n' + body
            with self.subTest(server=server['id']):
                self.assertIn(server['ip'], text)
                self.assertIn(server['hostname'], text)
                if server.get('previous_hostname'):
                    self.assertIn(server['previous_hostname'], text)
                for user in server['users']:
                    self.assertIn('`%s`' % user, text)
                for alias in server['reaches_other_with']:
                    self.assertIn(alias, text)
                for run in server.get('valentin_runs', []):
                    self.assertIn(run, text)

    def test_the_role_word_matches(self):
        for server in self.facts['servers']:
            title, body = self.section(server['id'])
            with self.subTest(server=server['id']):
                self.assertIn('%s server' % server['role'], (title + body).lower())

    def test_one_main_server(self):
        mains = [server['id'] for server in self.facts['servers']
                 if server['role'] == 'main']
        self.assertEqual(mains, [self.facts['main_server']])

    def test_docs_point_at_the_json_twin(self):
        self.assertIn('config/servers.json', self.docs)

    def test_agent_account_is_a_todo(self):
        hetzner = next(s for s in self.facts['servers'] if s['id'] == 'hetzner')
        self.assertIn('agent', hetzner['users'])
        self.assertIn('TODO', hetzner['agent'])
        self.assertIn('TODO', self.section('hetzner')[1])


class InstallPutsItWhereChatsLook(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.env = {key: value for key, value in os.environ.items()
                    if key not in ('VSTACK_DIR', 'VSTACK_INSTALL_ANYWHERE',
                                   'VSTACK_REFERENCE_DIR')}
        self.env['HOME'] = str(self.home)
        self.env['VSTACK_INSTALL_ANYWHERE'] = '1'
        self.env['VSTACK_DIR'] = str(self.home / '.local' / 'share' / 'vstack')

    def install(self):
        return subprocess.run(['bash', str(INSTALL)], env=self.env, text=True,
                              capture_output=True)

    def test_install_links_the_facts_file_twice_over(self):
        for run in (1, 2):
            result = self.install()
            self.assertEqual(result.returncode, 0, result.stderr)
            for name, source in (('servers.md', DOCS), ('servers.json', FACTS)):
                installed = self.home / '.claude' / 'reference' / name
                with self.subTest(run=run, file=name):
                    self.assertTrue(installed.exists(), result.stderr)
                    self.assertEqual(installed.read_text(), source.read_text())

    def test_a_plain_copy_is_replaced_by_the_linked_one(self):
        reference = self.home / '.claude' / 'reference'
        reference.mkdir(parents=True)
        (reference / 'servers.md').write_text('# stale hand-written copy\n')
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(DOCS.read_text(), (reference / 'servers.md').read_text())
        self.assertIn('servers.md', result.stderr,
                      'install should say it moved the stale copy')


if __name__ == '__main__':
    unittest.main()
