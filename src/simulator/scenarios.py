"""
Predefined test scenarios for demonstrating adaptive limiter behavior.

Each scenario is designed to show specific aspects of the control loop:
- Steady state: Normal operation
- Traffic spike: Sudden load increase
- Backend degradation: Slow backend
- Recovery: Return to normal after issues
- Chaos: Combined problems
"""

from dataclasses import dataclass
from typing import List, Dict

from .workload import (
    WorkloadConfig,
    TrafficPattern,
    LatencyDistribution,
)


@dataclass
class Scenario:
    """A test scenario with configuration and expected behavior."""
    name: str
    description: str
    workload_config: WorkloadConfig
    expected_behavior: str
    key_metrics: List[str]


def get_steady_state_scenario() -> Scenario:
    """Normal traffic at moderate load."""
    return Scenario(
        name="steady_state",
        description="Constant traffic at 80 RPS, normal backend latency",
        workload_config=WorkloadConfig(
            base_rps=80.0,
            pattern=TrafficPattern.STEADY,
            latency_distribution=LatencyDistribution.NORMAL,
            base_latency_ms=20.0,
            latency_stddev_ms=5.0,
            base_error_rate=0.001,
            duration_s=60.0,
            enable_overload_simulation=True,
            overload_threshold=50,
        ),
        expected_behavior=(
            "Limit should stabilize around 40-60 (below overload threshold). "
            "P95 latency should stay around 30ms. Minimal limit oscillation."
        ),
        key_metrics=["limit_stability", "p95_latency", "throughput"],
    )


def get_traffic_spike_scenario() -> Scenario:
    """Traffic bursts to test rapid adaptation."""
    return Scenario(
        name="traffic_spike",
        description="Periodic traffic bursts at 5x normal load",
        workload_config=WorkloadConfig(
            base_rps=50.0,
            max_rps=250.0,
            pattern=TrafficPattern.BURST,
            burst_multiplier=5.0,
            burst_duration_s=5.0,
            burst_interval_s=20.0,
            latency_distribution=LatencyDistribution.NORMAL,
            base_latency_ms=15.0,
            latency_stddev_ms=5.0,
            base_error_rate=0.01,
            duration_s=120.0,
            enable_overload_simulation=True,
            overload_threshold=40,
        ),
        expected_behavior=(
            "During bursts: limit should decrease to prevent overload. "
            "After bursts: limit should recover. Reject excess rather than timeout."
        ),
        key_metrics=["rejection_rate", "recovery_time", "max_latency"],
    )


def get_backend_degradation_scenario() -> Scenario:
    """Backend gets progressively slower."""
    return Scenario(
        name="backend_degradation",
        description="Backend latency increases over time (database saturation)",
        workload_config=WorkloadConfig(
            base_rps=60.0,
            pattern=TrafficPattern.STEADY,
            latency_distribution=LatencyDistribution.DEGRADING,
            base_latency_ms=15.0,
            latency_stddev_ms=5.0,
            base_error_rate=0.02,
            duration_s=90.0,
            enable_overload_simulation=True,
            overload_threshold=30,
        ),
        expected_behavior=(
            "Limit should progressively decrease as backend slows. "
            "Should maintain acceptable P95 despite degradation."
        ),
        key_metrics=["limit_trend", "p95_latency", "goodput"],
    )


def get_bimodal_latency_scenario() -> Scenario:
    """Mix of fast and slow requests (cache hit/miss)."""
    return Scenario(
        name="bimodal_latency",
        description="80% fast requests, 20% slow requests (like cache hit/miss)",
        workload_config=WorkloadConfig(
            base_rps=100.0,
            pattern=TrafficPattern.STEADY,
            latency_distribution=LatencyDistribution.BIMODAL,
            base_latency_ms=10.0,  # Fast path
            latency_stddev_ms=5.0,
            base_error_rate=0.005,
            duration_s=60.0,
            enable_overload_simulation=True,
            overload_threshold=60,
        ),
        expected_behavior=(
            "Limit should account for slow requests in P95. "
            "Should not oscillate due to occasional slow requests."
        ),
        key_metrics=["limit_variance", "p95_vs_p50_ratio"],
    )


