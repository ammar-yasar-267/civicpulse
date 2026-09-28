"""Test doubles.

FakeRedis exists so cache and rate-limiter behaviour is tested deterministically and with no
network — including TTL expiry, which is tested by advancing a fake clock rather than by
calling time.sleep(). A test that sleeps is a test that is slow and still flaky (§2.5).

The fakes implement only the methods the production code actually calls. That is a feature:
if someone reaches for a new Redis command, the fake fails loudly instead of silently
drifting from the real client.
"""

import json
from typing import Any

from app.providers.triage.base import TriageError
from app.schemas import TriageResult


class FakeClock:
    """Manually advanced clock, so TTL tests are instant and exact."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeRedis:
    """In-memory stand-in for redis.Redis, with real expiry semantics."""

    def __init__(self, clock: FakeClock | None = None) -> None:
        self._clock = clock or FakeClock()
        self._data: dict[str, str] = {}
        self._expires: dict[str, float] = {}
        self.fail = False  # flip on to simulate Redis being down

    # --- helpers ---------------------------------------------------------------

    def _guard(self) -> None:
        if self.fail:
            from redis.exceptions import ConnectionError as RedisConnectionError

            raise RedisConnectionError("fake redis is down")

    def _expire_if_due(self, key: str) -> None:
        expiry = self._expires.get(key)
        if expiry is not None and self._clock.now >= expiry:
            self._data.pop(key, None)
            self._expires.pop(key, None)

    # --- commands --------------------------------------------------------------

    def ping(self) -> bool:
        self._guard()
        return True

    def get(self, key: str) -> str | None:
        self._guard()
        self._expire_if_due(key)
        return self._data.get(key)

    def setex(self, key: str, ttl: int, value: str) -> bool:
        self._guard()
        self._data[key] = value
        self._expires[key] = self._clock.now + ttl
        return True

    def delete(self, *keys: str) -> int:
        self._guard()
        removed = 0
        for key in keys:
            removed += 1 if self._data.pop(key, None) is not None else 0
            self._expires.pop(key, None)
        return removed

    def incr(self, key: str) -> int:
        self._guard()
        self._expire_if_due(key)
        value = int(self._data.get(key, "0")) + 1
        self._data[key] = str(value)
        return value

    def ttl(self, key: str) -> int:
        self._guard()
        self._expire_if_due(key)
        if key not in self._data:
            return -2  # no such key
        if key not in self._expires:
            return -1  # key exists, no expiry
        return max(int(self._expires[key] - self._clock.now), 0)

    def expire(self, key: str, seconds: int) -> bool:
        self._guard()
        if key not in self._data:
            return False
        self._expires[key] = self._clock.now + seconds
        return True

    def close(self) -> None:
        return None

    def pipeline(self) -> "FakePipeline":
        return FakePipeline(self)


class FakePipeline:
    """Queues commands and runs them on execute(), like the real pipeline."""

    def __init__(self, client: FakeRedis) -> None:
        self._client = client
        self._queued: list[tuple[str, tuple[Any, ...]]] = []

    def incr(self, key: str) -> "FakePipeline":
        self._queued.append(("incr", (key,)))
        return self

    def ttl(self, key: str) -> "FakePipeline":
        self._queued.append(("ttl", (key,)))
        return self

    def execute(self) -> list[Any]:
        self._client._guard()
        return [getattr(self._client, name)(*args) for name, args in self._queued]


# --- triage provider doubles ---------------------------------------------------


class AlwaysRaisingProvider:
    """The provider from the test the assignment says to write if you write no other."""

    name = "llm:groq"

    def __init__(self, exc: Exception | None = None) -> None:
        self._exc = exc or TriageError("provider is down")
        self.calls = 0

    def triage(self, text: str, location: str) -> TriageResult:
        self.calls += 1
        raise self._exc


class FlakyProvider:
    """Fails the first N calls, then succeeds — exercises the single retry."""

    name = "llm:groq"

    def __init__(self, failures: int, exc: Exception, result: TriageResult) -> None:
        self._remaining = failures
        self._exc = exc
        self._result = result
        self.calls = 0

    def triage(self, text: str, location: str) -> TriageResult:
        self.calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise self._exc
        return self._result


class StaticProvider:
    """Returns a fixed result and counts calls — used to prove the cache prevents a second
    inference for duplicate content."""

    def __init__(self, result: TriageResult, name: str = "llm:groq") -> None:
        self.name = name
        self._result = result
        self.calls = 0

    def triage(self, text: str, location: str) -> TriageResult:
        self.calls += 1
        return self._result


class RawReplyProvider:
    """Returns whatever raw string it is given, parsed through the real parser — the way a
    misbehaving model reaches the validator in production."""

    name = "llm:groq"

    def __init__(self, raw: str) -> None:
        self._raw = raw
        self.calls = 0

    def triage(self, text: str, location: str) -> TriageResult:
        from app.providers.triage.prompt import parse_triage_response

        self.calls += 1
        return parse_triage_response(self._raw)


def json_reply(**fields: Any) -> str:
    return json.dumps(fields)
