"""
AIMD Controller - Adaptive Increase, Multiplicative Decrease

The brain of the adaptive concurrency limiter. Runs a control loop that:
1. Samples latency percentiles from the sliding window
2. Compares against target latency
3. Adjusts the semaphore limit using AIMD algorithm
4. Emits metrics for monitoring

Design Rationale:
- AIMD is proven in TCP congestion control (stable, fair)
- Additive increase is conservative (prevents overshoot)
- Multiplicative decrease is aggressive (fast recovery from overload)
- Rate limiting prevents oscillation from rapid changes

Key Parameters:
- alpha: additive increase amount (default 1)
- beta: multiplicative decrease factor (default 0.9)
- target_latency_ms: P95 latency target (default 50ms)
- control_interval_s: how often to adjust (default 1s)
"""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, List

from .semaphore import AdaptiveSemaphore
from .window import SlidingWindow, WindowStats


class ControlAction(Enum):
    """Action taken by the controller."""
    INCREASE = "increase"
    DECREASE = "decrease"
    BACKOFF = "backoff"
    HOLD = "hold"
    STARTUP = "startup"


@dataclass
class ControllerConfig:
    """Configuration for the AIMD controller."""
    
    # Limit bounds
    min_limit: int = 5
    max_limit: int = 200
    initial_limit: int = 20
    
    # AIMD parameters
    alpha: int = 1  # Additive increase
    beta: float = 0.9  # Multiplicative decrease
    
    # Target latency
    target_latency_ms: float = 50.0
    
    # When P95 is below this fraction of target, increase
    low_latency_threshold: float = 0.8
    
    # Error rate that triggers aggressive backoff
    error_backoff_threshold: float = 0.05
    backoff_factor: float = 0.5
    
    # Control loop timing
    control_interval_s: float = 1.0
    window_size_s: float = 10.0
    
    # Rate limit changes (max % change per interval)
    max_change_rate: float = 0.2
    
    # Minimum samples before adjusting
    min_samples: int = 10


@dataclass
class ControllerEvent:
    """Event emitted by the controller on each adjustment."""
    timestamp: float
    action: ControlAction
    old_limit: int
    new_limit: int
    stats: WindowStats
    
    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp,
            'action': self.action.value,
            'old_limit': self.old_limit,
            'new_limit': self.new_limit,
            'stats': self.stats.to_dict(),
        }


