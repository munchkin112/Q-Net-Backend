"""다른 종목의 인용과 근거 없는 직업명이 승인되지 않는지 검사한다."""
import copy
import unittest

from research.review_related_jobs import validate_roles, validate_audit, get_literal_quote


class RelatedJobReviewTests(unittest.TestCase):
    def setUp(self):
        self.item = {'qnet_code': '1320', 'documents': [
            {'document_id': 'qnet:1320:duties', 'content': '소프트웨어 설계 및 개발 업무를 수행한다.'}]}
        self.review = {'qnet_code': '1320', 'roles': [
            {'name': '소프트웨어 개발 담당', 'document_id': 'qnet:1320:duties',
             'quote': '소프트웨어 설계 및 개발 업무', 'source_phrase': '개발 업무'}], 'reason': ''}

    def test_owned_literal_evidence_is_required(self):
        self.assertEqual(validate_roles(self.item, self.review), [])
        for key, value in [('document_id', 'qnet:1021:duties'), ('quote', '취업이 보장된다'),
                           ('source_phrase', '법률 상담'), ('name', '취업 보장 개발자')]:
            review = copy.deepcopy(self.review)
            review['roles'][0][key] = value
            self.assertTrue(validate_roles(self.item, review))

    def test_empty_review_needs_explanation_and_duplicates_are_rejected(self):
        self.assertTrue(validate_roles(self.item, {'qnet_code': '1320', 'roles': [], 'reason': ''}))
        self.assertEqual(validate_roles(self.item, {'qnet_code': '1320', 'roles': [], 'reason': '업무 근거 부족'}), [])
        review = copy.deepcopy(self.review)
        review['roles'].append(review['roles'][0])
        self.assertTrue(validate_roles(self.item, review))

    def test_audit_must_cover_every_role_and_explicitly_support_it(self):
        audit = {'qnet_code': '1320', 'roles': [{'index': 0, 'supported': True, 'reason': '설계·개발 업무'}]}
        self.assertEqual(validate_audit(self.review, audit), [])
        audit['roles'][0]['supported'] = 'true'
        self.assertTrue(validate_audit(self.review, audit))
        audit['roles'] = []
        self.assertTrue(validate_audit(self.review, audit))

    def test_restore_whitespace_only_without_rewriting_words(self):
        self.assertEqual(get_literal_quote('소프트웨어 개발', '소프트웨어\n개발 업무'), '소프트웨어\n개발')
        self.assertIsNone(get_literal_quote('소프트웨어 설계', '소프트웨어\n개발 업무'))


if __name__ == '__main__':
    unittest.main()
