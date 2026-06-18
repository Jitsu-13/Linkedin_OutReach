"""
Retry decorator with exponential backoff.

Wraps async functions with automatic retry logic, logging,
and optional screenshot capture on final failure.
"""

import asyncio
import functools
from typing import Callable, Optional, Tuple, Type

from utils.logger import logger


def with_retry(
    max_attempts: int = 3,
    backoff_base: float = 2.0,
    backoff_max: float = 60.0,
    retry_on: Tuple[Type[Exception], ...] = (Exception,),
    on_final_failure: Optional[Callable] = None,
):
    """
    Async retry decorator with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts (including the first).
        backoff_base: Base seconds for exponential backoff (2^attempt * base).
        backoff_max: Maximum backoff delay in seconds.
        retry_on: Tuple of exception types to retry on.
        on_final_failure: Optional async callback(exception) on final failure.
    
    Usage:
        @with_retry(max_attempts=3, retry_on=(TimeoutError, ConnectionError))
        async def fragile_operation():
            ...
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except retry_on as e:
                    last_exception = e
                    if attempt < max_attempts:
                        delay = min(backoff_base ** attempt, backoff_max)
                        logger.warning(
                            f"Retry {attempt}/{max_attempts} for {func.__name__}: "
                            f"{type(e).__name__}: {e} — retrying in {delay:.1f}s"
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"Final failure for {func.__name__} after {max_attempts} attempts: "
                            f"{type(e).__name__}: {e}"
                        )

            # All attempts exhausted
            if on_final_failure and last_exception:
                try:
                    if asyncio.iscoroutinefunction(on_final_failure):
                        await on_final_failure(last_exception)
                    else:
                        on_final_failure(last_exception)
                except Exception as callback_err:
                    logger.error(f"on_final_failure callback error: {callback_err}")

            raise last_exception

        return wrapper

    return decorator
