from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from legacy_crawler.logging_config import StructuredRunLogger, mask_value
from legacy_crawler.publisher import PublishingError, RunLock
from legacy_crawler.scheduler import calculate_next_run


class SchedulerAndLoggingTests(unittest.TestCase):
    def test_second_concurrent_run_lock_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            lock_path = Path(temp) / "crawler.lock"
            first = RunLock(lock_path, run_id="first")
            second = RunLock(lock_path, run_id="second")
            first.acquire()
            try:
                with self.assertRaises(PublishingError):
                    second.acquire()
            finally:
                first.release()
            self.assertFalse(lock_path.exists())

    def test_next_refresh_uses_server_offset_and_five_second_delay(self) -> None:
        schedule = calculate_next_run(
            server_time="2026-08-27T10:00:10+09:00",
            next_refresh_at="2026-08-27T10:03:00+09:00",
            safety_delay_seconds=5,
            observed_local_time=datetime.fromisoformat("2026-08-27T10:00:00+09:00"),
        )
        self.assertEqual(
            schedule.source_target_time.isoformat(), "2026-08-27T10:03:05+09:00"
        )
        self.assertEqual(
            schedule.local_run_time.isoformat(), "2026-08-27T10:02:55+09:00"
        )
        self.assertEqual(schedule.clock_offset_seconds, 10)

    def test_structured_log_masks_secret_keys_and_values(self) -> None:
        self.assertEqual(mask_value({"api_key": "secret"}), {"api_key": "***REDACTED***"})
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            logger = StructuredRunLogger(
                log_root=Path(temp), run_id="run", source_name="source"
            )
            logger.register_secret("super-secret-value")
            logger.event(
                stage="test",
                event="mask",
                status="error",
                error="failed with super-secret-value",
                headers={"X-API-Key": "super-secret-value"},
            )
            line = logger.normal_path.read_text(encoding="utf-8").splitlines()[-1]
            record = json.loads(line)
            self.assertNotIn("super-secret-value", line)
            self.assertEqual(record["headers"]["X-API-Key"], "***REDACTED***")
            self.assertIn("***REDACTED***", record["error"])


if __name__ == "__main__":
    unittest.main()
