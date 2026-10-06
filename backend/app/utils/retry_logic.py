"""Retry logic and error handling utilities for robust operation."""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable, Optional, Tuple, Type

logger = logging.getLogger("lensai_bot.retry")


class RetryableError(Exception):
    """Base class for errors that should trigger a retry."""
    pass


class NetworkError(RetryableError):
    """Network-related errors."""
    pass


class ResourceError(RetryableError):
    """Resource temporarily unavailable."""
    pass


class ModelLoadError(RetryableError):
    """Model loading error."""
    pass


def retry_with_backoff(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 60.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """
    Decorator to retry a function with exponential backoff.
    
    Args:
        max_attempts: Maximum number of retry attempts
        initial_delay: Initial delay in seconds between retries
        backoff_factor: Multiplier for delay after each retry
        max_delay: Maximum delay between retries
        exceptions: Tuple of exception types to catch and retry
    
    Usage:
        @retry_with_backoff(max_attempts=3, initial_delay=1.0)
        def unstable_function():
            # ... code that might fail ...
            pass
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            delay = initial_delay
            last_exception = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {e}"
                        )
                        raise
                    
                    logger.warning(
                        f"{func.__name__} failed (attempt {attempt}/{max_attempts}): {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    
                    time.sleep(delay)
                    delay = min(delay * backoff_factor, max_delay)
            
            # Should never reach here, but just in case
            if last_exception:
                raise last_exception
            
        return wrapper
    return decorator


def fallback_on_error(fallback_value: Any = None, log_error: bool = True):
    """
    Decorator to return a fallback value if the function raises an exception.
    
    Args:
        fallback_value: Value to return on error
        log_error: Whether to log the error
    
    Usage:
        @fallback_on_error(fallback_value=[])
        def risky_function():
            # ... code that might fail ...
            return result
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if log_error:
                    logger.error(f"{func.__name__} failed: {e}. Returning fallback value.")
                return fallback_value
        return wrapper
    return decorator


class CircuitBreaker:
    """
    Circuit breaker pattern to prevent cascading failures.
    
    After a certain number of failures, the circuit "opens" and subsequent
    calls fail immediately without attempting the operation. After a timeout,
    the circuit enters "half-open" state and allows one test call.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: Type[Exception] = Exception,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = "closed"  # closed, open, half-open
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection."""
        
        if self.state == "open":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                logger.info("Circuit breaker entering half-open state")
                self.state = "half-open"
            else:
                raise Exception(f"Circuit breaker is OPEN (too many failures)")
        
        try:
            result = func(*args, **kwargs)
            
            # Success - reset if we were in half-open state
            if self.state == "half-open":
                logger.info("Circuit breaker closing (recovered)")
                self.state = "closed"
                self.failure_count = 0
            
            return result
            
        except self.expected_exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                logger.error(
                    f"Circuit breaker OPENING after {self.failure_count} failures"
                )
                self.state = "open"
            
            raise


def with_timeout(seconds: float):
    """
    Decorator to add timeout to a function.
    
    Note: This uses threading, so it won't interrupt CPU-bound operations.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            import threading
            
            result = [None]
            exception = [None]
            
            def target():
                try:
                    result[0] = func(*args, **kwargs)
                except Exception as e:
                    exception[0] = e
            
            thread = threading.Thread(target=target)
            thread.daemon = True
            thread.start()
            thread.join(timeout=seconds)
            
            if thread.is_alive():
                raise TimeoutError(
                    f"{func.__name__} exceeded timeout of {seconds}s"
                )
            
            if exception[0]:
                raise exception[0]
            
            return result[0]
        
        return wrapper
    return decorator


class ErrorRecovery:
    """Helper class for graceful error recovery strategies."""
    
    @staticmethod
    def safe_execute(
        func: Callable,
        fallback: Any = None,
        error_message: str = "Operation failed",
    ) -> Any:
        """
        Safely execute a function with fallback.
        
        Args:
            func: Function to execute
            fallback: Value to return on error
            error_message: Custom error message to log
        
        Returns:
            Function result or fallback value
        """
        try:
            return func()
        except Exception as e:
            logger.error(f"{error_message}: {e}")
            return fallback
    
    @staticmethod
    def try_multiple_strategies(
        strategies: list[Callable],
        strategy_names: Optional[list[str]] = None,
    ) -> Any:
        """
        Try multiple strategies in order until one succeeds.
        
        Args:
            strategies: List of functions to try
            strategy_names: Optional names for logging
        
        Returns:
            Result from first successful strategy
        
        Raises:
            Exception if all strategies fail
        """
        last_exception = None
        
        for i, strategy in enumerate(strategies):
            name = strategy_names[i] if strategy_names else f"Strategy {i+1}"
            
            try:
                logger.info(f"Trying {name}...")
                result = strategy()
                logger.info(f"✓ {name} succeeded")
                return result
            except Exception as e:
                logger.warning(f"✗ {name} failed: {e}")
                last_exception = e
                continue
        
        # All strategies failed
        raise Exception(
            f"All {len(strategies)} strategies failed. "
            f"Last error: {last_exception}"
        )


# Example usage demonstration
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    @retry_with_backoff(max_attempts=3, initial_delay=0.5)
    def unstable_api_call():
        import random
        if random.random() < 0.7:  # 70% chance of failure
            raise NetworkError("Connection failed")
        return "Success!"
    
    try:
        result = unstable_api_call()
        print(f"Result: {result}")
    except Exception as e:
        print(f"Failed: {e}")
