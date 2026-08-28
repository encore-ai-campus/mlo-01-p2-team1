"""Bronze Relay HTTP client with bounded retries and signed-cursor paging.

Record responses retain the exact HTTP body bytes. JSON parsing is performed
against those bytes separately and never used to recreate the Raw artifact.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
import json
import random
import socket
import time
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import Settings


class ClientError(RuntimeError):
    """Base client failure that never embeds credentials or response bodies."""


class HttpRequestError(ClientError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ResponseContractError(ClientError):
    """The endpoint returned JSON that violates the agreed source contract."""


class IncompleteCollectionError(ClientError):
    def __init__(self, message: str, *, completed_pages: int) -> None:
        super().__init__(message)
        self.completed_pages = completed_pages


@dataclass(frozen=True, slots=True)
class HttpBody:
    status: int
    headers: Mapping[str, str]
    body: bytes
    retry_count: int = 0

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "application/octet-stream").split(
            ";", 1
        )[0].strip()


@dataclass(frozen=True, slots=True)
class CollectedPage:
    number: int
    response: HttpBody
    parsed: Mapping[str, Any]
    requested_cursor: str | None

    @property
    def items(self) -> list[Mapping[str, Any]]:
        items = self.parsed["items"]
        return items  # type: ignore[return-value]


class Transport(Protocol):
    def __call__(self, request: Request, timeout: int) -> HttpBody: ...


def _default_transport(request: Request, timeout: int) -> HttpBody:
    with urlopen(request, timeout=timeout) as response:
        return HttpBody(
            status=response.status,
            headers={key.lower(): value for key, value in response.headers.items()},
            body=response.read(),
        )


def parse_json_body(body: bytes, *, endpoint_name: str) -> Mapping[str, Any]:
    try:
        parsed = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResponseContractError(f"{endpoint_name} returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ResponseContractError(f"{endpoint_name} JSON must be an object")
    return parsed


class BronzeRelayClient:
    RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        settings: Settings,
        *,
        transport: Transport = _default_transport,
        sleep: Callable[[float], None] = time.sleep,
        random_uniform: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.settings = settings
        self._transport = transport
        self._sleep = sleep
        self._random_uniform = random_uniform

    def _url(self, endpoint: str, query: Mapping[str, Any] | None = None) -> str:
        url = f"{self.settings.api_base_url}{endpoint}"
        if query:
            encoded = urlencode(
                {key: value for key, value in query.items() if value is not None}
            )
            url = f"{url}?{encoded}"
        return url

    def _delay(self, retry_number: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), self.settings.backoff_max_seconds)
            except ValueError:
                pass
        exponential = min(
            self.settings.backoff_base_seconds * (2 ** (retry_number - 1)),
            self.settings.backoff_max_seconds,
        )
        jitter = self._random_uniform(0, self.settings.jitter_max_seconds)
        return exponential + jitter

    def _request(
        self,
        endpoint: str,
        *,
        query: Mapping[str, Any] | None = None,
        api_key: str | None = None,
    ) -> HttpBody:
        headers = {
            "Accept": "application/json",
            "User-Agent": self.settings.user_agent,
        }
        if api_key is not None:
            headers["X-API-Key"] = api_key
        request = Request(self._url(endpoint, query), headers=headers, method="GET")

        for attempt in range(self.settings.max_retries + 1):
            try:
                response = self._transport(
                    request, self.settings.request_timeout_seconds
                )
                status = response.status
                response_headers = response.headers
            except HTTPError as exc:
                status = exc.code
                response_headers = {
                    key.lower(): value for key, value in (exc.headers or {}).items()
                }
                response = None
            except (URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
                if attempt >= self.settings.max_retries:
                    raise HttpRequestError(
                        "request failed after bounded network retries"
                    ) from exc
                self._sleep(self._delay(attempt + 1, None))
                continue

            if 200 <= status < 300 and response is not None:
                return HttpBody(
                    status=response.status,
                    headers=response.headers,
                    body=response.body,
                    retry_count=attempt,
                )
            if status in self.RETRYABLE_STATUSES and attempt < self.settings.max_retries:
                self._sleep(
                    self._delay(attempt + 1, response_headers.get("retry-after"))
                )
                continue
            raise HttpRequestError(
                f"request failed with HTTP status {status}", status=status
            )

        raise AssertionError("bounded request loop ended unexpectedly")

    def fetch_api_key(self) -> str:
        response = self._request(self.settings.api_key_endpoint)
        parsed = parse_json_body(response.body, endpoint_name="API key endpoint")
        for field in ("api_key", "key", "token"):
            value = parsed.get(field)
            if isinstance(value, str) and value:
                return value
        raise ResponseContractError("API key response has no supported key field")

    def _authenticated_request(
        self,
        endpoint: str,
        *,
        api_key: str,
        query: Mapping[str, Any] | None = None,
    ) -> tuple[HttpBody, str]:
        try:
            return self._request(endpoint, query=query, api_key=api_key), api_key
        except HttpRequestError as exc:
            if exc.status != 401:
                raise
        refreshed_key = self.fetch_api_key()
        return (
            self._request(endpoint, query=query, api_key=refreshed_key),
            refreshed_key,
        )

    def fetch_metadata(self, *, api_key: str) -> Mapping[str, Any]:
        response, _ = self._authenticated_request(
            self.settings.api_meta_endpoint, api_key=api_key
        )
        return parse_json_body(response.body, endpoint_name="metadata endpoint")

    @staticmethod
    def resolve_dataset_id(
        metadata: Mapping[str, Any], *, source_name: str
    ) -> str:
        """Resolve exactly one explicitly named dataset; never select by position."""

        candidates: list[Mapping[str, Any]] = []
        if isinstance(metadata.get("dataset_id"), str):
            candidates.append(metadata)
        for field in ("datasets", "items", "data"):
            value = metadata.get(field)
            if isinstance(value, list):
                candidates.extend(item for item in value if isinstance(item, Mapping))
            elif isinstance(value, Mapping):
                candidates.append(value)

        matches: list[str] = []
        for candidate in candidates:
            candidate_name = next(
                (
                    candidate.get(field)
                    for field in ("source_name", "dataset_name", "name")
                    if isinstance(candidate.get(field), str)
                ),
                None,
            )
            dataset_id = candidate.get("dataset_id")
            if candidate_name == source_name and isinstance(dataset_id, str) and dataset_id:
                matches.append(dataset_id)
        unique_matches = list(dict.fromkeys(matches))
        if len(unique_matches) != 1:
            raise ResponseContractError(
                "metadata must identify exactly one biz_legacy_integrated dataset"
            )
        return unique_matches[0]

    def iter_record_pages(
        self,
        *,
        dataset_id: str,
        api_key: str,
        initial_cursor: str | None = None,
        expected_checkpoint: str | None = None,
        expected_released_rows: int | None = None,
    ) -> Iterator[CollectedPage]:
        cursor = initial_cursor
        seen_cursors: set[str] = {initial_cursor} if initial_cursor else set()
        page_number = 1
        current_key = api_key
        snapshot_checkpoint: str | None = None
        snapshot_dataset_id: str | None = None
        snapshot_released_rows: int | None = None

        while True:
            try:
                response, current_key = self._authenticated_request(
                    self.settings.api_records_endpoint,
                    api_key=current_key,
                    query={
                        "dataset_id": dataset_id,
                        "limit": self.settings.page_limit,
                        "cursor": cursor,
                    },
                )
                parsed = parse_json_body(
                    response.body, endpoint_name=f"records page {page_number}"
                )
                self._validate_page(parsed, page_number=page_number)
                checkpoint, response_dataset_id, released_rows = (
                    self._snapshot_contract(parsed, page_number=page_number)
                )
                if snapshot_checkpoint is None:
                    snapshot_checkpoint = checkpoint
                    snapshot_dataset_id = response_dataset_id
                    snapshot_released_rows = released_rows
                    if response_dataset_id != dataset_id:
                        raise ResponseContractError(
                            "records dataset_id does not match the requested dataset"
                        )
                    if (
                        expected_checkpoint is not None
                        and checkpoint != expected_checkpoint
                    ):
                        raise ResponseContractError(
                            "resumed cursor checkpoint changed"
                        )
                    if (
                        expected_released_rows is not None
                        and released_rows != expected_released_rows
                    ):
                        raise ResponseContractError(
                            "resumed cursor released_rows changed"
                        )
                elif (
                    checkpoint != snapshot_checkpoint
                    or response_dataset_id != snapshot_dataset_id
                    or released_rows != snapshot_released_rows
                ):
                    raise ResponseContractError(
                        "records snapshot contract changed during cursor pagination"
                    )
            except ClientError as exc:
                raise IncompleteCollectionError(
                    f"full pagination failed at page {page_number}",
                    completed_pages=page_number - 1,
                ) from exc

            yield CollectedPage(
                number=page_number,
                response=response,
                parsed=parsed,
                requested_cursor=cursor,
            )

            has_more = parsed["has_more"]
            if has_more is False:
                return
            next_cursor = parsed["next_cursor"]
            if next_cursor in seen_cursors:
                raise IncompleteCollectionError(
                    "signed cursor loop detected",
                    completed_pages=page_number,
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor
            page_number += 1

    @staticmethod
    def _snapshot_contract(
        page: Mapping[str, Any], *, page_number: int
    ) -> tuple[str, str, int]:
        checkpoint = page.get("checkpoint")
        dataset_id = page.get("dataset_id")
        released_rows = page.get("released_rows")
        if not isinstance(checkpoint, str) or not checkpoint:
            raise ResponseContractError(
                f"records page {page_number} requires checkpoint"
            )
        if not isinstance(dataset_id, str) or not dataset_id:
            raise ResponseContractError(
                f"records page {page_number} requires dataset_id"
            )
        if not isinstance(released_rows, int) or released_rows < 0:
            raise ResponseContractError(
                f"records page {page_number} requires non-negative released_rows"
            )
        return checkpoint, dataset_id, released_rows

    @staticmethod
    def _validate_page(page: Mapping[str, Any], *, page_number: int) -> None:
        items = page.get("items")
        if not isinstance(items, list):
            raise ResponseContractError(f"records page {page_number} items must be a list")
        if page.get("count") != len(items):
            raise ResponseContractError(
                f"records page {page_number} count does not match items"
            )
        has_more = page.get("has_more")
        if not isinstance(has_more, bool):
            raise ResponseContractError(
                f"records page {page_number} has_more must be boolean"
            )
        next_cursor = page.get("next_cursor")
        if has_more and (not isinstance(next_cursor, str) or not next_cursor):
            raise ResponseContractError(
                f"records page {page_number} requires a signed next_cursor"
            )


def collection_failure_status(completed_pages: int) -> str:
    """Return a non-success Bronze status for an incomplete full collection."""

    return "partial_failure" if completed_pages > 0 else "failed"
