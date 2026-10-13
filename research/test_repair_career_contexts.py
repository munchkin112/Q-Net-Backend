"""공식 코드·이름으로만 식별하고 메뉴에 나타난 이름은 인정하지 않는다."""
import unittest
from research.repair_career_contexts import validate_certificate_identity

class IdentityTests(unittest.TestCase):
    def test_both_code_and_name_are_required(self):
        html='<input id="jmCd" value="1234"><input id="jmNm" value="표본자격">'
        self.assertTrue(validate_certificate_identity(html,'1234','표본자격'))
        self.assertFalse(validate_certificate_identity(html,'9999','표본자격'))
        self.assertFalse(validate_certificate_identity(html,'1234','다른자격'))

    def test_menu_name_does_not_identify_selected_certificate(self):
        html='<a>표본자격</a><input id="jmCd" value="1234"><input id="jmNm" value="다른자격">'
        self.assertFalse(validate_certificate_identity(html,'1234','표본자격'))

if __name__ == '__main__':
    unittest.main()
