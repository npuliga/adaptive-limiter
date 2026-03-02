"""
Tests for the Adaptive Concurrency Limiter.

Run with: python -m pytest tests/ -v
Or: python -m unittest tests.test_limiter
"""

import asyncio
import time
import unittest
from unittest import IsolatedAsyncioTestCase

import sys
sys.path.insert(0, '.')

from src.limiter import (
    AdaptiveSemaphore,
    SlidingWindow,
    AIMDController,
    ControllerConfig,
    ControlAction,
)


class TestSlidingWindow(IsolatedAsyncioTestCase):
    """Tests for SlidingWindow."""
    
    async def test_empty_window_returns_zero_stats(self):
        """Empty window should return zeroed stats."""
        window = SlidingWindow(window_size_s=10.0)
        stats = await window.get_stats()
        
        self.assertEqual(stats.sample_count, 0)
        self.assertEqual(stats.p95_latency_ms, 0.0)
        self.assertEqual(stats.error_rate, 0.0)
    
    async def test_records_samples(self):
        """Should record and retrieve samples."""
        window = SlidingWindow(window_size_s=10.0)
        
        # Record samples
        await window.record(10.0, is_error=False)
        await window.record(20.0, is_error=False)
        await window.record(30.0, is_error=True)
        
        stats = await window.get_stats()
        
        self.assertEqual(stats.sample_count, 3)
        self.assertAlmostEqual(stats.avg_latency_ms, 20.0, places=1)
        self.assertAlmostEqual(stats.error_rate, 1/3, places=2)
    
    async def test_window_pruning(self):
        """Old samples should be pruned."""
        window = SlidingWindow(window_size_s=0.1)  # 100ms window
        
        await window.record(100.0)
        await asyncio.sleep(0.15)  # Wait longer than window
        
        stats = await window.get_stats()
        self.assertEqual(stats.sample_count, 0)
    
    async def test_percentiles(self):
        """Should calculate percentiles correctly."""
        window = SlidingWindow(window_size_s=10.0)
        
        # Record 100 samples from 1 to 100
        for i in range(1, 101):
            await window.record(float(i))
        
        stats = await window.get_stats()
        
        # P50 should be around 50
        self.assertAlmostEqual(stats.p50_latency_ms, 50.0, delta=2.0)
        
        # P95 should be around 95
        self.assertAlmostEqual(stats.p95_latency_ms, 95.0, delta=2.0)
        
        # P99 should be around 99
        self.assertAlmostEqual(stats.p99_latency_ms, 99.0, delta=2.0)


class TestAdaptiveSemaphore(IsolatedAsyncioTestCase):
    """Tests for AdaptiveSemaphore."""
    
    async def test_initial_permits_available(self):
        """Should have initial permits available."""
        sem = AdaptiveSemaphore(initial_limit=10)
        
        self.assertEqual(sem.limit, 10)
        self.assertEqual(sem.available, 10)
        self.assertEqual(sem.in_flight, 0)
    
    async def test_acquire_reduces_available(self):
        """Acquiring should reduce available permits."""
        sem = AdaptiveSemaphore(initial_limit=5)
        
        await sem.acquire()
        
        self.assertEqual(sem.available, 4)
        self.assertEqual(sem.in_flight, 1)
    
    async def test_release_restores_available(self):
        """Releasing should restore available permits."""
        sem = AdaptiveSemaphore(initial_limit=5)
        
        await sem.acquire()
        await sem.release_async()
        
        # Give time for release to process
        await asyncio.sleep(0.01)
        
        self.assertEqual(sem.available, 5)
        self.assertEqual(sem.in_flight, 0)
    
    async def test_context_manager(self):
        """Context manager should acquire and release."""
        sem = AdaptiveSemaphore(initial_limit=5)
        
        async with sem:
            self.assertEqual(sem.in_flight, 1)
        
        self.assertEqual(sem.in_flight, 0)
    
    async def test_set_limit_increase(self):
        """Increasing limit should increase available."""
        sem = AdaptiveSemaphore(initial_limit=5)
        
        await sem.set_limit(10)
        
        self.assertEqual(sem.limit, 10)
        self.assertEqual(sem.available, 10)
    
    async def test_set_limit_decrease(self):
        """Decreasing limit should decrease available."""
        sem = AdaptiveSemaphore(initial_limit=10)
        
        await sem.set_limit(5)
        
        self.assertEqual(sem.limit, 5)
        self.assertEqual(sem.available, 5)
    
    async def test_try_acquire_success(self):
        """try_acquire should succeed when permits available."""
        sem = AdaptiveSemaphore(initial_limit=5)
        
        result = await sem.try_acquire()
        
        self.assertTrue(result)
        self.assertEqual(sem.available, 4)
    
    async def test_try_acquire_failure(self):
        """try_acquire should fail when no permits available."""
        sem = AdaptiveSemaphore(initial_limit=1)
        
        await sem.acquire()  # Take the only permit
        result = await sem.try_acquire()
        
        self.assertFalse(result)
    
    async def test_acquire_timeout(self):
        """acquire should timeout when no permits available."""
        sem = AdaptiveSemaphore(initial_limit=1)
        
        await sem.acquire()  # Take the only permit
        
        result = await sem.acquire(timeout=0.1)
        
        self.assertFalse(result)


