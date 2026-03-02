"""
Sliding Window Statistics Collector

Maintains a time-based sliding window of request samples for computing
latency percentiles and error rates. Thread-safe implementation using locks.

Design Rationale:
- Using deque for O(1) append and efficient pruning from left
- Lock-based synchronization for simplicity (asyncio.Lock for async context)
- Percentile calculation uses insertion sort for small windows (fast in practice)
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class WindowStats:
    """Statistics computed from the sliding window."""
    sample_count: int
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    error_rate: float
    avg_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    window_duration_s: float
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'sample_count': self.sample_count,
            'p50_latency_ms': round(self.p50_latency_ms, 2),
            'p95_latency_ms': round(self.p95_latency_ms, 2),
            'p99_latency_ms': round(self.p99_latency_ms, 2),
            'error_rate': round(self.error_rate, 4),
            'avg_latency_ms': round(self.avg_latency_ms, 2),
            'min_latency_ms': round(self.min_latency_ms, 2),
            'max_latency_ms': round(self.max_latency_ms, 2),
            'window_duration_s': round(self.window_duration_s, 2),
        }


@dataclass
class Sample:
    """A single request sample."""
    timestamp: float  # Unix timestamp
    latency_ms: float
    is_error: bool


class SlidingWindow:
    """
    Thread-safe sliding window for collecting request latency samples.
    
    The window automatically prunes old samples older than window_size_s.
    Statistics are computed on-demand from current window contents.
    
    Example:
        window = SlidingWindow(window_size_s=10.0)
        
        # Record samples
        window.record(latency_ms=15.0, is_error=False)
        window.record(latency_ms=45.0, is_error=False)
        window.record(latency_ms=500.0, is_error=True)
        
        # Get statistics
        stats = window.get_stats()
        print(f"P95: {stats.p95_latency_ms}ms, Errors: {stats.error_rate:.1%}")
    """
    
    def __init__(self, window_size_s: float = 10.0):
        """
        Initialize sliding window.
        
        Args:
            window_size_s: How many seconds of samples to retain
        """
        self.window_size_s = window_size_s
        self._samples: deque[Sample] = deque()
        self._lock = asyncio.Lock()
    
    async def record(self, latency_ms: float, is_error: bool = False) -> None:
        """
        Record a request sample.
        
        Args:
            latency_ms: Request latency in milliseconds
            is_error: Whether the request resulted in an error
        """
        sample = Sample(
            timestamp=time.time(),
            latency_ms=latency_ms,
            is_error=is_error,
        )
        
        async with self._lock:
            self._samples.append(sample)
            self._prune_old_samples()
    
    async def record_many(self, samples: List[Tuple[float, bool]]) -> None:
        """
        Record multiple samples at once (more efficient for batches).
        
        Args:
            samples: List of (latency_ms, is_error) tuples
        """
        now = time.time()
        async with self._lock:
            for latency_ms, is_error in samples:
                self._samples.append(Sample(
                    timestamp=now,
                    latency_ms=latency_ms,
                    is_error=is_error,
                ))
            self._prune_old_samples()
    
    def _prune_old_samples(self) -> None:
        """Remove samples older than window_size_s. Called while holding lock."""
        cutoff = time.time() - self.window_size_s
        while self._samples and self._samples[0].timestamp < cutoff:
            self._samples.popleft()
    
    async def get_stats(self) -> WindowStats:
        """
        Compute statistics from current window.
        
        Returns:
            WindowStats with percentiles, error rate, etc.
            Returns zeroed stats if window is empty.
        """
        async with self._lock:
            self._prune_old_samples()
            
            if not self._samples:
                return WindowStats(
                    sample_count=0,
                    p50_latency_ms=0.0,
                    p95_latency_ms=0.0,
                    p99_latency_ms=0.0,
                    error_rate=0.0,
                    avg_latency_ms=0.0,
                    min_latency_ms=0.0,
                    max_latency_ms=0.0,
                    window_duration_s=0.0,
                )
            
            # Extract latencies and count errors
            latencies = [s.latency_ms for s in self._samples]
            error_count = sum(1 for s in self._samples if s.is_error)
            
            # Calculate window duration
            timestamps = [s.timestamp for s in self._samples]
            window_duration = max(timestamps) - min(timestamps) if len(timestamps) > 1 else 0.0
            
            # Sort for percentile calculation
            sorted_latencies = sorted(latencies)
            n = len(sorted_latencies)
            
            return WindowStats(
                sample_count=n,
                p50_latency_ms=self._percentile(sorted_latencies, 50),
                p95_latency_ms=self._percentile(sorted_latencies, 95),
                p99_latency_ms=self._percentile(sorted_latencies, 99),
                error_rate=error_count / n if n > 0 else 0.0,
                avg_latency_ms=sum(latencies) / n,
                min_latency_ms=min(latencies),
                max_latency_ms=max(latencies),
                window_duration_s=window_duration,
            )
    
    @staticmethod
    def _percentile(sorted_values: List[float], percentile: float) -> float:
        """
        Calculate percentile from sorted values.
        
        Uses linear interpolation for values between indices.
        """
        if not sorted_values:
            return 0.0
        
        n = len(sorted_values)
        if n == 1:
            return sorted_values[0]
        
        # Calculate index (using nearest-rank method with interpolation)
        k = (percentile / 100.0) * (n - 1)
        f = int(k)
        c = f + 1 if f + 1 < n else f
        
        # Linear interpolation
        return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])
    
    async def clear(self) -> None:
        """Clear all samples from the window."""
        async with self._lock:
            self._samples.clear()
    
    async def get_sample_count(self) -> int:
        """Get current number of samples in window."""
        async with self._lock:
            self._prune_old_samples()
            return len(self._samples)


# Synchronous version for non-async contexts
class SyncSlidingWindow:
    """
    Synchronous version of SlidingWindow for use in non-async contexts.
    Uses threading.Lock instead of asyncio.Lock.
    """
    
    def __init__(self, window_size_s: float = 10.0):
        import threading
        self.window_size_s = window_size_s
        self._samples: deque[Sample] = deque()
        self._lock = threading.Lock()
    
    def record(self, latency_ms: float, is_error: bool = False) -> None:
        """Record a request sample."""
        sample = Sample(
            timestamp=time.time(),
            latency_ms=latency_ms,
            is_error=is_error,
        )
        
        with self._lock:
            self._samples.append(sample)
            self._prune_old_samples()
    
    def _prune_old_samples(self) -> None:
        """Remove samples older than window_size_s."""
        cutoff = time.time() - self.window_size_s
        while self._samples and self._samples[0].timestamp < cutoff:
            self._samples.popleft()
    
    def get_stats(self) -> WindowStats:
        """Compute statistics from current window."""
        with self._lock:
            self._prune_old_samples()
            
            if not self._samples:
                return WindowStats(
                    sample_count=0,
                    p50_latency_ms=0.0,
                    p95_latency_ms=0.0,
                    p99_latency_ms=0.0,
                    error_rate=0.0,
                    avg_latency_ms=0.0,
                    min_latency_ms=0.0,
                    max_latency_ms=0.0,
                    window_duration_s=0.0,
                )
            
            latencies = [s.latency_ms for s in self._samples]
            error_count = sum(1 for s in self._samples if s.is_error)
            timestamps = [s.timestamp for s in self._samples]
            window_duration = max(timestamps) - min(timestamps) if len(timestamps) > 1 else 0.0
            
            sorted_latencies = sorted(latencies)
            n = len(sorted_latencies)
            
            def percentile(values: List[float], p: float) -> float:
                if not values:
                    return 0.0
                k = (p / 100.0) * (len(values) - 1)
                f = int(k)
                c = f + 1 if f + 1 < len(values) else f
                return values[f] + (k - f) * (values[c] - values[f])
            
            return WindowStats(
                sample_count=n,
                p50_latency_ms=percentile(sorted_latencies, 50),
                p95_latency_ms=percentile(sorted_latencies, 95),
                p99_latency_ms=percentile(sorted_latencies, 99),
                error_rate=error_count / n if n > 0 else 0.0,
                avg_latency_ms=sum(latencies) / n,
                min_latency_ms=min(latencies),
                max_latency_ms=max(latencies),
                window_duration_s=window_duration,
            )