class AIMDController:
    """
    AIMD-based adaptive concurrency controller.
    
    Runs a background control loop that periodically:
    1. Collects latency statistics from the sliding window
    2. Decides whether to increase, decrease, or hold the limit
    3. Applies the new limit to the semaphore
    4. Emits events for monitoring
    
    Example:
        config = ControllerConfig(
            target_latency_ms=50.0,
            min_limit=5,
            max_limit=100,
        )
        
        controller = AIMDController(config)
        await controller.start()
        
        # Get the semaphore to use for requests
        sem = controller.semaphore
        
        async def handle_request():
            start = time.time()
            async with sem:
                result = await do_work()
            latency_ms = (time.time() - start) * 1000
            await controller.record(latency_ms, is_error=False)
            return result
        
        # Later...
        await controller.stop()
    """
    
    def __init__(
        self,
        config: Optional[ControllerConfig] = None,
        on_event: Optional[Callable[[ControllerEvent], None]] = None,
    ):
        """
        Initialize the controller.
        
        Args:
            config: Controller configuration
            on_event: Callback for control events (for logging/metrics)
        """
        self.config = config or ControllerConfig()
        self._on_event = on_event
        
        # Core components
        self._semaphore = AdaptiveSemaphore(self.config.initial_limit)
        self._window = SlidingWindow(self.config.window_size_s)
        
        # State
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._events: List[ControllerEvent] = []
        
        # Metrics
        self._total_adjustments = 0
        self._total_increases = 0
        self._total_decreases = 0
        self._total_backoffs = 0
    
    @property
    def semaphore(self) -> AdaptiveSemaphore:
        """Get the managed semaphore for request limiting."""
        return self._semaphore
    
    @property
    def window(self) -> SlidingWindow:
        """Get the sliding window for recording samples."""
        return self._window
    
    @property
    def current_limit(self) -> int:
        """Current concurrency limit."""
        return self._semaphore.limit
    
    @property
    def is_running(self) -> bool:
        """Whether the control loop is running."""
        return self._running
    
    async def start(self) -> None:
        """Start the control loop."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._control_loop())
    
    async def stop(self) -> None:
        """Stop the control loop."""
        if not self._running:
            return
        
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
    
    async def record(self, latency_ms: float, is_error: bool = False) -> None:
        """
        Record a request sample.
        
        Should be called after each request completes.
        
        Args:
            latency_ms: Request latency in milliseconds
            is_error: Whether the request resulted in an error
        """
        await self._window.record(latency_ms, is_error)
    
    async def _control_loop(self) -> None:
        """Main control loop - runs periodically to adjust limits."""
        while self._running:
            try:
                await asyncio.sleep(self.config.control_interval_s)
                
                if not self._running:
                    break
                
                await self._adjust()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log but don't crash the control loop
                print(f"[Controller] Error in control loop: {e}")
    
    async def _adjust(self) -> None:
        """Perform one adjustment cycle."""
        stats = await self._window.get_stats()
        old_limit = self._semaphore.limit
        
        # Determine action
        action, new_limit = self._decide(stats, old_limit)
        
        # Apply rate limiting
        new_limit = self._apply_rate_limit(old_limit, new_limit)
        
        # Apply bounds
        new_limit = max(self.config.min_limit, min(self.config.max_limit, new_limit))
        
        # Only adjust if changed
        if new_limit != old_limit:
            await self._semaphore.set_limit(new_limit)
            self._total_adjustments += 1
            
            if action == ControlAction.INCREASE:
                self._total_increases += 1
            elif action == ControlAction.DECREASE:
                self._total_decreases += 1
            elif action == ControlAction.BACKOFF:
                self._total_backoffs += 1
        
        # Emit event
        event = ControllerEvent(
            timestamp=time.time(),
            action=action,
            old_limit=old_limit,
            new_limit=new_limit,
            stats=stats,
        )
        self._events.append(event)
        
        # Keep only last 1000 events
        if len(self._events) > 1000:
            self._events = self._events[-500:]
        
        if self._on_event:
            self._on_event(event)
    
    def _decide(self, stats: WindowStats, current_limit: int) -> tuple[ControlAction, int]:
        """
        Decide what action to take based on statistics.
        
        Returns:
            Tuple of (action, new_limit)
        """
        # Not enough samples - hold
        if stats.sample_count < self.config.min_samples:
            return ControlAction.STARTUP, current_limit
        
        # High error rate - aggressive backoff
        if stats.error_rate > self.config.error_backoff_threshold:
            new_limit = int(current_limit * self.config.backoff_factor)
            return ControlAction.BACKOFF, max(self.config.min_limit, new_limit)
        
        # High latency - multiplicative decrease
        if stats.p95_latency_ms > self.config.target_latency_ms:
            new_limit = int(current_limit * self.config.beta)
            return ControlAction.DECREASE, max(self.config.min_limit, new_limit)
        
        # Low latency - additive increase
        if stats.p95_latency_ms < self.config.target_latency_ms * self.config.low_latency_threshold:
            new_limit = current_limit + self.config.alpha
            return ControlAction.INCREASE, min(self.config.max_limit, new_limit)
        
        # In acceptable range - hold
        return ControlAction.HOLD, current_limit
    
    def _apply_rate_limit(self, old_limit: int, new_limit: int) -> int:
        """Apply rate limiting to prevent rapid oscillation."""
        max_change = max(1, int(old_limit * self.config.max_change_rate))
        
        if new_limit > old_limit:
            return min(new_limit, old_limit + max_change)
        elif new_limit < old_limit:
            return max(new_limit, old_limit - max_change)
        return new_limit
    
    def get_recent_events(self, count: int = 10) -> List[ControllerEvent]:
        """Get recent control events."""
        return self._events[-count:]
    
    def get_metrics(self) -> dict:
        """Get controller metrics."""
        return {
            'current_limit': self.current_limit,
            'total_adjustments': self._total_adjustments,
            'total_increases': self._total_increases,
            'total_decreases': self._total_decreases,
            'total_backoffs': self._total_backoffs,
            'semaphore': self._semaphore.stats().to_dict(),
        }


class AdaptiveLimiter:
    """
    High-level API for the adaptive concurrency limiter.
    
    This is the main entry point for using the limiter.
    Wraps the controller and provides a clean interface.
    
    Example:
        limiter = AdaptiveLimiter(target_latency_ms=50.0)
        await limiter.start()
        
        async def handle_request(request):
            async with limiter.acquire() as permit:
                if not permit.acquired:
                    return Response(status=429)
                
                result = await process(request)
            
            # Latency automatically recorded
            return result
        
        await limiter.stop()
    """
    
    def __init__(
        self,
        target_latency_ms: float = 50.0,
        min_limit: int = 5,
        max_limit: int = 200,
        initial_limit: int = 20,
        **kwargs,
    ):
        config = ControllerConfig(
            target_latency_ms=target_latency_ms,
            min_limit=min_limit,
            max_limit=max_limit,
            initial_limit=initial_limit,
            **kwargs,
        )
        self._controller = AIMDController(config)
    
    @property
    def controller(self) -> AIMDController:
        return self._controller
    
    @property
    def current_limit(self) -> int:
        return self._controller.current_limit
    
    async def start(self) -> None:
        """Start the adaptive limiter."""
        await self._controller.start()
    
    async def stop(self) -> None:
        """Stop the adaptive limiter."""
        await self._controller.stop()
    
    def acquire(self, timeout: Optional[float] = None) -> 'LimiterContext':
        """
        Acquire a permit from the limiter.
        
        Usage:
            async with limiter.acquire() as permit:
                if permit.acquired:
                    await do_work()
        """
        return LimiterContext(self._controller, timeout)
    
    async def execute(
        self,
        func: Callable,
        *args,
        timeout: Optional[float] = None,
        **kwargs,
    ):
        """
        Execute a function with rate limiting.
        
        Args:
            func: Async function to execute
            timeout: Max time to wait for permit
            *args, **kwargs: Arguments to pass to func
            
        Returns:
            Result of func
            
        Raises:
            asyncio.TimeoutError: If timeout expires waiting for permit
        """
        async with self.acquire(timeout) as permit:
            if not permit.acquired:
                raise asyncio.TimeoutError("Failed to acquire permit")
            return await func(*args, **kwargs)


class LimiterContext:
    """Context manager for limiter permit acquisition with auto-recording."""
    
    def __init__(self, controller: AIMDController, timeout: Optional[float] = None):
        self._controller = controller
        self._timeout = timeout
        self.acquired = False
        self._start_time: Optional[float] = None
        self._is_error = False
    
    def mark_error(self) -> None:
        """Mark this request as an error (for error rate tracking)."""
        self._is_error = True
    
    @property
    def latency_ms(self) -> Optional[float]:
        """Current latency in milliseconds."""
        if self._start_time is None:
            return None
        return (time.time() - self._start_time) * 1000
    
    async def __aenter__(self) -> 'LimiterContext':
        self.acquired = await self._controller.semaphore.acquire(timeout=self._timeout)
        if self.acquired:
            self._start_time = time.time()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.acquired:
            # Record latency and release
            latency_ms = (time.time() - self._start_time) * 1000
            is_error = self._is_error or exc_type is not None
            
            await self._controller.record(latency_ms, is_error)
            await self._controller.semaphore.release_async()
