"""
Workload Generator - Simulates various traffic patterns.

Generates synthetic request loads with configurable:
- Request rate (RPS)
- Latency distribution (normal, exponential, bimodal)
- Error injection
- Traffic patterns (steady, burst, ramp, chaos)

Design Rationale:
- Using asyncio for high concurrency without threads
- Poisson arrival for realistic traffic
- Configurable latency to simulate backend behavior
"""

import asyncio
import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, List, Awaitable


class TrafficPattern(Enum):
    """Traffic load patterns."""
    STEADY = "steady"          # Constant RPS
    BURST = "burst"            # Periodic bursts
    RAMP_UP = "ramp_up"        # Gradually increasing
    RAMP_DOWN = "ramp_down"    # Gradually decreasing
    SINE = "sine"              # Sinusoidal oscillation
    CHAOS = "chaos"            # Random spikes


class LatencyDistribution(Enum):
    """Backend latency distributions."""
    CONSTANT = "constant"      # Fixed latency
    NORMAL = "normal"          # Gaussian distribution
    EXPONENTIAL = "exponential"  # Heavy tail
    BIMODAL = "bimodal"        # Fast/slow requests
    DEGRADING = "degrading"    # Gets slower over time


@dataclass
class WorkloadConfig:
    """Configuration for workload generation."""
    
    # Request rate
    base_rps: float = 100.0
    max_rps: float = 500.0
    min_rps: float = 10.0
    
    # Traffic pattern
    pattern: TrafficPattern = TrafficPattern.STEADY
    burst_multiplier: float = 5.0
    burst_duration_s: float = 2.0
    burst_interval_s: float = 10.0
    
    # Latency simulation
    latency_distribution: LatencyDistribution = LatencyDistribution.NORMAL
    base_latency_ms: float = 20.0
    latency_stddev_ms: float = 10.0
    
    # Error injection
    base_error_rate: float = 0.01
    
    # Duration
    duration_s: float = 60.0
    
    # Overload simulation (latency increases with concurrency)
    enable_overload_simulation: bool = True
    overload_threshold: int = 50  # Concurrency above which latency increases
    overload_latency_factor: float = 2.0


@dataclass
class RequestResult:
    """Result of a simulated request."""
    latency_ms: float
    is_error: bool
    was_rejected: bool
    timestamp: float
    concurrency_at_start: int


class BackendSimulator:
    """
    Simulates a backend service with realistic latency behavior.
    
    The simulator models:
    - Base latency with distribution
    - Overload behavior (latency increases under high concurrency)
    - Random errors
    - Degradation over time (optional)
    """
    
    def __init__(self, config: WorkloadConfig):
        self.config = config
        self._current_concurrency = 0
        self._start_time = time.time()
        self._lock = asyncio.Lock()
    
    @property
    def current_concurrency(self) -> int:
        return self._current_concurrency
    
    async def handle_request(self) -> tuple[float, bool]:
        """
        Simulate handling a request.
        
        Returns:
            Tuple of (latency_ms, is_error)
        """
        async with self._lock:
            self._current_concurrency += 1
            concurrency = self._current_concurrency
        
        try:
            # Calculate base latency
            latency_ms = self._calculate_latency(concurrency)
            
            # Check if error
            is_error = random.random() < self._calculate_error_rate(concurrency)
            
            # Simulate the work
            await asyncio.sleep(latency_ms / 1000.0)
            
            return latency_ms, is_error
            
        finally:
            async with self._lock:
                self._current_concurrency -= 1
    
    def _calculate_latency(self, concurrency: int) -> float:
        """Calculate latency based on distribution and load."""
        cfg = self.config
        
        # Base latency from distribution
        if cfg.latency_distribution == LatencyDistribution.CONSTANT:
            base = cfg.base_latency_ms
            
        elif cfg.latency_distribution == LatencyDistribution.NORMAL:
            base = max(1.0, random.gauss(cfg.base_latency_ms, cfg.latency_stddev_ms))
            
        elif cfg.latency_distribution == LatencyDistribution.EXPONENTIAL:
            base = random.expovariate(1.0 / cfg.base_latency_ms)
            
        elif cfg.latency_distribution == LatencyDistribution.BIMODAL:
            # 80% fast, 20% slow
            if random.random() < 0.8:
                base = random.gauss(cfg.base_latency_ms, cfg.latency_stddev_ms / 2)
            else:
                base = random.gauss(cfg.base_latency_ms * 5, cfg.latency_stddev_ms * 2)
            base = max(1.0, base)
            
        elif cfg.latency_distribution == LatencyDistribution.DEGRADING:
            # Latency increases over time
            elapsed = time.time() - self._start_time
            degradation = 1.0 + (elapsed / cfg.duration_s)
            base = max(1.0, random.gauss(cfg.base_latency_ms * degradation, cfg.latency_stddev_ms))
            
        else:
            base = cfg.base_latency_ms
        
        # Apply overload factor
        if cfg.enable_overload_simulation and concurrency > cfg.overload_threshold:
            excess = concurrency - cfg.overload_threshold
            # Quadratic increase - gets much worse quickly
            overload_factor = 1.0 + (excess * cfg.overload_latency_factor / 10.0) ** 2
            base *= min(overload_factor, 50.0)  # Cap at 50x
        
        return max(1.0, base)
    
    def _calculate_error_rate(self, concurrency: int) -> float:
        """Calculate error rate based on load."""
        cfg = self.config
        error_rate = cfg.base_error_rate
        
        # Errors increase under overload
        if cfg.enable_overload_simulation and concurrency > cfg.overload_threshold:
            excess = concurrency - cfg.overload_threshold
            # Error rate increases with excess concurrency
            error_rate += (excess / cfg.overload_threshold) * 0.1
        
        return min(error_rate, 0.5)  # Cap at 50%


