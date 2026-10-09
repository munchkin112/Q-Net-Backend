"""직무 구간에 통계·기관 정보가 섞이지 않는지 검증한다."""
import unittest
from research.collect_career_samples import extract_career_sections


class CareerSectionTests(unittest.TestCase):
    def test_ministry_and_statistics_end_duties(self):
        html = '<p>수행직무</p><p>표본자격 수행직무</p><p>설비를 관리한다.</p><p>소관부처명</p><p>기관명</p><p>통계자료</p><p>합격률 99%</p>'
        _, sections = extract_career_sections(html, '표본자격')
        self.assertEqual(sections['duties'], '설비를 관리한다.')
        self.assertNotIn('합격률', sections['duties'])

    def test_missing_duties_remains_none(self):
        html = '<p>개요</p><p>정보 처리 설명</p><p>진로 및 전망</p><p>시스템 운영 업무</p>'
        _, sections = extract_career_sections(html, '표본자격')
        self.assertIsNone(sections['duties'])
        self.assertEqual(sections['career'], '시스템 운영 업무')

    def test_encoded_html_and_script_are_not_evidence(self):
        html = '<p>수행직무</p>&lt;p&gt;시설 유지관리&lt;/p&gt;<script>거짓 직업</script><p>종목별 검정현황</p><p>통계</p>'
        _, sections = extract_career_sections(html, '표본자격')
        self.assertEqual(sections['duties'], '시설 유지관리')


if __name__ == '__main__':
    unittest.main()
