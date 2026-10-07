import os
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from backend.schemas import CertificateInput, ProfilePatch, ScheduleInput, validate_profile_state


def sample_schedule(**changes) -> ScheduleInput:
    values = {
        "certificate_id": uuid4(), "year": 2026, "round_key": "2026-engineer-3",
        "round_label": "2026년 정기 기사 3회", "phase": "practical",
        "registration_start": "2026-09-21", "registration_end": "2026-09-28",
        "exam_start": "2026-10-24", "exam_end": "2026-11-13", "result_date": "2026-12-18",
        "source_url": "https://www.q-net.or.kr/", "last_synced_at": datetime.now(timezone.utc),
    }
    return ScheduleInput(**{**values, **changes})


class InputTests(unittest.TestCase):
    def test_optional_career_dates_and_qualifications(self):
        profile = ProfilePatch(career_history=[{"job_title": "안전관리"}], qualifications=[{"name": "보유 자격"}])
        self.assertIsNone(profile.career_history[0].started_on)
        self.assertIsNone(profile.qualifications[0].acquired_on)

    def test_patch_omission_and_clear_are_different(self):
        self.assertEqual(ProfilePatch().model_dump(exclude_unset=True), {})
        self.assertEqual(ProfilePatch(major=None).model_dump(exclude_unset=True), {"major": None})

    def test_no_career_is_not_missing(self):
        validate_profile_state({"has_career": False, "career_history": []})

    def test_career_conflict(self):
        with self.assertRaises(ValueError):
            validate_profile_state({"has_career": False, "career_history": [{"job_title": "개발"}]})

    def test_major_state_conflict(self):
        with self.assertRaises(ValueError):
            validate_profile_state({"major_status": "provided", "major": None})

    def test_reversed_career_dates(self):
        with self.assertRaises(ValidationError):
            ProfilePatch(career_history=[{"job_title": "개발", "started_on": "2026-10-05", "ended_on": "2025-01-01"}])

    def test_period_not_single_exam_date(self):
        schedule = sample_schedule()
        self.assertLess(schedule.exam_start, schedule.exam_end)

    def test_registration_after_exam(self):
        with self.assertRaises(ValidationError):
            sample_schedule(registration_end="2026-10-25")

    def test_result_before_exam_end(self):
        with self.assertRaises(ValidationError):
            sample_schedule(result_date="2026-11-12")

    def test_missing_dates_allowed_without_invention(self):
        schedule = sample_schedule(exam_start=None, exam_end=None, result_date=None)
        self.assertIsNone(schedule.exam_start)

    def test_timezone_required(self):
        with self.assertRaises(ValidationError):
            sample_schedule(last_synced_at=datetime(2026, 10, 5))

    def test_missing_end_does_not_hide_result_conflict(self):
        with self.assertRaises(ValidationError):
            sample_schedule(exam_end=None, result_date="2026-10-23")

    def test_missing_registration_end_does_not_hide_conflict(self):
        with self.assertRaises(ValidationError):
            sample_schedule(registration_start="2026-10-25", registration_end=None)

    def test_pending_features_not_accepted(self):
        with self.assertRaises(ValidationError):
            ProfilePatch(available_hours=10)


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "테스트 PostgreSQL 연결 정보 미제공")
class PostgreSQLTests(unittest.TestCase):
    def test_profile_patch_and_separate_phases(self):
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        from backend.db.repository import get_profile, list_schedules, save_profile, save_schedule, save_certificate, search_certificates

        user_id, certificate_id = uuid4(), uuid4()
        connection = psycopg.connect(os.environ["TEST_DATABASE_URL"], row_factory=dict_row, connect_timeout=10)
        try:
            schema_name = "test_qnet_" + uuid4().hex
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
            connection.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema_name)))
            connection.execute(Path(__file__).parents[1].joinpath("db/schema.sql").read_text(encoding="utf-8"))
            connection.execute("INSERT INTO users(id, provider, provider_subject_id) VALUES (%s, 'google', %s)", (user_id, str(user_id)))
            connection.execute("INSERT INTO certificates(id, qnet_code, name, category, source_url, last_synced_at) VALUES (%s, '1320', '정보처리기사', 'T', 'https://www.q-net.or.kr/', now())", (certificate_id,))
            catalog_item = CertificateInput(qnet_code="0752", name="가스기술사", category="T",
                                            source_url="https://www.q-net.or.kr/", last_synced_at=datetime.now(timezone.utc))
            catalog_saved = save_certificate(connection, catalog_item)
            connection.execute("UPDATE certificates SET career_tags = '[\"팀 태그\"]' WHERE id = %s", (catalog_saved["id"],))
            catalog_repeated = save_certificate(connection, catalog_item)
            self.assertEqual(catalog_saved["id"], catalog_repeated["id"])
            self.assertEqual(catalog_repeated["career_tags"], ["팀 태그"])
            self.assertEqual(search_certificates(connection, "가스", "T")[0]["qnet_code"], "0752")
            self.assertEqual(search_certificates(connection, "0752")[0]["id"], catalog_saved["id"])
            self.assertEqual(search_certificates(connection, "%"), [])
            self.assertEqual(search_certificates(connection, "가스", "S"), [])
            save_profile(connection, user_id, ProfilePatch(has_career=True, desired_job="안전관리", career_history=[{"job_title": "안전관리"}]))
            save_profile(connection, user_id, ProfilePatch(qualifications=[{"name": "자격증"}]))
            self.assertEqual(get_profile(connection, user_id)["desired_job"], "안전관리")
            with self.assertRaises(ValueError):
                save_profile(connection, user_id, ProfilePatch(has_career=False))
            self.assertTrue(get_profile(connection, user_id)["has_career"])
            practical = sample_schedule(certificate_id=certificate_id)
            first = save_schedule(connection, practical)
            repeated = save_schedule(connection, practical)
            self.assertEqual(first["id"], repeated["id"])
            save_schedule(connection, sample_schedule(certificate_id=certificate_id, phase="written"))
            self.assertEqual(len(list_schedules(connection, certificate_id, 2026)), 2)
            old = practical.model_copy(update={"last_synced_at": datetime(2020, 1, 1, tzinfo=timezone.utc), "exam_site": "stale"})
            self.assertIsNone(save_schedule(connection, old)["exam_site"])
            save_profile(connection, user_id, ProfilePatch(career_history=None, has_career=False))
            self.assertEqual(get_profile(connection, user_id)["career_history"], [])
            # Ensure dates are real DATE columns, not a lossy single-date projection.
            self.assertEqual(first["exam_end"], date(2026, 11, 13))
        finally:
            connection.rollback()
            connection.close()


if __name__ == "__main__":
    unittest.main()