class TrafficGenerator:
    """
    Generates traffic according to configured patterns.
    
    Sends requests at varying rates based on pattern configuration.
    """
    
    def __init__(self, config: WorkloadConfig):
        self.config = config
        self._start_time: Optional[float] = None
        self._last_burst: float = 0
    
    def get_current_rps(self, elapsed_s: float) -> float:
        """Get current RPS based on pattern and elapsed time."""
        cfg = self.config
        
        if cfg.pattern == TrafficPattern.STEADY:
            return cfg.base_rps
        
        elif cfg.pattern == TrafficPattern.BURST:
            # Check if in burst period
            time_since_burst = elapsed_s % cfg.burst_interval_s
            if time_since_burst < cfg.burst_duration_s:
                return cfg.base_rps * cfg.burst_multiplier
            return cfg.base_rps
        
        elif cfg.pattern == TrafficPattern.RAMP_UP:
            progress = min(1.0, elapsed_s / cfg.duration_s)
            return cfg.min_rps + (cfg.max_rps - cfg.min_rps) * progress
        
        elif cfg.pattern == TrafficPattern.RAMP_DOWN:
            progress = min(1.0, elapsed_s / cfg.duration_s)
            return cfg.max_rps - (cfg.max_rps - cfg.min_rps) * progress
        
        elif cfg.pattern == TrafficPattern.SINE:
            import math
            # Complete one cycle over the duration
            phase = (elapsed_s / cfg.duration_s) * 2 * math.pi
            normalized = (math.sin(phase) + 1) / 2  # 0 to 1
            return cfg.min_rps + (cfg.max_rps - cfg.min_rps) * normalized
        
        elif cfg.pattern == TrafficPattern.CHAOS:
            # Random spikes
            if random.random() < 0.1:  # 10% chance of spike per second
                return random.uniform(cfg.base_rps, cfg.max_rps)
            return cfg.base_rps
        
        return cfg.base_rps
    
    def get_inter_arrival_time(self, current_rps: float) -> float:
        """
        Get time until next request (Poisson arrival).
        
        Uses exponential distribution for realistic traffic.
        """
        if current_rps <= 0:
            return 1.0
        
        # Exponential inter-arrival time for Poisson process
        return random.expovariate(current_rps)


