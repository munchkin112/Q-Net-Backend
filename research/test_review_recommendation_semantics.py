"""의미 검토에서 다른 종목·없는 근거·잘못된 분야가 승인되지 않는지 확인한다."""
import unittest

from research.review_recommendation_semantics import validate_review


class SemanticReviewTests(unittest.TestCase):
    def setUp(self):
        self.item = {'qnet_code': '1320', 'certificate_id': 'one', 'name': '정보처리기사'}
        self.documents = [{'document_id': 'd1', 'content': '소프트웨어를 개발하고 정보시스템을 운영한다.'}]
        self.review = {
            'qnet_code': '1320', 'summary': '소프트웨어 개발과 정보시스템 운영을 다룹니다.',
            'summary_evidence': [{'document_id': 'd1', 'quote': '소프트웨어를 개발하고 정보시스템을 운영한다.'}],
            'issues': [], 'interest_matches': [{'code': '20', 'document_id': 'd1', 'quote': '소프트웨어를 개발'}],
        }

    def test_exact_evidence_required(self):
        self.assertEqual(validate_review(self.item, self.documents, self.review), [])
        self.review['summary_evidence'][0]['quote'] = '취업을 보장한다'
        self.assertIn('summary_quote_missing', validate_review(self.item, self.documents, self.review))

    def test_other_certificate_and_interest_code_rejected(self):
        self.review['qnet_code'] = '9999'
        self.review['interest_matches'][0]['code'] = '25'
        errors = validate_review(self.item, self.documents, self.review)
        self.assertIn('certificate_code_mismatch', errors)
        self.assertIn('invalid_interest_code', errors)

    def test_empty_summary_needs_issue_and_cannot_claim_pass(self):
        self.review['summary'] = None
        self.review['summary_evidence'] = []
        self.assertIn('missing_summary_without_issue', validate_review(self.item, self.documents, self.review))

    def test_unknown_source_and_duplicate_matches_rejected(self):
        self.review['summary_evidence'][0]['document_id'] = 'other'
        self.review['interest_matches'].append(self.review['interest_matches'][0].copy())
        errors = validate_review(self.item, self.documents, self.review)
        self.assertIn('summary_source_missing', errors)
        self.assertIn('duplicate_interest_code', errors)


if __name__ == '__main__':
    unittest.main()
