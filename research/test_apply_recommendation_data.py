"""승인되지 않은 자료와 잘못 연결된 근거가 DB 입력으로 넘어가지 않는지 검사한다."""
import copy
import json
import unittest
from pathlib import Path

from research.apply_recommendation_data import prepare_recommendation_data

DATA = Path(__file__).parent / 'preparation/recommendation'


class RecommendationDataTests(unittest.TestCase):
    def setUp(self):
        self.approved = json.loads((DATA / 'reviewed_recommendation_contexts.json').read_text(encoding='utf-8'))
        self.original = json.loads((DATA / 'candidate_contexts.json').read_text(encoding='utf-8'))
        self.interests = json.loads((DATA / 'interest_categories.json').read_text(encoding='utf-8'))

    def test_only_reviewed_data_and_owned_role_evidence(self):
        rows, interests = prepare_recommendation_data(self.approved, self.original, self.interests)
        self.assertEqual(len(rows), 592)
        self.assertEqual(len(interests), 24)
        self.assertEqual(sum(len(row['payload']['related_jobs']) for row in rows), 13)
        row = next(row for row in rows if row['qnet_code'] == '1320')
        self.assertTrue(all(document['qnet_code'] == '1320' for document in row['payload']['evidence_documents']))
        self.assertEqual(rows, prepare_recommendation_data(self.approved, self.original, self.interests)[0])

    def test_reject_held_and_duplicate_candidates(self):
        for change in ['held', 'duplicate']:
            items = copy.deepcopy(self.approved)
            if change == 'held':
                items[0]['review_status'] = 'held'
            else:
                items.append(items[0])
            with self.assertRaises(ValueError):
                prepare_recommendation_data(items, self.original, self.interests)

    def test_reject_modified_source_and_foreign_role(self):
        originals = copy.deepcopy(self.original)
        originals[0]['career_evidence'][0]['content'] += '변경'
        with self.assertRaises(ValueError):
            prepare_recommendation_data(self.approved, originals, self.interests)
        items = copy.deepcopy(self.approved)
        row = next(row for row in items if row['qnet_code'] == '1320')
        row['related_jobs'][0]['source_ids'] = ['qnet:1021:duties']
        with self.assertRaises(ValueError):
            prepare_recommendation_data(items, self.original, self.interests)

    def test_reject_fixed_classification_and_invalid_choices(self):
        items = copy.deepcopy(self.approved)
        items[0]['interest_category_codes'] = ['01']
        with self.assertRaises(ValueError):
            prepare_recommendation_data(items, self.original, self.interests)
        with self.assertRaises(ValueError):
            prepare_recommendation_data(self.approved, self.original, self.interests[:-1])


if __name__ == '__main__':
    unittest.main()
