"""
Metrics Collector - Aggregates and reports limiter performance.

Collects:
- Throughput (requests/sec)
- Latency percentiles
- Limit history
- Rejection rate
- Error rate

Outputs:
- Real-time console display
- JSON export for analysis
- Summary statistics
"""

import json
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from collections import deque


@dataclass
class MetricsSnapshot:
    """Point-in-time metrics snapshot."""
    timestamp: float
    current_limit: int
    in_flight: int
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    requests_per_second: float
    rejection_rate: float
    error_rate: float
    sample_count: int


@dataclass
class MetricsSummary:
    """Summary statistics over a time period."""
    duration_s: float
    total_requests: int
    successful_requests: int
    rejected_requests: int
    error_requests: int
    
    # Throughput
    avg_rps: float
    peak_rps: float
    
    # Latency
    avg_p50_ms: float
    avg_p95_ms: float
    avg_p99_ms: float
    max_latency_ms: float
    
    # Limit behavior
    initial_limit: int
    final_limit: int
    min_limit: int
    max_limit: int
    avg_limit: float
    limit_changes: int
    
    # Rates
    rejection_rate: float
    error_rate: float
    
    def to_dict(self) -> dict:
        return {
            'duration_s': round(self.duration_s, 2),
            'total_requests': self.total_requests,
            'successful_requests': self.successful_requests,
            'rejected_requests': self.rejected_requests,
            'error_requests': self.error_requests,
            'avg_rps': round(self.avg_rps, 2),
            'peak_rps': round(self.peak_rps, 2),
            'latency': {
                'avg_p50_ms': round(self.avg_p50_ms, 2),
                'avg_p95_ms': round(self.avg_p95_ms, 2),
                'avg_p99_ms': round(self.avg_p99_ms, 2),
                'max_ms': round(self.max_latency_ms, 2),
            },
            'limit': {
                'initial': self.initial_limit,
                'final': self.final_limit,
                'min': self.min_limit,
                'max': self.max_limit,
                'avg': round(self.avg_limit, 2),
                'changes': self.limit_changes,
            },
            'rejection_rate': round(self.rejection_rate, 4),
            'error_rate': round(self.error_rate, 4),
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


class MetricsCollector:
    """
    Collects and aggregates metrics from the adaptive limiter.
    
    Example:
        collector = MetricsCollector()
        
        # Record snapshots periodically
        collector.record_snapshot(
            current_limit=50,
            in_flight=45,
            p50_latency_ms=20.0,
            ...
        )
        
        # Get summary
        summary = collector.get_summary()
        print(summary.to_json())
    """
    
    def __init__(self, max_snapshots: int = 10000):
        self._snapshots: deque[MetricsSnapshot] = deque(maxlen=max_snapshots)
        self._start_time: Optional[float] = None
        self._request_count = 0
        self._rejection_count = 0
        self._error_count = 0
        
        # Per-second tracking
        self._second_requests: Dict[int, int] = {}
    
    def record_snapshot(
        self,
        current_limit: int,
        in_flight: int,
        p50_latency_ms: float,
        p95_latency_ms: float,
        p99_latency_ms: float,
        sample_count: int,
        requests_per_second: float = 0.0,
        rejection_rate: float = 0.0,
        error_rate: float = 0.0,
    ) -> None:
        """Record a metrics snapshot."""
        if self._start_time is None:
            self._start_time = time.time()
        
        snapshot = MetricsSnapshot(
            timestamp=time.time(),
            current_limit=current_limit,
            in_flight=in_flight,
            p50_latency_ms=p50_latency_ms,
            p95_latency_ms=p95_latency_ms,
            p99_latency_ms=p99_latency_ms,
            requests_per_second=requests_per_second,
            rejection_rate=rejection_rate,
            error_rate=error_rate,
            sample_count=sample_count,
        )
        self._snapshots.append(snapshot)
    
    def record_request(self, rejected: bool = False, error: bool = False) -> None:
        """Record a request for throughput tracking."""
        self._request_count += 1
        if rejected:
            self._rejection_count += 1
        if error:
            self._error_count += 1
        
        # Track per-second
        second = int(time.time())
        self._second_requests[second] = self._second_requests.get(second, 0) + 1
    
    def get_rps(self, window_s: int = 5) -> float:
        """Get requests per second over recent window."""
        now = int(time.time())
        total = sum(
            count for sec, count in self._second_requests.items()
            if now - sec < window_s
        )
        return total / window_s
    
    def get_summary(self) -> MetricsSummary:
        """Calculate summary statistics from collected snapshots."""
        if not self._snapshots:
            return MetricsSummary(
                duration_s=0, total_requests=0, successful_requests=0,
                rejected_requests=0, error_requests=0, avg_rps=0, peak_rps=0,
                avg_p50_ms=0, avg_p95_ms=0, avg_p99_ms=0, max_latency_ms=0,
                initial_limit=0, final_limit=0, min_limit=0, max_limit=0,
                avg_limit=0, limit_changes=0, rejection_rate=0, error_rate=0,
            )
        
        snapshots = list(self._snapshots)
        
        # Duration
        duration = snapshots[-1].timestamp - snapshots[0].timestamp
        if duration <= 0:
            duration = 1.0
        
        # Limit statistics
        limits = [s.current_limit for s in snapshots]
        limit_changes = sum(
            1 for i in range(1, len(limits))
            if limits[i] != limits[i-1]
        )
        
        # Latency statistics (filter out zeros)
        p50s = [s.p50_latency_ms for s in snapshots if s.sample_count > 0]
        p95s = [s.p95_latency_ms for s in snapshots if s.sample_count > 0]
        p99s = [s.p99_latency_ms for s in snapshots if s.sample_count > 0]
        
        # RPS
        rps_values = [s.requests_per_second for s in snapshots if s.requests_per_second > 0]
        
        successful = self._request_count - self._rejection_count - self._error_count
        
        return MetricsSummary(
            duration_s=duration,
            total_requests=self._request_count,
            successful_requests=max(0, successful),
            rejected_requests=self._rejection_count,
            error_requests=self._error_count,
            avg_rps=self._request_count / duration if duration > 0 else 0,
            peak_rps=max(rps_values) if rps_values else 0,
            avg_p50_ms=sum(p50s) / len(p50s) if p50s else 0,
            avg_p95_ms=sum(p95s) / len(p95s) if p95s else 0,
            avg_p99_ms=sum(p99s) / len(p99s) if p99s else 0,
            max_latency_ms=max(p99s) if p99s else 0,
            initial_limit=limits[0] if limits else 0,
            final_limit=limits[-1] if limits else 0,
            min_limit=min(limits) if limits else 0,
            max_limit=max(limits) if limits else 0,
            avg_limit=sum(limits) / len(limits) if limits else 0,
            limit_changes=limit_changes,
            rejection_rate=self._rejection_count / self._request_count if self._request_count > 0 else 0,
            error_rate=self._error_count / self._request_count if self._request_count > 0 else 0,
        )
    
    def get_recent_snapshots(self, count: int = 10) -> List[MetricsSnapshot]:
        """Get the most recent snapshots."""
        return list(self._snapshots)[-count:]
    
    def reset(self) -> None:
        """Reset all collected metrics."""
        self._snapshots.clear()
        self._start_time = None
        self._request_count = 0
        self._rejection_count = 0
        self._error_count = 0
        self._second_requests.clear()
    
    def export_to_json(self, filepath: str) -> None:
        """Export all snapshots to JSON file."""
        data = {
            'summary': self.get_summary().to_dict(),
            'snapshots': [
                {
                    'timestamp': s.timestamp,
                    'limit': s.current_limit,
                    'in_flight': s.in_flight,
                    'p95_ms': s.p95_latency_ms,
                    'rps': s.requests_per_second,
                    'rejection_rate': s.rejection_rate,
                }
                for s in self._snapshots
            ],
        }
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)


