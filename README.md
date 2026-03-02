# Adaptive Concurrency Limiter

A Python implementation demonstrating **control-loop thinking** with the AIMD (Additive Increase, Multiplicative Decrease) algorithm. The system automatically adjusts concurrency limits based on real-time latency and error feedback.

## Overview

Static concurrency limits fail in production because:
- Traffic fluctuates (spikes, lulls)
- Backend capacity changes (degradation, scaling)
- One size doesn't fit all workloads

This limiter uses a **feedback control loop** to dynamically find the optimal concurrency level:

```
┌─────────────────────────────────────────────────────────────┐
│                     CONTROL LOOP                            │
│                                                             │
│   ┌─────────┐    ┌──────────┐    ┌─────────────────────┐   │
│   │ Request │───►│ Acquire  │───►│ Execute + Measure   │   │
│   │ Arrives │    │ Permit   │    │ Latency             │   │
│   └─────────┘    └──────────┘    └─────────────────────┘   │
│                        ▲                     │              │
│                        │                     ▼              │
│                  ┌─────┴─────┐    ┌─────────────────────┐   │
│                  │  Adjust   │◄───│ Sliding Window      │   │
│                  │  Limit    │    │ (P95, errors)       │   │
│                  └───────────┘    └─────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## AIMD Algorithm

The controller uses **Additive Increase, Multiplicative Decrease**:

| Condition | Action | Formula |
|-----------|--------|---------|
| P95 < 80% of target | **Increase** | `limit += 1` |
| P95 > target | **Decrease** | `limit *= 0.9` |
| Error rate > 5% | **Backoff** | `limit *= 0.5` |
| In acceptable range | **Hold** | No change |

This is the same algorithm that powers TCP congestion control—proven stable and fair.

## Quick Start

```bash
# Clone and navigate
cd adaptive-limiter

# Run with Python 3.10+
python -m src.main

# Run a specific scenario
python -m src.main --scenario traffic_spike

# List all scenarios
python -m src.main --list-scenarios

# Custom parameters
python -m src.main --custom --rps 150 --duration 90 --target-latency 30
```

## Project Structure

```
adaptive-limiter/
├── src/
│   ├── main.py              # Entry point with CLI
│   ├── limiter/
│   │   ├── controller.py    # AIMD control loop
│   │   ├── semaphore.py     # Adaptive semaphore
│   │   └── window.py        # Sliding window stats
│   ├── simulator/
│   │   ├── workload.py      # Traffic generation
│   │   └── scenarios.py     # Test scenarios
│   └── metrics/
│       └── collector.py     # Telemetry
├── tests/
│   └── test_limiter.py
└── docs/
    ├── GETTING_STARTED.md   # Beginner guide
    ├── ENGINEERING_REVIEW.md # Technical review
    └── PRODUCTION_DEPLOYMENT.md
```

## Available Scenarios

| Scenario | Description | Tests |
|----------|-------------|-------|
| `steady_state` | Constant moderate load | Stability, convergence |
| `traffic_spike` | Periodic bursts at 5x | Burst handling, recovery |
| `backend_degradation` | Progressively slower backend | Adaptation to degradation |
| `bimodal_latency` | 80% fast / 20% slow | Handling P95 outliers |
| `ramp_up` | Gradually increasing load | Proactive adjustment |
| `chaos` | Random spikes and errors | Stability under chaos |
| `stress_test` | Maximum load | Protection, rejection |

## Example Output

```
============================================================
ADAPTIVE CONCURRENCY LIMITER - SIMULATION
============================================================
Target Latency:  50.0ms
Initial Limit:   20
Limit Range:     [5, 200]
Duration:        60.0s
Base RPS:        80.0
Pattern:         steady
============================================================

Running simulation...

[  5.0s] Limit:  25 | InFlight:  22 | P95:   32.1ms | RPS:   78.4 | Reject:  0.0% | Errors:  0.1%
[ 10.0s] Limit:  30 | InFlight:  28 | P95:   35.2ms | RPS:   81.2 | Reject:  0.0% | Errors:  0.1%
[ 15.0s] Limit:  35 | InFlight:  33 | P95:   38.4ms | RPS:   79.8 | Reject:  0.0% | Errors:  0.1%
...
[ 60.0s] Limit:  42 | InFlight:  40 | P95:   45.3ms | RPS:   80.1 | Reject:  0.0% | Errors:  0.1%

============================================================
SIMULATION COMPLETE
============================================================
Duration:        60.0s
Total Requests:  4832
Successful:      4810
Rejected:        17 (0.4%)
Errors:          5 (0.1%)

Latency:
  P50:           22.1ms
  P95:           41.2ms
  P99:           52.4ms

Limit:
  Initial:       20
  Final:         42
  Range:         20 - 45
  Adjustments:   24
```

## Using as a Library

```python
from src.limiter import AdaptiveLimiter

# Create limiter
limiter = AdaptiveLimiter(
    target_latency_ms=50.0,
    min_limit=5,
    max_limit=100,
    initial_limit=20,
)

# Start control loop
await limiter.start()

# Use in request handler
async def handle_request(request):
    async with limiter.acquire() as permit:
        if not permit.acquired:
            return Response(status=429)  # Rejected
        
        # Process request
        result = await process(request)
        return result

# On shutdown
await limiter.stop()
```

## Key Insights

1. **Why AIMD works**: Additive increase is conservative (slow growth), multiplicative decrease is aggressive (fast recovery). This prevents oscillation.

2. **Why sliding windows**: Point-in-time measurements are noisy. A 10-second window smooths outliers while still being responsive.

3. **Why rate-limit changes**: Even with AIMD, rapid changes cause oscillation. Limiting change to 20%/second adds stability.

4. **Why safety bounds**: Minimum prevents starvation. Maximum prevents resource exhaustion. Both are essential.

## Requirements

- Python 3.10+ (using asyncio, dataclasses, type hints)
- No external dependencies (pure Python standard library)

## License

MIT
# adaptive-limiter
