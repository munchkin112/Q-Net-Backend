"""원본 누락·변조를 막고 실패와 정상 자료를 구분해 보관하는지 검사한다."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib

from research.apply_preparation import read_verified_response, prepare_sources


class SourceStorageTests(unittest.TestCase):
    def test_windows_newlines_preserve_response_content(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'response.txt').write_bytes(b'first\r\nsecond')
            attempt = {'response_file': 'response.txt',
                       'sha256': hashlib.sha256(b'first\nsecond').hexdigest()}
            self.assertEqual(read_verified_response(root, attempt), 'first\r\nsecond')

    def test_modified_response_is_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'response.txt').write_text('changed', encoding='utf-8')
            attempt = {'response_file': 'response.txt',
                       'sha256': hashlib.sha256(b'original').hexdigest()}
            with self.assertRaises(ValueError):
                read_verified_response(root, attempt)

    def test_missing_response_is_rejected(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                read_verified_response(Path(directory), {'response_file': 'missing.txt', 'sha256': 'x'})

    def test_collected_sources_keep_states_and_raw_bodies(self):
        rows = prepare_sources()
        self.assertEqual(len(rows), 137)
        details = [row for row in rows if row['kind'] == 'details']
        self.assertEqual({state: sum(row['status'] == state for row in details)
                          for state in ('fetched', 'empty', 'failed')},
                         {'fetched': 56, 'empty': 36, 'failed': 8})
        self.assertTrue(all(row['payload']['raw_responses'] for row in rows if row['status'] == 'fetched'))
        self.assertEqual(sum(len(row['payload']['schedule_candidates']) for row in rows), 72)


if __name__ == '__main__':
    unittest.main()
