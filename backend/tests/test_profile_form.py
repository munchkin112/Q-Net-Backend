import unittest

from pydantic import ValidationError

from backend.profile_form import ProfileForm


class ProfileFormTests(unittest.TestCase):
    def sample(self, **changes):
        values = dict(interest_category_codes=['20'], education_level='university',
                      education_status='graduated', has_career=False, career_years=None)
        return ProfileForm(**{**values, **changes})

    def test_optional_major_and_no_desired_job(self):
        profile = self.sample()
        self.assertIsNone(profile.major)
        self.assertEqual(profile.interest_category_codes, ['20'])

    def test_exactly_one_known_interest(self):
        for codes in ([], ['20', '19'], ['25']):
            with self.subTest(codes=codes), self.assertRaises(ValidationError):
                self.sample(interest_category_codes=codes)

    def test_education_and_status_use_options(self):
        for changes in ({'education_level': 'typed value'}, {'education_status': ''}):
            with self.assertRaises(ValidationError):
                self.sample(**changes)

    def test_career_years_required_only_with_career(self):
        with self.assertRaises(ValidationError):
            self.sample(has_career=True)
        self.assertEqual(self.sample(has_career=True, career_years=0.5).career_years, 0.5)
        with self.assertRaises(ValidationError):
            self.sample(career_years=3)

    def test_invalid_years_and_extra_fields_rejected(self):
        for years in (-1, 81, float('nan'), True):
            with self.subTest(years=years), self.assertRaises(ValidationError):
                self.sample(has_career=True, career_years=years)
        with self.assertRaises(ValidationError):
            self.sample(user_id='someone-else')


if __name__ == '__main__':
    unittest.main()