def get_ramp_up_scenario() -> Scenario:
    """Traffic gradually increases (marketing campaign, morning traffic)."""
    return Scenario(
        name="ramp_up",
        description="Traffic ramps from 20 to 200 RPS over duration",
        workload_config=WorkloadConfig(
            base_rps=100.0,
            min_rps=20.0,
            max_rps=200.0,
            pattern=TrafficPattern.RAMP_UP,
            latency_distribution=LatencyDistribution.NORMAL,
            base_latency_ms=20.0,
            latency_stddev_ms=8.0,
            base_error_rate=0.01,
            duration_s=120.0,
            enable_overload_simulation=True,
            overload_threshold=50,
        ),
        expected_behavior=(
            "Limit should increase initially (low load), then decrease "
            "as load increases past capacity. Graceful degradation."
        ),
        key_metrics=["limit_trajectory", "rejection_vs_timeout_ratio"],
    )


def get_chaos_scenario() -> Scenario:
    """Random spikes and failures."""
    return Scenario(
        name="chaos",
        description="Random traffic spikes and error bursts",
        workload_config=WorkloadConfig(
            base_rps=80.0,
            min_rps=30.0,
            max_rps=300.0,
            pattern=TrafficPattern.CHAOS,
            latency_distribution=LatencyDistribution.EXPONENTIAL,
            base_latency_ms=25.0,
            latency_stddev_ms=15.0,
            base_error_rate=0.05,  # Higher baseline errors
            duration_s=90.0,
            enable_overload_simulation=True,
            overload_threshold=40,
        ),
        expected_behavior=(
            "Limit should respond to spikes but not overreact. "
            "High errors should trigger backoff. Overall stability."
        ),
        key_metrics=["max_limit_change", "error_triggered_backoffs", "stability"],
    )


def get_recovery_scenario() -> Scenario:
    """Test recovery after overload."""
    return Scenario(
        name="recovery",
        description="Moderate load after initial spike",
        workload_config=WorkloadConfig(
            base_rps=40.0,  # Moderate
            max_rps=150.0,
            pattern=TrafficPattern.RAMP_DOWN,  # Starts high, reduces
            latency_distribution=LatencyDistribution.NORMAL,
            base_latency_ms=18.0,
            latency_stddev_ms=6.0,
            base_error_rate=0.01,
            duration_s=60.0,
            enable_overload_simulation=True,
            overload_threshold=35,
        ),
        expected_behavior=(
            "Should start stressed (low limit), then recover. "
            "Additive increase should be visible as load decreases."
        ),
        key_metrics=["recovery_time", "limit_increase_rate"],
    )


def get_stress_test_scenario() -> Scenario:
    """Maximum load to find breaking point."""
    return Scenario(
        name="stress_test",
        description="Maximum sustained load (breaking point test)",
        workload_config=WorkloadConfig(
            base_rps=300.0,
            pattern=TrafficPattern.STEADY,
            latency_distribution=LatencyDistribution.NORMAL,
            base_latency_ms=15.0,
            latency_stddev_ms=5.0,
            base_error_rate=0.02,
            duration_s=60.0,
            enable_overload_simulation=True,
            overload_threshold=30,
            overload_latency_factor=3.0,  # More aggressive overload penalty
        ),
        expected_behavior=(
            "Should stabilize at minimum limit. High rejection rate. "
            "Demonstrates protection against overload."
        ),
        key_metrics=["rejection_rate", "limit_floor", "backend_protection"],
    )


# All scenarios
ALL_SCENARIOS: Dict[str, Scenario] = {
    "steady_state": get_steady_state_scenario(),
    "traffic_spike": get_traffic_spike_scenario(),
    "backend_degradation": get_backend_degradation_scenario(),
    "bimodal_latency": get_bimodal_latency_scenario(),
    "ramp_up": get_ramp_up_scenario(),
    "chaos": get_chaos_scenario(),
    "recovery": get_recovery_scenario(),
    "stress_test": get_stress_test_scenario(),
}


def list_scenarios() -> List[str]:
    """List all available scenario names."""
    return list(ALL_SCENARIOS.keys())


def get_scenario(name: str) -> Scenario:
    """Get a scenario by name."""
    if name not in ALL_SCENARIOS:
        available = ", ".join(ALL_SCENARIOS.keys())
        raise ValueError(f"Unknown scenario: {name}. Available: {available}")
    return ALL_SCENARIOS[name]


def describe_scenarios() -> str:
    """Get a formatted description of all scenarios."""
    lines = ["Available Scenarios:", "=" * 50]
    
    for name, scenario in ALL_SCENARIOS.items():
        lines.append(f"\n{name}:")
        lines.append(f"  {scenario.description}")
        lines.append(f"  Expected: {scenario.expected_behavior[:80]}...")
    
    return "\n".join(lines)