class ConsoleReporter:
    """
    Real-time console output for metrics.
    
    Displays a live-updating status line showing:
    - Current limit
    - P95 latency
    - Throughput
    - Rejection rate
    """
    
    def __init__(self, update_interval_s: float = 1.0):
        self.update_interval_s = update_interval_s
        self._last_update = 0.0
    
    def should_update(self) -> bool:
        """Check if enough time has passed for an update."""
        now = time.time()
        if now - self._last_update >= self.update_interval_s:
            self._last_update = now
            return True
        return False
    
    def format_status_line(
        self,
        elapsed_s: float,
        current_limit: int,
        in_flight: int,
        p95_latency_ms: float,
        rps: float,
        rejection_rate: float,
        error_rate: float,
    ) -> str:
        """Format a status line for console output."""
        return (
            f"\r[{elapsed_s:6.1f}s] "
            f"Limit: {current_limit:3d} | "
            f"InFlight: {in_flight:3d} | "
            f"P95: {p95_latency_ms:6.1f}ms | "
            f"RPS: {rps:6.1f} | "
            f"Reject: {rejection_rate:5.1%} | "
            f"Errors: {error_rate:5.1%}"
        )
    
    def print_status(
        self,
        elapsed_s: float,
        current_limit: int,
        in_flight: int,
        p95_latency_ms: float,
        rps: float,
        rejection_rate: float,
        error_rate: float,
    ) -> None:
        """Print status line (overwrites previous line)."""
        line = self.format_status_line(
            elapsed_s, current_limit, in_flight,
            p95_latency_ms, rps, rejection_rate, error_rate,
        )
        print(line, end='', flush=True)
    
    def print_final(self, summary: MetricsSummary) -> None:
        """Print final summary."""
        print("\n")
        print("=" * 60)
        print("SIMULATION COMPLETE")
        print("=" * 60)
        print(f"Duration:        {summary.duration_s:.1f}s")
        print(f"Total Requests:  {summary.total_requests}")
        print(f"Successful:      {summary.successful_requests}")
        print(f"Rejected:        {summary.rejected_requests} ({summary.rejection_rate:.1%})")
        print(f"Errors:          {summary.error_requests} ({summary.error_rate:.1%})")
        print()
        print("Latency:")
        print(f"  P50:           {summary.avg_p50_ms:.1f}ms")
        print(f"  P95:           {summary.avg_p95_ms:.1f}ms")
        print(f"  P99:           {summary.avg_p99_ms:.1f}ms")
        print(f"  Max:           {summary.max_latency_ms:.1f}ms")
        print()
        print("Limit:")
        print(f"  Initial:       {summary.initial_limit}")
        print(f"  Final:         {summary.final_limit}")
        print(f"  Range:         {summary.min_limit} - {summary.max_limit}")
        print(f"  Average:       {summary.avg_limit:.1f}")
        print(f"  Adjustments:   {summary.limit_changes}")
        print()
        print(f"Throughput:      {summary.avg_rps:.1f} req/s (peak: {summary.peak_rps:.1f})")
        print("=" * 60)
