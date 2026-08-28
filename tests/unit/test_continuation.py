from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from legacy_crawler.continuation import ContinuationState, ContinuationStore


class ContinuationStoreTests(unittest.TestCase):
    def test_round_trip_replaces_cursor_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = ContinuationStore(Path(temp) / "records_continuation.json")
            first = ContinuationState(
                cursor="cursor-a",
                checkpoint="checkpoint-a",
                dataset_id="dataset",
                released_rows=1000,
                next_refresh_at="2026-08-28T10:03:00+09:00",
                has_more=True,
            )
            second = ContinuationState(
                cursor="cursor-b",
                checkpoint="checkpoint-a",
                dataset_id="dataset",
                released_rows=1000,
                next_refresh_at="2026-08-28T10:03:00+09:00",
                has_more=False,
            )
            store.save(first)
            self.assertEqual(store.load(), first)
            store.save(second)
            self.assertEqual(store.load(), second)
            self.assertFalse(store.path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
