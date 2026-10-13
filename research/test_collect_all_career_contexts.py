"""전체 수집에서 빈 페이지·다른 종목·통계 오염을 성공으로 처리하지 않는다."""
import unittest
from research.collect_all_career_contexts import validate_career_content


class CareerValidationTests(unittest.TestCase):
    def test_wrong_name_is_not_success(self):
        status,_,_=validate_career_content('다른자격 개요',{'overview':'내용'},'표본자격')
        self.assertEqual(status,'identity_not_confirmed')

    def test_empty_sections_are_not_success(self):
        status,_,_=validate_career_content('표본자격',{'overview':None,'duties':None,'career':None},'표본자격')
        self.assertEqual(status,'empty')

    def test_statistics_are_review_required(self):
        status,_,_=validate_career_content('표본자격',{'duties':'관리 업무 합격률 90%'},'표본자격')
        self.assertEqual(status,'needs_content_review')

    def test_family_name_is_not_exact_identity(self):
        status,_,_=validate_career_content('통역안내 개요',{'overview':'여행 안내'},'통역안내(영어)')
        self.assertEqual(status,'needs_content_review')

    def test_verified_wrapper_allows_body_without_name(self):
        status,_,identity=validate_career_content('수행직무 시설 관리',{'duties':'시설 관리'},'표본자격', identity_confirmed=True)
        self.assertEqual(status,'fetched')
        self.assertEqual(identity,'official_wrapper_code_and_name')

    def test_duties_about_statistics_are_not_exam_statistics(self):
        status,_,_=validate_career_content('표본자격',{'duties':'수도 관련 통계자료의 관리'},'표본자격')
        self.assertEqual(status,'fetched')

    def test_confirmed_identity_does_not_make_empty_success(self):
        status,_,_=validate_career_content('기본 정보가 없습니다.',{'duties':None},'표본자격',identity_confirmed=True)
        self.assertEqual(status,'empty')

    def test_clean_real_content_is_collected_not_reviewed(self):
        status,_,_=validate_career_content('표본자격 수행직무',{'duties':'시설 유지관리'},'표본자격')
        self.assertEqual(status,'fetched')


if __name__=='__main__':
    unittest.main()
