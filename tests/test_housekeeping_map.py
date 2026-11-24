from pathlib import Path
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAP_JSON = ROOT / 'docs' / 'housekeeping-map.json'
MAP_MD = ROOT / 'docs' / 'housekeeping-map.md'


def load():
    return json.loads(MAP_JSON.read_text())


def md_text():
    return MAP_MD.read_text()


def map_rows(md):
    """The rows of the one table under '## The map', header keyed."""
    section = md.split('## The map', 1)[1].split('\n---', 1)[0]
    lines = [line for line in section.splitlines() if line.startswith('|')]
    header = [cell.strip() for cell in lines[0].strip('|').split('|')]
    rows = []
    for line in lines[2:]:
        cells = [cell.strip() for cell in line.strip('|').split('|')]
        rows.append(dict(zip(header, cells)))
    return rows


def declared_counts(md):
    line = re.search(r'Verdict counts: \*\*(.+?)\*\*', md).group(1)
    counts = {}
    for part in line.split(','):
        verdict, number = part.strip().rsplit(' ', 1)
        counts[verdict] = int(number)
    return counts


def counted(verdicts):
    counts = {}
    for verdict in verdicts:
        counts[verdict] = counts.get(verdict, 0) + 1
    return counts


class HousekeepingMapTests(unittest.TestCase):
    def setUp(self):
        self.data = load()
        self.md = md_text()
        self.rows = map_rows(self.md)
        self.items = self.data['items']

    def test_verdict_counts_match_the_table_and_the_json(self):
        table = counted(row['Verdict'].split(',')[0].strip() for row in self.rows)
        items = counted(item['verdict'] for item in self.items)
        self.assertEqual(len(self.rows), len(self.items),
                         'map table and json must hold the same number of rows')
        self.assertEqual(table, items, 'map table verdicts disagree with the json')
        self.assertEqual(table, self.data['verdict_counts'],
                         'json verdict_counts disagree with its own rows')
        self.assertEqual(table, declared_counts(self.md),
                         'the stated verdict counts disagree with the map table')

    def test_each_row_keeps_its_verdict_between_json_and_table(self):
        for row, item in zip(self.rows, self.items):
            self.assertEqual(row['Verdict'].split(',')[0].strip(), item['verdict'],
                             item['id'])

    def test_every_reclaimable_figure_fits_inside_its_size(self):
        measured = [entry for entry in self.data['disk']['reclaimable']
                    if 'reclaimable_mb' in entry]
        self.assertTrue(measured, 'no reclaimable figures to check')
        for entry in measured:
            self.assertLessEqual(entry['reclaimable_mb'], entry['size_mb'], entry['target'])

    def test_every_parent_is_at_least_as_big_as_its_listed_children(self):
        for entry in self.data['disk']['reclaimable']:
            children = entry.get('children', [])
            if not children:
                continue
            self.assertIn('size_mb', entry, entry['target'])
            total = sum(child['size_mb'] for child in children)
            self.assertGreaterEqual(entry['size_mb'], total,
                                    f"{entry['target']} {entry['size']} is smaller than "
                                    f"its children {total}M")

    def test_every_disk_figure_in_the_json_is_printed_in_the_page(self):
        for entry in self.data['disk']['reclaimable']:
            if 'size' in entry and entry['size']:
                self.assertIn(entry['size'], self.md, entry['target'])
            for child in entry.get('children', []):
                self.assertIn(child['size'], self.md, child['target'])

    def test_docker_reclaimable_total_matches_its_parts(self):
        docker = [entry for entry in self.data['disk']['reclaimable']
                  if 'reclaimable_mb' in entry]
        self.assertEqual(sum(entry['reclaimable_mb'] for entry in docker),
                         self.data['disk']['docker_reclaimable_total_mb'])

    def test_every_delete_row_appears_in_the_archive_step(self):
        deletes = [item for item in self.items if item['verdict'] == 'DELETE']
        self.assertTrue(deletes, 'no DELETE rows to check')
        step = [entry for entry in self.data['migration_order'] if entry['step'] == 10]
        self.assertEqual(len(step), 1, 'migration step 10 must exist once')
        archived = set(step[0]['archives'])
        self.assertEqual({item['archive_key'] for item in deletes}, archived,
                         'every DELETE row must be named in the archive step')
        block = re.search(r'^10\. \*\*.*?(?=^11\.)', self.md, re.S | re.M).group(0)
        for item in deletes:
            for name in item['archive_names']:
                self.assertIn(name, block, f'{item["id"]} is not listed in migration step 10')

    def test_no_central_timer_or_instance_is_planned(self):
        self.assertFalse(self.data['run_model']['central_timer'])
        self.assertFalse(self.data['run_model']['central_instance'])
        self.assertNotIn('vps-tidy.timer', self.md)
        self.assertNotIn('one systemd user timer', self.md.lower())


if __name__ == '__main__':
    unittest.main()
