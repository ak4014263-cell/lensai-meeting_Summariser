"""
Test suite for AI Meeting Assistant optimizations.

Run with: python -m pytest tests/test_optimizations.py -v
"""

import pytest
import time
from unittest.mock import Mock, patch
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.app.utils.cache import InMemoryCache, cache_key, CacheManager
from backend.app.utils.retry_logic import retry_with_backoff, fallback_on_error, CircuitBreaker
from backend.app.utils.performance_monitor import PerformanceMonitor, calculate_transcription_quality


class TestCache:
    """Test caching functionality."""
    
    def test_cache_set_get(self):
        """Test basic cache set and get operations."""
        cache = InMemoryCache()
        
        cache.set("test_key", {"data": "value"}, ttl=60)
        result = cache.get("test_key")
        
        assert result == {"data": "value"}
    
    def test_cache_expiry(self):
        """Test that cache entries expire correctly."""
        cache = InMemoryCache()
        
        cache.set("test_key", "value", ttl=1)
        time.sleep(1.5)
        result = cache.get("test_key")
        
        assert result is None
    
    def test_cache_lru_eviction(self):
        """Test LRU eviction when cache is full."""
        cache = InMemoryCache(max_size=2)
        
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")  # Should evict key1
        
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"
    
    def test_cache_key_generation(self):
        """Test cache key generation from arguments."""
        key1 = cache_key("meeting", 123, status="completed")
        key2 = cache_key("meeting", 123, status="completed")
        key3 = cache_key("meeting", 456, status="completed")
        
        assert key1 == key2
        assert key1 != key3
    
    def test_cache_stats(self):
        """Test cache statistics."""
        cache = InMemoryCache(max_size=10)
        
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        
        stats = cache.stats()
        assert stats["size"] == 2
        assert stats["max_size"] == 10
    
    def test_cache_manager(self):
        """Test CacheManager helper methods."""
        # Test meeting summary caching
        summary = {"executive_summary": "Test summary", "key_points": ["Point 1"]}
        CacheManager.cache_meeting_summary(123, summary)
        
        result = CacheManager.get_meeting_summary(123)
        assert result == summary
        
        # Test cache invalidation
        CacheManager.invalidate_meeting(123)
        result = CacheManager.get_meeting_summary(123)
        assert result is None


class TestRetryLogic:
    """Test retry and error handling functionality."""
    
    def test_retry_with_backoff_success(self):
        """Test retry decorator with successful execution."""
        call_count = [0]
        
        @retry_with_backoff(max_attempts=3, initial_delay=0.1)
        def unstable_function():
            call_count[0] += 1
            if call_count[0] < 2:
                raise Exception("Temporary error")
            return "success"
        
        result = unstable_function()
        assert result == "success"
        assert call_count[0] == 2
    
    def test_retry_with_backoff_failure(self):
        """Test retry decorator when all attempts fail."""
        call_count = [0]
        
        @retry_with_backoff(max_attempts=3, initial_delay=0.1)
        def always_fails():
            call_count[0] += 1
            raise ValueError("Persistent error")
        
        with pytest.raises(ValueError):
            always_fails()
        
        assert call_count[0] == 3
    
    def test_fallback_on_error(self):
        """Test fallback decorator."""
        @fallback_on_error(fallback_value=[], log_error=False)
        def risky_function():
            raise RuntimeError("Something went wrong")
        
        result = risky_function()
        assert result == []
    
    def test_circuit_breaker_opens(self):
        """Test that circuit breaker opens after threshold."""
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=1)
        
        def failing_operation():
            raise Exception("Error")
        
        # Fail 3 times to open circuit
        for _ in range(3):
            with pytest.raises(Exception):
                breaker.call(failing_operation)
        
        # Circuit should now be open
        with pytest.raises(Exception, match="Circuit breaker is OPEN"):
            breaker.call(failing_operation)
    
    def test_circuit_breaker_recovery(self):
        """Test circuit breaker recovery after timeout."""
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=0.5)
        
        call_count = [0]
        
        def unstable_operation():
            call_count[0] += 1
            if call_count[0] < 3:
                raise Exception("Error")
            return "success"
        
        # Open circuit
        for _ in range(2):
            with pytest.raises(Exception):
                breaker.call(unstable_operation)
        
        # Wait for recovery timeout
        time.sleep(0.6)
        
        # Should enter half-open state and succeed
        result = breaker.call(unstable_operation)
        assert result == "success"


