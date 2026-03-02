"""
Adaptive Concurrency Limiter - Main Entry Point

Demonstrates control-loop thinking with AIMD algorithm:
- Runs simulated workloads against the adaptive limiter
- Shows real-time limit adjustments
- Reports performance metrics

Usage:
    python -m src.main                          # Run default scenario
    python -m src.main --scenario traffic_spike # Run specific scenario
    python -m src.main --list-scenarios         # List available scenarios
    python -m src.main --duration 120           # Run for 2 minutes
"""

import argparse
import asyncio
import sys
import time
from typing import Optional

# Add src to path for imports
sys.path.insert(0, '.')

from src.limiter import (
    AIMDController,
    ControllerConfig,
    ControlAction,
)
from src.simulator import (
    WorkloadSimulator,
    WorkloadConfig,
    TrafficPattern,
    LatencyDistribution,
    get_scenario,
    list_scenarios,
    describe_scenarios,
)
from src.metrics import (
    MetricsCollector,
    ConsoleReporter,
)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Adaptive Concurrency Limiter Demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                              Run default steady-state scenario
  %(prog)s --scenario traffic_spike     Test burst traffic handling
  %(prog)s --scenario chaos --duration 120   Chaos test for 2 minutes
  %(prog)s --list-scenarios             Show all available scenarios
  %(prog)s --custom --rps 200 --duration 60  Custom workload
        """,
    )
    
    parser.add_argument(
        '--scenario', '-s',
        default='steady_state',
        help='Scenario to run (default: steady_state)',
    )
    
    parser.add_argument(
        '--list-scenarios', '-l',
        action='store_true',
        help='List available scenarios and exit',
    )
    
    parser.add_argument(
        '--duration', '-d',
        type=float,
        default=None,
        help='Override scenario duration (seconds)',
    )
    
    parser.add_argument(
        '--custom',
        action='store_true',
        help='Use custom workload parameters instead of scenario',
    )
    
    # Custom workload parameters
    parser.add_argument('--rps', type=float, default=100.0, help='Base RPS for custom workload')
    parser.add_argument('--target-latency', type=float, default=50.0, help='Target P95 latency (ms)')
    parser.add_argument('--min-limit', type=int, default=5, help='Minimum concurrency limit')
    parser.add_argument('--max-limit', type=int, default=200, help='Maximum concurrency limit')
    parser.add_argument('--initial-limit', type=int, default=20, help='Starting concurrency limit')
    
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Minimal output (no live updates)',
    )
    
    parser.add_argument(
        '--export',
        type=str,
        default=None,
        help='Export results to JSON file',
    )
    
    return parser.parse_args()


async def run_simulation(
    workload_config: WorkloadConfig,
    controller_config: ControllerConfig,
    quiet: bool = False,
    export_path: Optional[str] = None,
) -> None:
    """Run the simulation with given configurations."""
    
    # Initialize components
    controller = AIMDController(
        config=controller_config,
        on_event=None if quiet else lambda e: None,
    )
    
    simulator = WorkloadSimulator(workload_config)
    collector = MetricsCollector()
    reporter = ConsoleReporter()
    
    # Start controller
    await controller.start()
    
    start_time = time.time()
    last_total = 0
    
    def on_tick(elapsed_s: float, current_rps: float, total_requests: int) -> None:
        """Called periodically during simulation."""
        nonlocal last_total
        
        if quiet:
            return
        
        if not reporter.should_update():
            return
        
        # Get current stats
        sem_stats = controller.semaphore.stats()
        
        # Calculate actual RPS
        actual_rps = (total_requests - last_total) / reporter.update_interval_s
        last_total = total_requests
        
        # Get window stats (sync version for callback)
        rejection_rate = simulator._rejected_requests / max(1, total_requests)
        error_rate = simulator._error_requests / max(1, total_requests)
        
        # Record snapshot
        collector.record_snapshot(
            current_limit=sem_stats.limit,
            in_flight=sem_stats.in_flight,
            p50_latency_ms=0,  # Will be filled from window
            p95_latency_ms=0,
            p99_latency_ms=0,
            sample_count=total_requests,
            requests_per_second=actual_rps,
            rejection_rate=rejection_rate,
            error_rate=error_rate,
        )
        
        # Print status
        reporter.print_status(
            elapsed_s=elapsed_s,
            current_limit=sem_stats.limit,
            in_flight=sem_stats.in_flight,
            p95_latency_ms=controller_config.target_latency_ms,  # Placeholder
            rps=actual_rps,
            rejection_rate=rejection_rate,
            error_rate=error_rate,
        )
    
    print("\n" + "=" * 60)
    print("ADAPTIVE CONCURRENCY LIMITER - SIMULATION")
    print("=" * 60)
    print(f"Target Latency:  {controller_config.target_latency_ms}ms")
    print(f"Initial Limit:   {controller_config.initial_limit}")
    print(f"Limit Range:     [{controller_config.min_limit}, {controller_config.max_limit}]")
    print(f"Duration:        {workload_config.duration_s}s")
    print(f"Base RPS:        {workload_config.base_rps}")
    print(f"Pattern:         {workload_config.pattern.value}")
    print("=" * 60)
    print("\nRunning simulation...")
    print()
    
    try:
        # Run simulation
        results = await simulator.run(
            acquire_permit=lambda: controller.semaphore.acquire(timeout=1.0),
            release_permit=lambda: controller.semaphore.release(),
            record_result=controller.record,
            on_tick=on_tick,
        )
        
    finally:
        await controller.stop()
    
    # Record final stats
    for r in results[-100:]:  # Sample last 100 results
        collector.record_request(rejected=r.was_rejected, error=r.is_error)
    
    # Get summary
    summary = collector.get_summary()
    
    # Update summary with actual data
    summary.total_requests = simulator._total_requests
    summary.successful_requests = simulator._successful_requests
    summary.rejected_requests = simulator._rejected_requests
    summary.error_requests = simulator._error_requests
    summary.rejection_rate = simulator._rejected_requests / max(1, simulator._total_requests)
    summary.error_rate = simulator._error_requests / max(1, simulator._total_requests)
    summary.duration_s = workload_config.duration_s
    
    # Get limit stats from controller
    controller_metrics = controller.get_metrics()
    
    # Print summary
    reporter.print_final(summary)
    
    # Print controller-specific stats
    print("\nController Statistics:")
    print(f"  Total Adjustments: {controller_metrics['total_adjustments']}")
    print(f"  Increases:         {controller_metrics['total_increases']}")
    print(f"  Decreases:         {controller_metrics['total_decreases']}")
    print(f"  Backoffs:          {controller_metrics['total_backoffs']}")
    
    # Export if requested
    if export_path:
        collector.export_to_json(export_path)
        print(f"\nResults exported to: {export_path}")


def main() -> None:
    """Main entry point."""
    args = parse_args()
    
    # List scenarios and exit
    if args.list_scenarios:
        print(describe_scenarios())
        return
    
    # Build configurations
    if args.custom:
        # Custom workload
        workload_config = WorkloadConfig(
            base_rps=args.rps,
            pattern=TrafficPattern.STEADY,
            latency_distribution=LatencyDistribution.NORMAL,
            base_latency_ms=20.0,
            duration_s=args.duration or 60.0,
            enable_overload_simulation=True,
            overload_threshold=int(args.max_limit * 0.4),
        )
    else:
        # Load scenario
        try:
            scenario = get_scenario(args.scenario)
            workload_config = scenario.workload_config
            
            print(f"\nScenario: {scenario.name}")
            print(f"Description: {scenario.description}")
            print(f"Expected: {scenario.expected_behavior}")
            
        except ValueError as e:
            print(f"Error: {e}")
            print(f"\nAvailable scenarios: {', '.join(list_scenarios())}")
            return
    
    # Override duration if specified
    if args.duration:
        workload_config.duration_s = args.duration
    
    # Controller config
    controller_config = ControllerConfig(
        target_latency_ms=args.target_latency,
        min_limit=args.min_limit,
        max_limit=args.max_limit,
        initial_limit=args.initial_limit,
    )
    
    # Run simulation
    asyncio.run(run_simulation(
        workload_config=workload_config,
        controller_config=controller_config,
        quiet=args.quiet,
        export_path=args.export,
    ))


if __name__ == '__main__':
    main()
