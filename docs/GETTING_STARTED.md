# Getting Started with the Adaptive Concurrency Limiter

A beginner-friendly guide to understanding and using this project.

## What Problem Does This Solve?

Imagine you run a coffee shop. If too many customers crowd the counter at once:
- Service slows down (high latency)
- Orders get mixed up (errors)
- People leave frustrated (timeouts)

The solution? **A queue with adaptive capacity.**

This code does the same thing for computer systems. It controls how many requests can run at the same time, and *automatically adjusts* based on how well things are going.

## The Big Idea: Control Loops

A **control loop** is like a thermostat:

```
┌──────────┐     ┌─────────┐     ┌──────────┐
│  Target  │────►│ Compare │────►│  Action  │
│  (68°F)  │     │ to Real │     │ (Heat on)│
└──────────┘     └─────────┘     └──────────┘
      ▲                               │
      │                               ▼
      │                        ┌──────────┐
      └────────────────────────│ Measure  │
                               │ (67°F)   │
                               └──────────┘
```

Our limiter does the same thing:
- **Target**: P95 latency should be ≤50ms
- **Measure**: Actual P95 latency over last 10 seconds
- **Action**: Increase or decrease the concurrency limit

## Key Concepts Explained

### Concurrency Limit

The maximum number of requests that can run **at the same time**.

```
Limit = 5

[Request 1] - Running
[Request 2] - Running
[Request 3] - Running
[Request 4] - Running
[Request 5] - Running
[Request 6] - WAITING (no room)
[Request 7] - WAITING
```

When a running request finishes, a waiting one can start.

### Semaphore

A **counting lock** that enforces the limit. Think of it as tickets:

```python
# Create semaphore with 5 permits
sem = AdaptiveSemaphore(initial_limit=5)

# Take a permit (blocks if none available)
await sem.acquire()

# ... do work ...

# Return the permit
sem.release()
```

The special thing about our semaphore: you can change the limit *while it's running*!

```python
# Start with 5
sem = AdaptiveSemaphore(5)

# Later, increase to 10
await sem.set_limit(10)
```

### Sliding Window

We measure latency over a *time window* (not just the last request):

```
Time:    0s    2s    4s    6s    8s    10s   12s
Window:  |<-------- 10 seconds -------->|
                                        |<-------- 10 seconds -------->|
```

This smooths out noise. One slow request doesn't trigger a panic.

### AIMD Algorithm

**A**dditive **I**ncrease, **M**ultiplicative **D**ecrease.

| If... | Then... | Why? |
|-------|---------|------|
| Things are great (low latency) | Add 1 to limit | Grow slowly |
| Things are bad (high latency) | Multiply limit by 0.9 | Shrink faster |
| Things are terrible (many errors) | Multiply by 0.5 | Emergency retreat |

Why the asymmetry?
- **Growing slow** prevents overshooting
- **Shrinking fast** escapes problems quickly

This is the same algorithm that powers TCP congestion control on the internet!

## Project Structure

```
adaptive-limiter/
├── src/
│   ├── main.py              # CLI entry point
│   ├── limiter/
│   │   ├── window.py        # Sliding window for stats
│   │   ├── semaphore.py     # The concurrency limit enforcer
│   │   └── controller.py    # The AIMD brain
│   ├── simulator/
│   │   ├── workload.py      # Fake traffic generator
│   │   └── scenarios.py     # Test scenarios
│   └── metrics/
│       └── collector.py     # Performance tracking
├── tests/
│   └── test_limiter.py      # Unit tests
└── docs/                    # You are here!
```

## Running the Code

### Prerequisites

- Python 3.10 or newer
- No pip packages needed! (Pure Python)

### Quick Start

```bash
# Navigate to project
cd adaptive-limiter

# Run with default settings (30 seconds of steady traffic)
python -m src.main

# Run a specific scenario
python -m src.main --scenario traffic_spike

# List all scenarios
python -m src.main --list-scenarios

# Custom duration
python -m src.main --duration 60
```

### Understanding the Output

```
[   5.0s] Limit:  25 | InFlight:  22 | P95:   32.1ms | RPS:   78.4 | Reject:  0.0% | Errors:  0.1%
    │        │           │             │            │            │             │
    │        │           │             │            │            │             └── Request errors
    │        │           │             │            │            └── Rejected (no permit)
    │        │           │             │            └── Requests per second
    │        │           │             └── 95th percentile latency
    │        │           └── Currently running
    │        └── Current concurrency limit
    └── Time since start
```

**What to watch for:**
- **Limit increasing**: System is healthy, adding capacity
- **Limit decreasing**: System is stressed, backing off
- **Low reject rate**: Limiter is calibrated well
- **P95 near target**: Control loop found the sweet spot

## Code Walkthrough

### The Sliding Window

[window.py](../src/limiter/window.py) collects latency samples:

```python
class SlidingWindow:
    def __init__(self, window_size_s: float = 10.0):
        self.window_size_s = window_size_s
        self._samples = deque()  # Fast append and pop
    
    async def record(self, latency_ms: float, is_error: bool = False):
        """Add a sample to the window."""
        sample = Sample(
            timestamp=time.time(),
            latency_ms=latency_ms,
            is_error=is_error,
        )
        self._samples.append(sample)
        self._prune_old_samples()  # Remove anything older than window_size_s
    
    async def get_stats(self) -> WindowStats:
        """Calculate P50, P95, P99, error rate from window."""
        # Sort latencies and compute percentiles
        ...
```

