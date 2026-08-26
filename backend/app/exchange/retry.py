"""
Exponential backoff retry helpers for CCXT calls.

Design goals:
- Retry only on transient upstream issues (rate limit, timeouts, network).
- Add jitter to avoid thundering herd.
- Keep the exchange layer side-effect free (no telegram import here).
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence, Tuple, Type, TypeVar

import logging

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _default_retryable_exceptions() -> Tuple[Type[BaseException], ...]:
    try:
        # CCXT exception hierarchy
        from ccxt.base.errors import (  # type: ignore
            DDoSProtection,
            ExchangeNotAvailable,
            NetworkError,
            RateLimitExceeded,
            RequestTimeout,
        )

        return (
            RateLimitExceeded,
            RequestTimeout,
            NetworkError,
            ExchangeNotAvailable,
            DDoSProtection,
        )
    except Exception:
        # If CCXT import fails at runtime for any reason, fall back to no special casing.
        return tuple()


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 6.0
    backoff_factor: float = 2.0
    jitter_ratio: float = 0.25  # +/- 25%


def _sleep_duration(policy: RetryPolicy, attempt: int) -> float:
    # attempt is 1-based; we sleep after a failure, so attempt>=1
    delay = min(policy.max_delay_s, policy.base_delay_s * (policy.backoff_factor ** (attempt - 1)))
    jitter = delay * policy.jitter_ratio
    return max(0.0, random.uniform(delay - jitter, delay + jitter))


def call_with_retry(
    fn: Callable[[], T],
    *,
    op_name: str,
    policy: Optional[RetryPolicy] = None,
    retryable_exceptions: Optional[Sequence[Type[BaseException]]] = None,
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
) -> T:
    """
    Run a synchronous function with exponential backoff + jitter.
    """
    policy = policy or RetryPolicy()
    retryables = tuple(retryable_exceptions) if retryable_exceptions is not None else _default_retryable_exceptions()

    last_exc: Optional[BaseException] = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn()
        except BaseException as exc:  # noqa: BLE001 - deliberate, we re-raise at the end
            last_exc = exc
            is_retryable = isinstance(exc, retryables) if retryables else False
            if not is_retryable or attempt >= policy.max_attempts:
                raise

            sleep_s = _sleep_duration(policy, attempt)
            logger.warning(
                "CCXT call retrying: op=%s attempt=%s/%s sleep=%.2fs err=%s",
                op_name,
                attempt,
                policy.max_attempts,
                sleep_s,
                repr(exc),
            )
            if on_retry:
                try:
                    on_retry(attempt, exc, sleep_s)
                except Exception:
                    pass
            time.sleep(sleep_s)

    # should be unreachable
    assert last_exc is not None
    raise last_exc


def ccxt_retry(op_name: str, *, policy: Optional[RetryPolicy] = None):
    """
    Decorator form for wrapping BaseExchange methods.
    """

    def _decorator(func: Callable[..., T]) -> Callable[..., T]:
        def _wrapped(*args: Any, **kwargs: Any) -> T:
            return call_with_retry(lambda: func(*args, **kwargs), op_name=op_name, policy=policy)

        return _wrapped

    return _decorator
