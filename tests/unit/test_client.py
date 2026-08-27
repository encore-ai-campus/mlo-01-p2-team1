from __future__ import annotations

import json
import unittest
from urllib.request import Request

from legacy_crawler.client import (
    BronzeRelayClient,
    HttpBody,
    IncompleteCollectionError,
    collection_failure_status,
)
from legacy_crawler.config import Settings


def settings(**overrides: str) -> Settings:
    values = {
        "CRAWLER_MAX_RETRIES": "2",
        "CRAWLER_BACKOFF_BASE_SECONDS": "1",
        "CRAWLER_BACKOFF_MAX_SECONDS": "4",
        "CRAWLER_JITTER_MAX_SECONDS": "0",
    }
    values.update(overrides)
    return Settings.from_env(values)


def response(payload: object, *, status: int = 200) -> HttpBody:
    return HttpBody(
        status=status,
        headers={"content-type": "application/json; charset=utf-8"},
        body=json.dumps(payload, separators=(",", ":")).encode(),
    )


class QueueTransport:
    def __init__(self, responses: list[HttpBody]) -> None:
        self.responses = responses
        self.requests: list[Request] = []

    def __call__(self, request: Request, timeout: int) -> HttpBody:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected transport call")
        return self.responses.pop(0)


class BronzeRelayClientTests(unittest.TestCase):
    def test_metadata_resolves_only_exact_named_dataset(self) -> None:
        metadata = {
            "datasets": [
                {"dataset_id": "other", "name": "other"},
                {
                    "dataset_id": "target-id",
                    "dataset_name": "biz_legacy_integrated",
                },
            ]
        }
        self.assertEqual(
            BronzeRelayClient.resolve_dataset_id(
                metadata, source_name="biz_legacy_integrated"
            ),
            "target-id",
        )

    def test_signed_cursor_paginates_until_has_more_false(self) -> None:
        page_one = {
            "items": [{"record_id": 1}],
            "count": 1,
            "has_more": True,
            "next_cursor": "signed cursor/one",
        }
        page_two = {
            "items": [{"record_id": 2}],
            "count": 1,
            "has_more": False,
            "next_cursor": None,
        }
        transport = QueueTransport([response(page_one), response(page_two)])
        client = BronzeRelayClient(settings(), transport=transport)

        pages = list(client.iter_record_pages(dataset_id="dataset", api_key="secret"))

        self.assertEqual([page.number for page in pages], [1, 2])
        self.assertEqual(pages[0].response.body, response(page_one).body)
        self.assertIn("cursor=signed+cursor%2Fone", transport.requests[1].full_url)
        self.assertNotIn("secret", transport.requests[0].full_url)

    def test_retry_is_bounded_and_uses_backoff(self) -> None:
        ok_page = {
            "items": [],
            "count": 0,
            "has_more": False,
            "next_cursor": None,
        }
        transport = QueueTransport(
            [response({}, status=503), response({}, status=503), response(ok_page)]
        )
        delays: list[float] = []
        client = BronzeRelayClient(
            settings(), transport=transport, sleep=delays.append
        )

        page = next(client.iter_record_pages(dataset_id="dataset", api_key="secret"))

        self.assertEqual(page.response.retry_count, 2)
        self.assertEqual(delays, [1.0, 2.0])

    def test_middle_page_exhaustion_is_not_success(self) -> None:
        page_one = {
            "items": [{"record_id": 1}],
            "count": 1,
            "has_more": True,
            "next_cursor": "cursor-2",
        }
        transport = QueueTransport(
            [
                response(page_one),
                response({}, status=503),
                response({}, status=503),
                response({}, status=503),
            ]
        )
        client = BronzeRelayClient(
            settings(), transport=transport, sleep=lambda _: None
        )
        iterator = client.iter_record_pages(dataset_id="dataset", api_key="secret")
        self.assertEqual(next(iterator).number, 1)

        with self.assertRaises(IncompleteCollectionError) as caught:
            next(iterator)

        self.assertEqual(caught.exception.completed_pages, 1)
        self.assertEqual(collection_failure_status(1), "partial_failure")
        self.assertNotEqual(collection_failure_status(1), "success")

    def test_cursor_loop_is_rejected(self) -> None:
        looping = {
            "items": [],
            "count": 0,
            "has_more": True,
            "next_cursor": "same",
        }
        transport = QueueTransport([response(looping), response(looping)])
        client = BronzeRelayClient(settings(), transport=transport)
        iterator = client.iter_record_pages(dataset_id="dataset", api_key="secret")
        next(iterator)
        next(iterator)
        with self.assertRaises(IncompleteCollectionError):
            next(iterator)


if __name__ == "__main__":
    unittest.main()