**Why `deque`?** It's O(1) for both append (right) and pop (left). Perfect for sliding windows.

### The Adaptive Semaphore

[semaphore.py](../src/limiter/semaphore.py) controls concurrency:

```python
class AdaptiveSemaphore:
    def __init__(self, initial_limit: int = 10):
        self._limit = initial_limit
        self._available = initial_limit
        self._condition = asyncio.Condition()  # For waiting
    
    async def acquire(self, timeout: float = None) -> bool:
        """Wait for a permit. Returns False if timeout."""
        async with self._condition:
            while self._available <= 0:
                await self._condition.wait()  # Sleep until notified
            self._available -= 1
            return True
    
    async def set_limit(self, new_limit: int):
        """Change the limit dynamically."""
        async with self._condition:
            diff = new_limit - self._limit
            self._limit = new_limit
            self._available += diff
            if diff > 0:
                self._condition.notify(diff)  # Wake up waiters
```

**Key insight:** `asyncio.Condition` lets tasks sleep until notified. No busy-waiting!

### The AIMD Controller

[controller.py](../src/limiter/controller.py) runs the control loop:

```python
class AIMDController:
    async def _control_loop(self):
        """Run forever, adjusting limits every interval."""
        while self._running:
            await asyncio.sleep(self.config.control_interval_s)  # e.g., 1 second
            
            stats = await self._window.get_stats()
            old_limit = self._semaphore.limit
            
            # Decide what to do
            action, new_limit = self._decide(stats, old_limit)
            
            # Apply rate limiting (prevent wild swings)
            new_limit = self._apply_rate_limit(old_limit, new_limit)
            
            # Apply bounds (stay within min/max)
            new_limit = max(self.config.min_limit, min(self.config.max_limit, new_limit))
            
            # Update the semaphore
            await self._semaphore.set_limit(new_limit)
    
    def _decide(self, stats: WindowStats, current_limit: int):
        """AIMD decision logic."""
        # Not enough data yet
        if stats.sample_count < self.config.min_samples:
            return ControlAction.STARTUP, current_limit
        
        # High error rate → aggressive backoff
        if stats.error_rate > 0.05:  # >5% errors
            return ControlAction.BACKOFF, int(current_limit * 0.5)
        
        # High latency → multiplicative decrease
        if stats.p95_latency_ms > self.config.target_latency_ms:
            return ControlAction.DECREASE, int(current_limit * 0.9)
        
        # Low latency → additive increase
        if stats.p95_latency_ms < self.config.target_latency_ms * 0.8:
            return ControlAction.INCREASE, current_limit + 1
        
        # In acceptable range → hold steady
        return ControlAction.HOLD, current_limit
```

## Running the Tests

```bash
# From project root
python -m unittest tests.test_limiter -v
```

You should see all tests pass:
```
test_decision_backoff_on_errors ... ok
test_decision_decrease_on_high_latency ... ok
test_decision_increase_on_low_latency ... ok
...
Ran 25 tests in 0.407s
OK
```

## Common Questions

### Why not just use a fixed limit?

Fixed limits are **static** but traffic is **dynamic**:
- Morning traffic is different from midnight
- A slow database query changes everything
- New code deployments affect performance

An adaptive limit finds the right value *automatically*.

### Why P95 and not average?

Average hides outliers. P95 means "95% of requests are faster than this."

```
5 requests: 10ms, 10ms, 10ms, 10ms, 500ms

Average:    108ms  (misleading!)
P95:        500ms  (reveals the slow one)
```

We want to know about the slow requests.

### What if the control loop makes things worse?

Several safeguards:
1. **Minimum samples**: Don't adjust without enough data
2. **Rate limiting**: No more than 20% change per interval
3. **Hard bounds**: Never go below min or above max
4. **AIMD asymmetry**: Slow to grow, fast to shrink

### How do I tune the parameters?

Start with defaults, then adjust based on your system:

| Parameter | Start Here | If... Then... |
|-----------|------------|---------------|
| `target_latency_ms` | 50 | Your SLA is different → change it |
| `min_limit` | 5 | Services starts failing → raise it |
| `max_limit` | 200 | You have more capacity → raise it |
| `control_interval_s` | 1.0 | Too noisy → increase to 2s |

## Next Steps

1. **Read the code**: Start with `src/limiter/controller.py`
2. **Run scenarios**: Try `--scenario chaos` to see edge cases
3. **Add metrics**: Hook up Prometheus (see PRODUCTION_DEPLOYMENT.md)
4. **Integrate**: Add to your web framework (examples in README)

## Further Reading

- [TCP Congestion Control (Wikipedia)](https://en.wikipedia.org/wiki/TCP_congestion_control) - The origin of AIMD
- [Netflix's Concurrency Limits](https://github.com/Netflix/concurrency-limits) - Industrial-strength version
- [Little's Law](https://en.wikipedia.org/wiki/Little%27s_law) - Why Throughput = Concurrency / Latency
