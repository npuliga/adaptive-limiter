"""
Adaptive Semaphore Implementation

A counting semaphore that supports dynamic limit adjustment.
This is the core concurrency control primitive used by the limiter.

Design Rationale:
- BoundedSemaphore doesn't support changing limits at runtime
- We implement a custom semaphore using asyncio.Condition
- Permits can be acquired/released, and limit can change while requests wait

Key Properties:
- Fair ordering: requests are served in order they arrived
- Safe adjustment: can raise/lower limit while requests are in-flight
- Non-blocking try_acquire: useful for immediate rejection
"""

import asyncio
from dataclasses import dataclass
from typing import Optional


@dataclass
class SemaphoreStats:
    """Current state of the semaphore."""
    limit: int
    available: int
    in_flight: int
    waiting: int
    
    def to_dict(self) -> dict:
        return {
            'limit': self.limit,
            'available': self.available,
            'in_flight': self.in_flight,
            'waiting': self.waiting,
        }


class AdaptiveSemaphore:
    """
    A counting semaphore with a dynamically adjustable limit.
    
    Unlike asyncio.BoundedSemaphore, this semaphore allows the limit to be
    changed at runtime. When the limit is lowered and more permits are
    currently in use than the new limit allows, no existing permits are
    revoked—the semaphore simply becomes "over-capacity" until permits
    are released naturally.
    
    Example:
        sem = AdaptiveSemaphore(initial_limit=10)
        
        # Acquire a permit
        async with sem:
            await do_work()
        
        # Dynamically adjust limit
        await sem.set_limit(20)
        
        # Try to acquire without blocking
        if await sem.try_acquire():
            try:
                await do_work()
            finally:
                sem.release()
    """
    
    def __init__(self, initial_limit: int = 10):
        """
        Initialize semaphore with given concurrency limit.
        
        Args:
            initial_limit: Initial number of permits available
        """
        if initial_limit < 1:
            raise ValueError("Limit must be at least 1")
        
        self._limit = initial_limit
        self._available = initial_limit
        self._waiting = 0
        self._condition = asyncio.Condition()
    
    @property
    def limit(self) -> int:
        """Current limit."""
        return self._limit
    
    @property
    def available(self) -> int:
        """Number of permits currently available."""
        return max(0, self._available)
    
    @property
    def in_flight(self) -> int:
        """Number of permits currently in use."""
        return self._limit - self._available
    
    @property
    def waiting(self) -> int:
        """Number of tasks waiting for a permit."""
        return self._waiting
    
    def stats(self) -> SemaphoreStats:
        """Get current semaphore statistics."""
        return SemaphoreStats(
            limit=self._limit,
            available=self.available,
            in_flight=max(0, self.in_flight),
            waiting=self._waiting,
        )
    
    async def acquire(self, timeout: Optional[float] = None) -> bool:
        """
        Acquire a permit, blocking until available or timeout.
        
        Args:
            timeout: Maximum seconds to wait. None = wait forever.
            
        Returns:
            True if permit acquired, False if timeout expired.
        """
        async with self._condition:
            self._waiting += 1
            try:
                while self._available <= 0:
                    try:
                        await asyncio.wait_for(
                            self._condition.wait(),
                            timeout=timeout
                        )
                    except asyncio.TimeoutError:
                        return False
                
                self._available -= 1
                return True
            finally:
                self._waiting -= 1
    
    async def try_acquire(self) -> bool:
        """
        Try to acquire a permit without blocking.
        
        Returns:
            True if permit acquired immediately, False otherwise.
        """
        async with self._condition:
            if self._available > 0:
                self._available -= 1
                return True
            return False
    
    def release(self) -> None:
        """
        Release a permit back to the semaphore.
        
        Note: This is intentionally synchronous for use in finally blocks.
        It schedules a notify on the event loop.
        """
        # Schedule the actual release on the event loop
        loop = asyncio.get_event_loop()
        loop.call_soon(self._do_release)
    
    def _do_release(self) -> None:
        """Internal release implementation."""
        async def _release():
            async with self._condition:
                self._available += 1
                # Don't exceed the limit
                if self._available > self._limit:
                    self._available = self._limit
                self._condition.notify()
        
        asyncio.create_task(_release())
    
    async def release_async(self) -> None:
        """Async version of release for explicit async contexts."""
        async with self._condition:
            self._available += 1
            if self._available > self._limit:
                self._available = self._limit
            self._condition.notify()
    
    async def set_limit(self, new_limit: int) -> None:
        """
        Dynamically adjust the semaphore limit.
        
        If increasing: immediately notify waiting tasks.
        If decreasing below current usage: gracefully converge as permits release.
        
        Args:
            new_limit: New concurrency limit (must be >= 1)
        """
        if new_limit < 1:
            raise ValueError("Limit must be at least 1")
        
        async with self._condition:
            old_limit = self._limit
            diff = new_limit - old_limit
            
            self._limit = new_limit
            self._available += diff
            
            # If we increased capacity, wake up waiting tasks
            if diff > 0:
                self._condition.notify(diff)
    
    async def __aenter__(self) -> 'AdaptiveSemaphore':
        """Enter context manager, acquiring a permit."""
        await self.acquire()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager, releasing the permit."""
        await self.release_async()


class PermitContext:
    """
    A context manager for tracking permit acquisition with timing.
    
    Use when you need to measure how long a permit was held.
    
    Example:
        sem = AdaptiveSemaphore(10)
        
        async with PermitContext(sem) as ctx:
            await do_work()
        
        print(f"Held permit for {ctx.duration_ms}ms")
    """
    
    def __init__(self, semaphore: AdaptiveSemaphore, timeout: Optional[float] = None):
        self.semaphore = semaphore
        self.timeout = timeout
        self.acquired = False
        self.acquire_time: Optional[float] = None
        self.release_time: Optional[float] = None
    
    @property
    def duration_ms(self) -> Optional[float]:
        """Duration permit was held in milliseconds."""
        if self.acquire_time is None:
            return None
        end = self.release_time or asyncio.get_event_loop().time()
        return (end - self.acquire_time) * 1000
    
    async def __aenter__(self) -> 'PermitContext':
        import time
        self.acquired = await self.semaphore.acquire(timeout=self.timeout)
        if self.acquired:
            self.acquire_time = time.time()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        import time
        if self.acquired:
            self.release_time = time.time()
            await self.semaphore.release_async()