class TestAIMDController(IsolatedAsyncioTestCase):
    """Tests for AIMDController."""
    
    async def test_starts_with_initial_limit(self):
        """Controller should start with configured initial limit."""
        config = ControllerConfig(
            initial_limit=50,
            min_limit=5,
            max_limit=100,
        )
        controller = AIMDController(config)
        
        self.assertEqual(controller.current_limit, 50)
    
    async def test_start_stop(self):
        """Controller should start and stop cleanly."""
        controller = AIMDController()
        
        self.assertFalse(controller.is_running)
        
        await controller.start()
        self.assertTrue(controller.is_running)
        
        await controller.stop()
        self.assertFalse(controller.is_running)
    
    async def test_record_samples(self):
        """Should record samples to window."""
        controller = AIMDController()
        
        await controller.record(10.0, is_error=False)
        await controller.record(20.0, is_error=True)
        
        count = await controller.window.get_sample_count()
        self.assertEqual(count, 2)
    
    async def test_decision_increase_on_low_latency(self):
        """Should increase limit when latency is low."""
        config = ControllerConfig(
            target_latency_ms=100.0,
            initial_limit=20,
            min_samples=5,
        )
        controller = AIMDController(config)
        
        # Record low-latency samples (below 80% of target = 80ms)
        for _ in range(10):
            await controller.record(30.0, is_error=False)
        
        stats = await controller.window.get_stats()
        action, new_limit = controller._decide(stats, 20)
        
        self.assertEqual(action, ControlAction.INCREASE)
        self.assertEqual(new_limit, 21)  # +1 (additive)
    
    async def test_decision_decrease_on_high_latency(self):
        """Should decrease limit when latency exceeds target."""
        config = ControllerConfig(
            target_latency_ms=50.0,
            initial_limit=20,
            min_samples=5,
        )
        controller = AIMDController(config)
        
        # Record high-latency samples (above target)
        for _ in range(10):
            await controller.record(100.0, is_error=False)
        
        stats = await controller.window.get_stats()
        action, new_limit = controller._decide(stats, 20)
        
        self.assertEqual(action, ControlAction.DECREASE)
        self.assertEqual(new_limit, 18)  # 20 * 0.9 = 18
    
    async def test_decision_backoff_on_errors(self):
        """Should backoff aggressively on high error rate."""
        config = ControllerConfig(
            error_backoff_threshold=0.05,
            initial_limit=20,
            min_samples=5,
        )
        controller = AIMDController(config)
        
        # Record many errors (>5%)
        for _ in range(10):
            await controller.record(20.0, is_error=True)
        
        stats = await controller.window.get_stats()
        action, new_limit = controller._decide(stats, 20)
        
        self.assertEqual(action, ControlAction.BACKOFF)
        self.assertEqual(new_limit, 10)  # 20 * 0.5 = 10
    
    async def test_decision_hold_in_acceptable_range(self):
        """Should hold when latency is in acceptable range."""
        config = ControllerConfig(
            target_latency_ms=100.0,
            low_latency_threshold=0.8,
            initial_limit=20,
            min_samples=5,
        )
        controller = AIMDController(config)
        
        # Record latency in acceptable range (80-100ms)
        for _ in range(10):
            await controller.record(90.0, is_error=False)
        
        stats = await controller.window.get_stats()
        action, new_limit = controller._decide(stats, 20)
        
        self.assertEqual(action, ControlAction.HOLD)
        self.assertEqual(new_limit, 20)
    
    async def test_respects_min_limit(self):
        """Should not go below min_limit."""
        config = ControllerConfig(
            min_limit=10,
            initial_limit=10,
            min_samples=5,
        )
        controller = AIMDController(config)
        
        # Record errors to trigger backoff
        for _ in range(10):
            await controller.record(20.0, is_error=True)
        
        stats = await controller.window.get_stats()
        action, new_limit = controller._decide(stats, 10)
        
        # Even with 50% backoff, shouldn't go below min
        self.assertGreaterEqual(new_limit, config.min_limit)
    
    async def test_respects_max_limit(self):
        """Should not exceed max_limit."""
        config = ControllerConfig(
            max_limit=25,
            initial_limit=25,
            min_samples=5,
        )
        controller = AIMDController(config)
        
        # Record low latency to trigger increase
        for _ in range(10):
            await controller.record(10.0, is_error=False)
        
        stats = await controller.window.get_stats()
        action, new_limit = controller._decide(stats, 25)
        
        # Even with increase, shouldn't exceed max
        self.assertLessEqual(new_limit, config.max_limit)


class TestRateLimiting(IsolatedAsyncioTestCase):
    """Tests for rate limiting of changes."""
    
    async def test_rate_limits_large_decrease(self):
        """Large decreases should be rate limited."""
        config = ControllerConfig(
            max_change_rate=0.2,  # 20% max change
        )
        controller = AIMDController(config)
        
        # A 50% decrease from 100 should be limited to 20%
        new_limit = controller._apply_rate_limit(old_limit=100, new_limit=50)
        
        # Should only decrease by 20% (100 -> 80)
        self.assertEqual(new_limit, 80)
    
    async def test_rate_limits_large_increase(self):
        """Large increases should be rate limited."""
        config = ControllerConfig(
            max_change_rate=0.2,
        )
        controller = AIMDController(config)
        
        # A 50% increase from 100 should be limited to 20%
        new_limit = controller._apply_rate_limit(old_limit=100, new_limit=150)
        
        # Should only increase by 20% (100 -> 120)
        self.assertEqual(new_limit, 120)
    
    async def test_small_changes_not_rate_limited(self):
        """Small changes should pass through unchanged."""
        config = ControllerConfig(
            max_change_rate=0.2,
        )
        controller = AIMDController(config)
        
        # A 5% increase from 100 should not be limited
        new_limit = controller._apply_rate_limit(old_limit=100, new_limit=105)
        
        self.assertEqual(new_limit, 105)


if __name__ == '__main__':
    unittest.main()
