# Production Deployment Guide

Complete guide for deploying the Adaptive Concurrency Limiter in production environments.

## Table of Contents

1. [Deployment Options](#deployment-options)
2. [Framework Integration](#framework-integration)
3. [Container Deployment](#container-deployment)
4. [Kubernetes Deployment](#kubernetes-deployment)
5. [Monitoring & Observability](#monitoring--observability)
6. [Configuration Tuning](#configuration-tuning)
7. [Troubleshooting](#troubleshooting)
8. [Runbooks](#runbooks)

---

## Deployment Options

### Option 1: Direct Integration (Library)

Embed the limiter directly in your application code.

**Pros:** Lowest latency, no network hops, simple deployment
**Cons:** Per-instance limits, no global coordination

**Best for:** Microservices, single-process applications

### Option 2: Sidecar Container

Run the limiter as a sidecar in Kubernetes pods.

**Pros:** Language-agnostic, uniform across services
**Cons:** Inter-process communication overhead

**Best for:** Heterogeneous tech stacks, service mesh patterns

### Option 3: API Gateway Integration

Implement at the gateway level (Kong, Envoy, etc.).

**Pros:** Centralized control, global view
**Cons:** Gateway becomes bottleneck, more complex

**Best for:** API gateways, multi-tenant platforms

---

## Framework Integration

### FastAPI Integration

```python
# app/main.py
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
import asyncio

from src.limiter import AdaptiveLimiter, ControllerConfig

# Create limiter with production settings
limiter = AdaptiveLimiter(
    target_latency_ms=100.0,
    min_limit=10,
    max_limit=500,
    initial_limit=50,
    control_interval_s=2.0,
    window_size_s=30.0,
)

app = FastAPI()


@app.on_event("startup")
async def startup():
    """Start the limiter control loop."""
    await limiter.start()


@app.on_event("shutdown")
async def shutdown():
    """Stop the limiter gracefully."""
    await limiter.stop()


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Apply adaptive rate limiting to all requests."""
    
    # Try to acquire permit with timeout
    async with limiter.acquire(timeout=5.0) as permit:
        if not permit.acquired:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too Many Requests",
                    "retry_after_seconds": 5,
                },
                headers={"Retry-After": "5"},
            )
        
        # Process request
        response = await call_next(request)
        
        # Mark errors for limiter feedback
        if response.status_code >= 500:
            permit.mark_error()
        
        return response


@app.get("/health")
async def health():
    """Health check endpoint (excluded from rate limiting)."""
    return {
        "status": "healthy",
        "limiter": {
            "current_limit": limiter.current_limit,
            "controller_running": limiter.controller.is_running,
        },
    }


@app.get("/metrics")
async def metrics():
    """Metrics endpoint for monitoring."""
    return limiter.controller.get_metrics()
```

### Flask Integration

```python
# app.py
from flask import Flask, request, jsonify, g
import asyncio
from functools import wraps

from src.limiter import AdaptiveLimiter

app = Flask(__name__)

# Create event loop and limiter
loop = asyncio.new_event_loop()
limiter = AdaptiveLimiter(target_latency_ms=100.0)

# Start limiter
loop.run_until_complete(limiter.start())


def with_rate_limit(f):
    """Decorator to apply rate limiting."""
    @wraps(f)
    def decorated(*args, **kwargs):
        async def acquire_and_run():
            async with limiter.acquire(timeout=5.0) as permit:
                if not permit.acquired:
                    return None, True  # Rejected
                
                # Run the sync function in executor
                result = await loop.run_in_executor(None, f, *args, **kwargs)
                return result, False
        
        result, rejected = loop.run_until_complete(acquire_and_run())
        
        if rejected:
            return jsonify({"error": "Too Many Requests"}), 429
        
        return result
    
    return decorated


@app.route("/api/resource")
@with_rate_limit
def get_resource():
    return jsonify({"data": "example"})
```

### Generic ASGI Middleware

```python
# middleware.py
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

class AdaptiveLimiterMiddleware(BaseHTTPMiddleware):
    """Generic ASGI middleware for adaptive rate limiting."""
    
    def __init__(self, app, limiter, timeout: float = 5.0):
        super().__init__(app)
        self.limiter = limiter
        self.timeout = timeout
    
    async def dispatch(self, request, call_next):
        # Skip health checks
        if request.url.path in ["/health", "/ready", "/metrics"]:
            return await call_next(request)
        
        async with self.limiter.acquire(timeout=self.timeout) as permit:
            if not permit.acquired:
                return JSONResponse(
                    {"error": "Too Many Requests"},
                    status_code=429,
                )
            
            response = await call_next(request)
            
            if response.status_code >= 500:
                permit.mark_error()
            
            return response


# Usage
from starlette.applications import Starlette
from src.limiter import AdaptiveLimiter

limiter = AdaptiveLimiter(target_latency_ms=100.0)
app = Starlette()
app.add_middleware(AdaptiveLimiterMiddleware, limiter=limiter)
```

---

## Container Deployment

### Dockerfile

```dockerfile
# Dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy source code
COPY src/ /app/src/
COPY pyproject.toml /app/

# No dependencies to install (pure Python)

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser
USER appuser

# Environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Default command (override in docker-compose or K8s)
CMD ["python", "-m", "src.main", "--scenario", "steady_state"]
```

### Docker Compose (Development)

```yaml
# docker-compose.yml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - LIMITER_TARGET_LATENCY_MS=100
      - LIMITER_MIN_LIMIT=5
      - LIMITER_MAX_LIMIT=200
      - LIMITER_INITIAL_LIMIT=50
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 3
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 512M
        reservations:
          cpus: '0.5'
          memory: 256M

  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
```

---

## Kubernetes Deployment

### ConfigMap

```yaml
# k8s/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: adaptive-limiter-config
  namespace: default
data:
  # Limiter settings (can be environment-specific)
  TARGET_LATENCY_MS: "100"
  MIN_LIMIT: "10"
  MAX_LIMIT: "500"
  INITIAL_LIMIT: "50"
  CONTROL_INTERVAL_S: "2.0"
  WINDOW_SIZE_S: "30.0"
```

### Deployment

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
  namespace: default
  labels:
    app: myapp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: myapp
  template:
    metadata:
      labels:
        app: myapp
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
    spec:
      containers:
        - name: app
          image: myapp:latest
          ports:
            - containerPort: 8000
              name: http
          envFrom:
            - configMapRef:
                name: adaptive-limiter-config
          resources:
            requests:
              cpu: "500m"
              memory: "256Mi"
            limits:
              cpu: "1000m"
              memory: "512Mi"
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /ready
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 5
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app: myapp
```

### Service

```yaml
# k8s/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: myapp
  namespace: default
spec:
  selector:
    app: myapp
  ports:
    - port: 80
      targetPort: 8000
      name: http
  type: ClusterIP
```

### HorizontalPodAutoscaler

```yaml
# k8s/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: myapp-hpa
  namespace: default
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: myapp
  minReplicas: 3
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    # Custom metric: rejection rate
    - type: Pods
      pods:
        metric:
          name: limiter_rejection_rate
        target:
          type: AverageValue
          averageValue: "5"  # Scale up if >5% rejection
```

### PodDisruptionBudget

```yaml
# k8s/pdb.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: myapp-pdb
  namespace: default
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: myapp
```

---

## Monitoring & Observability

### Prometheus Metrics

```python
# metrics/prometheus.py
from prometheus_client import Gauge, Counter, Histogram, generate_latest
from src.limiter import ControllerEvent, ControlAction

# Gauges (current values)
current_limit = Gauge(
    'adaptive_limiter_current_limit',
    'Current concurrency limit'
)
in_flight = Gauge(
    'adaptive_limiter_in_flight',
    'Currently executing requests'
)
p95_latency = Gauge(
    'adaptive_limiter_p95_latency_ms',
    'P95 latency in milliseconds'
)

# Counters (totals)
requests_total = Counter(
    'adaptive_limiter_requests_total',
    'Total requests',
    ['status']  # acquired, rejected, error
)
adjustments_total = Counter(
    'adaptive_limiter_adjustments_total',
    'Total limit adjustments',
    ['action']  # increase, decrease, backoff, hold
)

# Histogram (latency distribution)
request_latency = Histogram(
    'adaptive_limiter_request_latency_seconds',
    'Request latency',
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)


def on_controller_event(event: ControllerEvent):
    """Callback to update Prometheus metrics."""
    current_limit.set(event.new_limit)
    p95_latency.set(event.stats.p95_latency_ms)
    adjustments_total.labels(action=event.action.value).inc()


def record_request(latency_s: float, acquired: bool, error: bool):
    """Record request metrics."""
    if not acquired:
        requests_total.labels(status='rejected').inc()
    elif error:
        requests_total.labels(status='error').inc()
    else:
        requests_total.labels(status='success').inc()
    
    request_latency.observe(latency_s)


# FastAPI endpoint
from fastapi import Response

@app.get("/metrics")
async def metrics():
    # Update current values
    in_flight.set(limiter.controller.semaphore.in_flight)
    return Response(
        content=generate_latest(),
        media_type="text/plain"
    )
```

### Prometheus Configuration

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'adaptive-limiter'
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
        action: replace
        target_label: __metrics_path__
        regex: (.+)
```

### Grafana Dashboard

```json
{
  "dashboard": {
    "title": "Adaptive Limiter Dashboard",
    "panels": [
      {
        "title": "Current Limit",
        "type": "stat",
        "targets": [
          {
            "expr": "adaptive_limiter_current_limit",
            "legendFormat": "Limit"
          }
        ]
      },
      {
        "title": "Limit Over Time",
        "type": "graph",
        "targets": [
          {
            "expr": "adaptive_limiter_current_limit",
            "legendFormat": "{{instance}}"
          }
        ]
      },
      {
        "title": "P95 Latency",
        "type": "graph",
        "targets": [
          {
            "expr": "adaptive_limiter_p95_latency_ms",
            "legendFormat": "P95"
          },
          {
            "expr": "100",
            "legendFormat": "Target"
          }
        ]
      },
      {
        "title": "Requests/sec by Status",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(adaptive_limiter_requests_total[1m])",
            "legendFormat": "{{status}}"
          }
        ]
      },
      {
        "title": "Rejection Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(adaptive_limiter_requests_total{status='rejected'}[5m]) / rate(adaptive_limiter_requests_total[5m]) * 100",
            "legendFormat": "Rejection %"
          }
        ]
      },
      {
        "title": "Adjustments",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(adaptive_limiter_adjustments_total[5m])",
            "legendFormat": "{{action}}"
          }
        ]
      }
    ]
  }
}
```

### Alerting Rules

```yaml
# alerting-rules.yaml
groups:
  - name: adaptive-limiter
    rules:
      - alert: HighRejectionRate
        expr: |
          rate(adaptive_limiter_requests_total{status="rejected"}[5m]) 
          / rate(adaptive_limiter_requests_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High request rejection rate"
          description: "More than 10% of requests are being rejected"
      
      - alert: LimiterAtMinimum
        expr: adaptive_limiter_current_limit == 10
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Limiter stuck at minimum"
          description: "The concurrency limit has been at minimum for 10+ minutes"
      
      - alert: HighLatency
        expr: adaptive_limiter_p95_latency_ms > 200
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "P95 latency exceeds 200ms"
          description: "Latency is high despite adaptive limiting"
      
      - alert: LimiterControllerStopped
        expr: up{job="adaptive-limiter"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Limiter controller not running"
          description: "Cannot scrape metrics from limiter"
```

---

## Configuration Tuning

### Environment-Specific Settings

| Parameter | Development | Staging | Production |
|-----------|-------------|---------|------------|
| `target_latency_ms` | 100 | 100 | 100 |
| `min_limit` | 2 | 5 | 10 |
| `max_limit` | 50 | 200 | 500 |
| `initial_limit` | 10 | 20 | 50 |
| `control_interval_s` | 0.5 | 1.0 | 2.0 |
| `window_size_s` | 5 | 10 | 30 |
| `min_samples` | 5 | 10 | 20 |
| `max_change_rate` | 0.3 | 0.2 | 0.1 |

### Environment Variables

```bash
# Production environment
export LIMITER_TARGET_LATENCY_MS=100
export LIMITER_MIN_LIMIT=10
export LIMITER_MAX_LIMIT=500
export LIMITER_INITIAL_LIMIT=50
export LIMITER_CONTROL_INTERVAL_S=2.0
export LIMITER_WINDOW_SIZE_S=30.0
export LIMITER_MIN_SAMPLES=20
export LIMITER_MAX_CHANGE_RATE=0.1
```

### Load Configuration from Environment

```python
import os

def load_config_from_env() -> ControllerConfig:
    """Load limiter configuration from environment variables."""
    return ControllerConfig(
        target_latency_ms=float(os.getenv('LIMITER_TARGET_LATENCY_MS', '100')),
        min_limit=int(os.getenv('LIMITER_MIN_LIMIT', '10')),
        max_limit=int(os.getenv('LIMITER_MAX_LIMIT', '500')),
        initial_limit=int(os.getenv('LIMITER_INITIAL_LIMIT', '50')),
        control_interval_s=float(os.getenv('LIMITER_CONTROL_INTERVAL_S', '2.0')),
        window_size_s=float(os.getenv('LIMITER_WINDOW_SIZE_S', '30.0')),
        min_samples=int(os.getenv('LIMITER_MIN_SAMPLES', '20')),
        max_change_rate=float(os.getenv('LIMITER_MAX_CHANGE_RATE', '0.1')),
    )
```

---

## Troubleshooting

### Problem: High Rejection Rate

**Symptoms:** >10% of requests getting 429 status

**Diagnostic Steps:**
```bash
# Check current limit
curl localhost:8000/metrics | grep adaptive_limiter_current_limit

# Check if at minimum
kubectl logs deployment/myapp | grep "limit.*5"

# Check backend latency
curl localhost:8000/metrics | grep adaptive_limiter_p95_latency_ms
```

**Resolution:**
1. If limit at minimum → Backend is overloaded, scale or fix backend
2. If latency is low but limit is low → Check for error spike, increase min_limit
3. If latency is high → Backend problem, not limiter problem

### Problem: Limit Oscillating

**Symptoms:** Limit bouncing between values rapidly

**Diagnostic Steps:**
```bash
# Check adjustment frequency
kubectl logs deployment/myapp | grep -c "INCREASE\|DECREASE" 

# Check adjustment rate
curl localhost:8000/metrics | grep adaptive_limiter_adjustments_total
```

**Resolution:**
1. Increase `control_interval_s` (e.g., 1.0 → 2.0)
2. Decrease `max_change_rate` (e.g., 0.2 → 0.1)
3. Increase `window_size_s` (e.g., 10 → 30)
4. Increase `min_samples` (e.g., 10 → 20)

### Problem: Limit Not Increasing

**Symptoms:** Limit stays at initial value, never adjusts

**Diagnostic Steps:**
```bash
# Check controller is running
curl localhost:8000/health | jq .limiter

# Check sample count
kubectl logs deployment/myapp | grep "sample_count"

# Check if traffic is reaching service
curl localhost:8000/metrics | grep requests_total
```

**Resolution:**
1. If controller not running → Check startup, look for exceptions
2. If sample_count < min_samples → Traffic too low, or samples not recording
3. If latency in acceptable range → Limiter is holding (correct behavior)

### Problem: Memory Growing

**Symptoms:** Pod memory usage increasing over time

**Diagnostic Steps:**
```bash
# Check memory
kubectl top pod -l app=myapp

# Check sample deque size (if exposed)
kubectl exec deployment/myapp -- python -c "
from app import limiter
print(len(limiter.controller._window._samples))
"
```

**Resolution:**
1. Samples should be bounded by window size × RPS
2. If unbounded growth → Bug in pruning, check `_prune_old_samples`
3. Reduce `window_size_s` as last resort

---

## Runbooks

### Runbook: Emergency Disable Limiter

**When to use:** Limiter is causing issues and needs to be bypassed immediately.

```bash
# Option 1: Set very high limit
kubectl set env deployment/myapp LIMITER_MAX_LIMIT=100000 LIMITER_INITIAL_LIMIT=100000

# Option 2: Bypass in code (feature flag)
kubectl set env deployment/myapp LIMITER_ENABLED=false

# Option 3: Skip limiter middleware (if designed with bypass)
kubectl annotate pod -l app=myapp limiter.skip=true

# Rollback
kubectl set env deployment/myapp LIMITER_MAX_LIMIT=500 LIMITER_INITIAL_LIMIT=50
```

### Runbook: Tune for New Traffic Pattern

**When to use:** Regular traffic pattern has changed (e.g., new feature launch)

```bash
# 1. Enable shadow mode (log decisions but don't enforce)
kubectl set env deployment/myapp LIMITER_SHADOW_MODE=true

# 2. Monitor for 1 hour
# Watch Grafana for limit suggestions

# 3. Update parameters based on observation
kubectl set env deployment/myapp \
  LIMITER_INITIAL_LIMIT=75 \
  LIMITER_MAX_LIMIT=300

# 4. Disable shadow mode
kubectl set env deployment/myapp LIMITER_SHADOW_MODE=false
```

### Runbook: Investigate Latency Spike

**When to use:** Alert fired for high latency

```bash
# 1. Check limiter state
curl localhost:8000/metrics | grep adaptive_limiter

# 2. Check if limiter is reducing load
# Expected: limit should be decreasing

# 3. Check backend health
kubectl logs deployment/backend --tail=100

# 4. Check if limiter is at minimum (can't help further)
if limit == min_limit:
    echo "Backend is overloaded, not a limiter problem"
    # Proceed with backend scaling/troubleshooting

# 5. If limit is high but latency is high
# Possible: min_samples too high, not enough signal
kubectl set env deployment/myapp LIMITER_MIN_SAMPLES=5
```

### Runbook: Gradual Rollout

**When to use:** First deployment or major configuration change

```bash
# Day 1: Canary (5%)
kubectl apply -f k8s/deployment-canary.yaml
# Monitor for 4 hours

# Day 2: Increase to 25%
kubectl scale deployment myapp-canary --replicas=3

# Day 3: Increase to 50%  
kubectl scale deployment myapp-canary --replicas=5
kubectl scale deployment myapp-stable --replicas=5

# Day 4: Full rollout
kubectl delete deployment myapp-stable
kubectl scale deployment myapp-canary --replicas=10
kubectl patch deployment myapp-canary -p '{"metadata":{"name":"myapp"}}'
```

---

## Checklist: Production Readiness

- [ ] **Monitoring**
  - [ ] Prometheus metrics configured
  - [ ] Grafana dashboard deployed
  - [ ] Alerting rules active
  
- [ ] **Configuration**
  - [ ] Environment-specific configs in ConfigMap
  - [ ] Min/max limits appropriate for capacity
  - [ ] Target latency matches SLA
  
- [ ] **Reliability**
  - [ ] Health checks configured
  - [ ] PodDisruptionBudget set
  - [ ] HPA configured for scaling
  
- [ ] **Operations**
  - [ ] Runbooks documented
  - [ ] On-call trained on limiter behavior
  - [ ] Emergency disable procedure tested
  
- [ ] **Testing**
  - [ ] Load tested with expected traffic
  - [ ] Chaos tested with failure injection
  - [ ] Shadow mode validated behavior
