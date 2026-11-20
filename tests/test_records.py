import unittest

from record_reader import read_records


class RecordsTest(unittest.TestCase):
    def setUp(self):
        self.tables = read_records()

    def references(self, left, left_key, right, right_key):
        candidates = {row[right_key] for row in self.tables[right]}
        self.assertTrue(all(row[left_key] in candidates for row in self.tables[left]))

    def test_documents_reference_source_records(self):
        self.references('offers','group','groups','group')
        self.references('offers','student','applications','student')
        self.references('confirmations','group','groups','group')
        self.assertTrue(any(len(row['groups']) > 1 for row in self.tables['closures']))
        group = {row['group']: row for row in self.tables['groups']}
        self.assertTrue(all(set(row['accepted_groups']) <= set(group) for row in self.tables['applications']))
        self.assertEqual(group['g1']['equipment'], group['g2']['equipment'])
        self.assertLess(group['g2']['start'], group['g1']['end'])
        self.assertTrue(any(row['equipment']==group['g3']['equipment'] and row['day']==group['g3']['day']
            for row in self.tables['outages']))