class TestPerformanceMonitoring:
    """Test performance monitoring functionality."""
    
    def test_performance_monitor_measure(self):
        """Test performance measurement context manager."""
        monitor = PerformanceMonitor()
        
        with monitor.measure("test_operation", param1="value1"):
            time.sleep(0.1)
        
        assert len(monitor.metrics) == 1
        metric = monitor.metrics[0]
        assert metric.operation == "test_operation"
        assert metric.duration_ms >= 100
        assert metric.metadata["param1"] == "value1"
    
    def test_performance_summary(self):
        """Test performance summary statistics."""
        monitor = PerformanceMonitor()
        
        # Record multiple operations
        for i in range(3):
            with monitor.measure("operation_a"):
                time.sleep(0.05)
        
        for i in range(2):
            with monitor.measure("operation_b"):
                time.sleep(0.1)
        
        summary = monitor.get_summary()
        
        assert "operation_a" in summary
        assert "operation_b" in summary
        assert summary["operation_a"]["count"] == 3
        assert summary["operation_b"]["count"] == 2
    
    def test_transcription_quality_metrics(self):
        """Test transcription quality calculation."""
        segments = [
            {
                "start_ms": 0,
                "end_ms": 5000,
                "text": "Hello world this is a test",
                "speaker": "Speaker A",
                "confidence": 0.95,
            },
            {
                "start_ms": 5000,
                "end_ms": 10000,
                "text": "Another segment here",
                "speaker": "Speaker B",
                "confidence": 0.90,
            },
        ]
        
        metrics = calculate_transcription_quality(segments, duration_ms=15000)
        
        assert metrics.total_segments == 2
        assert metrics.speakers_detected == 2
        assert metrics.avg_confidence == pytest.approx(0.925)
        assert metrics.silence_ratio == pytest.approx(1 - (10000 / 15000))


class TestTranscriptionOptimization:
    """Test transcription optimization features."""
    
    @pytest.mark.skipif(
        not os.getenv("HUGGINGFACE_TOKEN"),
        reason="HUGGINGFACE_TOKEN not set"
    )
    def test_huggingface_model_loading(self):
        """Test Hugging Face model can be loaded."""
        from Lensai_Bot.transcription.huggingface_whisper import HuggingFacePipelineEngine
        
        try:
            engine = HuggingFacePipelineEngine()
            pipeline = engine.get_pipeline()
            assert pipeline is not None
        except Exception as e:
            pytest.skip(f"Could not load HF model: {e}")
    
    def test_advanced_transcription_config(self):
        """Test advanced transcription configuration."""
        from Lensai_Bot.transcription.advanced_transcription import AdvancedTranscriptionEngine
        
        engine = AdvancedTranscriptionEngine()
        assert hasattr(engine, 'enable_diarization')
        assert hasattr(engine, 'enable_noise_reduction')
        assert hasattr(engine, 'enable_vad')


class TestDatabaseOptimizations:
    """Test database query optimizations."""
    
    def test_cache_manager_transcript(self):
        """Test transcript caching."""
        transcript = "This is a test transcript"
        meeting_id = 999
        
        CacheManager.cache_transcript(meeting_id, transcript)
        result = CacheManager.get_transcript(meeting_id)
        
        assert result == transcript
    
    def test_cache_manager_user_meetings(self):
        """Test user meetings caching."""
        meetings = [{"id": 1, "title": "Meeting 1"}, {"id": 2, "title": "Meeting 2"}]
        user_id = 123
        
        CacheManager.cache_user_meetings(user_id, meetings)
        result = CacheManager.get_user_meetings(user_id)
        
        assert result == meetings


class TestIntegration:
    """Integration tests for complete workflows."""
    
    def test_full_cache_workflow(self):
        """Test complete caching workflow."""
        cache = InMemoryCache()
        
        # Set multiple keys
        cache.set("user:1:meetings", ["meeting1", "meeting2"], ttl=60)
        cache.set("meeting:1:summary", {"summary": "test"}, ttl=60)
        
        # Verify retrieval
        assert cache.get("user:1:meetings") == ["meeting1", "meeting2"]
        assert cache.get("meeting:1:summary") == {"summary": "test"}
        
        # Check stats
        stats = cache.stats()
        assert stats["size"] == 2
        
        # Clear cache
        cache.clear()
        assert cache.get("user:1:meetings") is None
    
    def test_performance_with_retry(self):
        """Test performance monitoring with retry logic."""
        monitor = PerformanceMonitor()
        call_count = [0]
        
        @retry_with_backoff(max_attempts=2, initial_delay=0.1)
        def monitored_operation():
            with monitor.measure("test_op"):
                call_count[0] += 1
                if call_count[0] < 2:
                    raise Exception("Retry me")
                return "success"
        
        result = monitored_operation()
        
        assert result == "success"
        assert len(monitor.metrics) == 2  # Two attempts recorded


# Benchmark tests (run with pytest -v --benchmark)
class TestBenchmarks:
    """Performance benchmarks."""
    
    def test_cache_performance(self):
        """Benchmark cache operations."""
        cache = InMemoryCache(max_size=10000)
        
        # Benchmark writes
        start = time.time()
        for i in range(1000):
            cache.set(f"key_{i}", f"value_{i}")
        write_time = time.time() - start
        
        # Benchmark reads
        start = time.time()
        for i in range(1000):
            cache.get(f"key_{i}")
        read_time = time.time() - start
        
        print(f"\nCache performance:")
        print(f"  1000 writes: {write_time*1000:.2f}ms")
        print(f"  1000 reads: {read_time*1000:.2f}ms")
        
        # Verify performance is acceptable
        assert write_time < 0.1  # Should be under 100ms
        assert read_time < 0.1


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "--tb=short"])