class WorkloadSimulator:
    """
    Complete workload simulator combining traffic generation and backend simulation.
    
    Example:
        config = WorkloadConfig(
            base_rps=100,
            pattern=TrafficPattern.BURST,
            duration_s=60,
        )
        
        simulator = WorkloadSimulator(config)
        
        async def on_request(result: RequestResult):
            await limiter.record(result.latency_ms, result.is_error)
        
        await simulator.run(
            request_handler=limiter.semaphore.acquire,
            on_complete=on_request,
        )
    """
    
    def __init__(self, config: WorkloadConfig):
        self.config = config
        self.backend = BackendSimulator(config)
        self.traffic = TrafficGenerator(config)
        
        # Stats
        self._total_requests = 0
        self._successful_requests = 0
        self._rejected_requests = 0
        self._error_requests = 0
        self._results: List[RequestResult] = []
        
        self._running = False
    
    @property
    def stats(self) -> dict:
        return {
            'total_requests': self._total_requests,
            'successful_requests': self._successful_requests,
            'rejected_requests': self._rejected_requests,
            'error_requests': self._error_requests,
        }
    
    async def run(
        self,
        acquire_permit: Callable[[], Awaitable[bool]],
        release_permit: Callable[[], None],
        record_result: Optional[Callable[[float, bool], Awaitable[None]]] = None,
        on_tick: Optional[Callable[[float, float, int], None]] = None,
    ) -> List[RequestResult]:
        """
        Run the workload simulation.
        
        Args:
            acquire_permit: Async function to acquire a permit (returns True if granted)
            release_permit: Function to release a permit
            record_result: Async function to record latency and error
            on_tick: Callback for progress (elapsed_s, current_rps, total_requests)
            
        Returns:
            List of request results
        """
        self._running = True
        self._results = []
        start_time = time.time()
        
        tasks: List[asyncio.Task] = []
        
        try:
            while self._running:
                elapsed = time.time() - start_time
                
                if elapsed >= self.config.duration_s:
                    break
                
                current_rps = self.traffic.get_current_rps(elapsed)
                
                # Report progress
                if on_tick:
                    on_tick(elapsed, current_rps, self._total_requests)
                
                # Send requests at current rate
                inter_arrival = self.traffic.get_inter_arrival_time(current_rps)
                await asyncio.sleep(inter_arrival)
                
                # Start request (don't await - fire and forget)
                task = asyncio.create_task(
                    self._handle_request(acquire_permit, release_permit, record_result)
                )
                tasks.append(task)
                
                # Clean up completed tasks periodically
                if len(tasks) > 1000:
                    done = [t for t in tasks if t.done()]
                    tasks = [t for t in tasks if not t.done()]
        
        finally:
            self._running = False
            
            # Wait for all pending requests
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        
        return self._results
    
    async def _handle_request(
        self,
        acquire_permit: Callable[[], Awaitable[bool]],
        release_permit: Callable[[], None],
        record_result: Optional[Callable[[float, bool], Awaitable[None]]],
    ) -> None:
        """Handle a single simulated request."""
        self._total_requests += 1
        timestamp = time.time()
        concurrency = self.backend.current_concurrency
        
        # Try to acquire permit
        try:
            acquired = await acquire_permit()
        except asyncio.TimeoutError:
            acquired = False
        
        if not acquired:
            # Rejected - no permit available
            self._rejected_requests += 1
            result = RequestResult(
                latency_ms=0,
                is_error=False,
                was_rejected=True,
                timestamp=timestamp,
                concurrency_at_start=concurrency,
            )
            self._results.append(result)
            return
        
        try:
            # Execute request
            latency_ms, is_error = await self.backend.handle_request()
            
            if is_error:
                self._error_requests += 1
            else:
                self._successful_requests += 1
            
            # Record result
            if record_result:
                await record_result(latency_ms, is_error)
            
            result = RequestResult(
                latency_ms=latency_ms,
                is_error=is_error,
                was_rejected=False,
                timestamp=timestamp,
                concurrency_at_start=concurrency,
            )
            self._results.append(result)
            
        finally:
            release_permit()
    
    def stop(self) -> None:
        """Stop the simulator."""
        self._running = False
