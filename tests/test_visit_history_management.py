import importlib.util
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path


# NAS 호스트에는 BeautifulSoup 패키지가 없을 수 있으므로,
# 방문기록 DB 로직 테스트에서는 import만 통과하도록 최소 대체 모듈을 사용한다.
if "bs4" not in sys.modules:
    fake_bs4 = types.ModuleType("bs4")
    fake_bs4.BeautifulSoup = lambda *args, **kwargs: None
    sys.modules["bs4"] = fake_bs4


PLUGIN_DIR = Path(__file__).resolve().parents[1]
SOURCE_PATH = PLUGIN_DIR / "source_naverpaper.py"
spec = importlib.util.spec_from_file_location("ff_naverpaper_source_test", SOURCE_PATH)
np = importlib.util.module_from_spec(spec)
# Python 3.8 dataclass가 동적 모듈의 타입 정보를 조회할 수 있도록 먼저 등록한다.
sys.modules[spec.name] = np
spec.loader.exec_module(np)


class VisitHistoryManagementTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp.name, "naverpaper.sqlite")
        self.backup_dir = os.path.join(self.temp.name, "backup")
        self.db = np.Database(self.db_path)
        self.db.create_all()

        base = datetime(2026, 9, 22, 10, 0, 0)
        with self.db.get_session() as session:
            urls = ["bad1", "bad2", "terminal", "good", "other"]
            for name in urls:
                session.add(np.CampaignUrl(url=f"https://example.com/{name}", is_available=True))

            # 프로필2 실패 실행: 방문 0 / 적립 0인데 과거 버그로 방문기록 2건이 저장된 상황.
            bad_run = np.RunHistory(
                started_at=base,
                finished_at=base + timedelta(minutes=10),
                status="completed",
                account_count=1,
            )
            session.add(bad_run)
            session.flush()
            session.add(
                np.RunAccountSummary(
                    run_id=bad_run.id,
                    user_id="profile2",
                    target_url_count=2,
                    skipped_url_count=2,
                    visited_url_count=0,
                    estimated_points=0,
                    detail_count=1,
                )
            )
            session.add(
                np.RunDetail(
                    run_id=bad_run.id,
                    user_id="profile2",
                    url="https://example.com/bad1",
                    status="skipped",
                    point=0,
                    message="redirected to Naver login",
                    created_at=base + timedelta(minutes=5),
                )
            )
            session.add_all(
                [
                    np.UrlVisit(
                        url="https://example.com/bad1",
                        user_id="profile2",
                        visited_at=base + timedelta(minutes=5),
                    ),
                    np.UrlVisit(
                        url="https://example.com/bad2",
                        user_id="profile2",
                        visited_at=base + timedelta(minutes=6),
                    ),
                ]
            )

            # "이미 1회 적립됨"은 방문 0/적립 0이어도 정상 종결 기록이므로 복구 대상에서 제외한다.
            terminal_start = base + timedelta(hours=1)
            terminal_run = np.RunHistory(
                started_at=terminal_start,
                finished_at=terminal_start + timedelta(minutes=10),
                status="completed",
                account_count=1,
            )
            session.add(terminal_run)
            session.flush()
            session.add(
                np.RunAccountSummary(
                    run_id=terminal_run.id,
                    user_id="profile2",
                    target_url_count=1,
                    skipped_url_count=1,
                    visited_url_count=0,
                    estimated_points=0,
                    detail_count=1,
                )
            )
            session.add(
                np.RunDetail(
                    run_id=terminal_run.id,
                    user_id="profile2",
                    url="https://example.com/terminal",
                    status="skipped",
                    point=0,
                    message="already received once",
                    created_at=terminal_start + timedelta(minutes=5),
                )
            )
            session.add(
                np.UrlVisit(
                    url="https://example.com/terminal",
                    user_id="profile2",
                    visited_at=terminal_start + timedelta(minutes=5),
                )
            )

            # 정상 적립 실행의 방문기록도 복구 대상에서 제외한다.
            good_start = base + timedelta(hours=2)
            good_run = np.RunHistory(
                started_at=good_start,
                finished_at=good_start + timedelta(minutes=10),
                status="completed",
                account_count=1,
            )
            session.add(good_run)
            session.flush()
            session.add(
                np.RunAccountSummary(
                    run_id=good_run.id,
                    user_id="profile2",
                    target_url_count=1,
                    skipped_url_count=0,
                    visited_url_count=1,
                    estimated_points=5,
                    detail_count=1,
                )
            )
            session.add(
                np.RunDetail(
                    run_id=good_run.id,
                    user_id="profile2",
                    url="https://example.com/good",
                    status="visited",
                    point=5,
                    message="ok",
                    created_at=good_start + timedelta(minutes=5),
                )
            )
            session.add(
                np.UrlVisit(
                    url="https://example.com/good",
                    user_id="profile2",
                    visited_at=good_start + timedelta(minutes=5),
                )
            )

            # 프로필1 데이터는 어떤 프로필2 작업에서도 삭제되면 안 된다.
            other_start = base + timedelta(hours=3)
            other_run = np.RunHistory(
                started_at=other_start,
                finished_at=other_start + timedelta(minutes=10),
                status="completed",
                account_count=1,
            )
            session.add(other_run)
            session.flush()
            session.add(
                np.RunAccountSummary(
                    run_id=other_run.id,
                    user_id="profile1",
                    target_url_count=1,
                    skipped_url_count=1,
                    visited_url_count=0,
                    estimated_points=0,
                    detail_count=0,
                )
            )
            session.add(
                np.UrlVisit(
                    url="https://example.com/other",
                    user_id="profile1",
                    visited_at=other_start + timedelta(minutes=5),
                )
            )

    def tearDown(self):
        self.temp.cleanup()

    def _visit_count(self, user_id):
        with self.db.get_session() as session:
            return session.query(np.UrlVisit).filter_by(user_id=user_id).count()

    def test_preview_filters_only_error_candidates(self):
        preview = np.visit_history_preview(self.db_path, "profile2")
        self.assertEqual(preview["total_count"], 4)
        self.assertEqual(preview["recovery_count"], 2)
        self.assertEqual(preview["recovery_by_date"], [{"date": "2026-09-22", "count": 2}])
        self.assertEqual(np.visit_history_preview(self.db_path, "profile1")["recovery_count"], 1)

    def test_recovery_keeps_normal_and_other_profile_records(self):
        progress = []
        result = np.reset_visit_history(
            self.db_path,
            "profile2",
            "recovery",
            self.backup_dir,
            progress=lambda percent, message: progress.append((percent, message)),
        )

        self.assertEqual(result["target_count"], 2)
        self.assertEqual(result["deleted_count"], 2)
        self.assertTrue(os.path.exists(result["backup_path"]))
        self.assertEqual(self._visit_count("profile2"), 2)
        self.assertEqual(self._visit_count("profile1"), 1)
        self.assertEqual(np.visit_history_preview(self.db_path, "profile2")["recovery_count"], 0)
        self.assertIn(100, [row[0] for row in progress])

        # 백업에는 삭제 전 프로필2 방문기록 4건이 그대로 있어야 한다.
        import sqlite3

        con = sqlite3.connect(result["backup_path"])
        try:
            backup_count = con.execute(
                "SELECT COUNT(*) FROM url_visits WHERE user_id=?", ("profile2",)
            ).fetchone()[0]
        finally:
            con.close()
        self.assertEqual(backup_count, 4)

    def test_full_reset_deletes_only_selected_profile(self):
        result = np.reset_visit_history(
            self.db_path,
            "profile2",
            "all",
            self.backup_dir,
        )
        self.assertEqual(result["deleted_count"], 4)
        self.assertEqual(self._visit_count("profile2"), 0)
        self.assertEqual(self._visit_count("profile1"), 1)
        self.assertTrue(os.path.exists(result["backup_path"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
