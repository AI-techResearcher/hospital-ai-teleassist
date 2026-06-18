"""
Production Metrics and Health Monitoring
Provides comprehensive monitoring for the hospital AI system
"""
import time
import psutil
import asyncio
from typing import Dict, Any
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import FastAPI, Response
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Prometheus Metrics
# Twilio Metrics
TWILIO_CALLS_TOTAL = Counter('twilio_calls_total', 'Total number of Twilio calls', ['status', 'direction'])
TWILIO_CALL_DURATION = Histogram('twilio_call_duration_seconds', 'Duration of Twilio calls')
TWILIO_ACTIVE_CALLS = Gauge('twilio_active_calls', 'Number of active Twilio calls')

# Hospital System Metrics
HOSPITAL_REQUESTS_TOTAL = Counter('hospital_requests_total', 'Total hospital system requests', ['endpoint', 'method', 'status'])
HOSPITAL_REQUEST_DURATION = Histogram('hospital_request_duration_seconds', 'Hospital system request duration', ['endpoint'])
HOSPITAL_AGENT_USAGE = Counter('hospital_agent_usage_total', 'Usage count by agent type', ['agent_type'])

# OpenAI API Metrics
OPENAI_REQUESTS_TOTAL = Counter('openai_requests_total', 'Total OpenAI API requests', ['model', 'status'])
OPENAI_REQUEST_DURATION = Histogram('openai_request_duration_seconds', 'OpenAI API request duration')
OPENAI_TOKENS_USED = Counter('openai_tokens_used_total', 'Total OpenAI tokens used', ['type'])

# System Metrics
SYSTEM_CPU_USAGE = Gauge('system_cpu_usage_percent', 'System CPU usage percentage')
SYSTEM_MEMORY_USAGE = Gauge('system_memory_usage_bytes', 'System memory usage in bytes')
SYSTEM_DISK_USAGE = Gauge('system_disk_usage_percent', 'System disk usage percentage')

# Database Metrics
DATABASE_CONNECTIONS = Gauge('database_connections_active', 'Active database connections')
DATABASE_QUERY_DURATION = Histogram('database_query_duration_seconds', 'Database query duration')

# Error Metrics
ERROR_COUNT = Counter('errors_total', 'Total number of errors', ['service', 'error_type'])
HEALTH_CHECK_STATUS = Gauge('health_check_status', 'Health check status (1=healthy, 0=unhealthy)', ['service'])

class MetricsCollector:
    """Collects and manages application metrics"""
    
    def __init__(self):
        self.start_time = time.time()
        self.active_calls = set()
        
    def record_call_start(self, call_sid: str, direction: str = "inbound"):
        """Record the start of a Twilio call"""
        TWILIO_CALLS_TOTAL.labels(status='started', direction=direction).inc()
        TWILIO_ACTIVE_CALLS.inc()
        self.active_calls.add(call_sid)
        logger.info(f"📊 Call started: {call_sid} ({direction})")
    
    def record_call_end(self, call_sid: str, duration: float, status: str = "completed"):
        """Record the end of a Twilio call"""
        TWILIO_CALLS_TOTAL.labels(status=status, direction='inbound').inc()
        TWILIO_CALL_DURATION.observe(duration)
        TWILIO_ACTIVE_CALLS.dec()
        self.active_calls.discard(call_sid)
        logger.info(f"📊 Call ended: {call_sid}, duration: {duration:.2f}s, status: {status}")
    
    def record_hospital_request(self, endpoint: str, method: str, duration: float, status_code: int):
        """Record hospital system request metrics"""
        status = "success" if 200 <= status_code < 400 else "error"
        HOSPITAL_REQUESTS_TOTAL.labels(endpoint=endpoint, method=method, status=status).inc()
        HOSPITAL_REQUEST_DURATION.labels(endpoint=endpoint).observe(duration)
    
    def record_agent_usage(self, agent_type: str):
        """Record usage of specific hospital agents"""
        HOSPITAL_AGENT_USAGE.labels(agent_type=agent_type).inc()
        logger.info(f"📊 Agent used: {agent_type}")
    
    def record_openai_request(self, model: str, duration: float, tokens_used: int, status: str = "success"):
        """Record OpenAI API request metrics"""
        OPENAI_REQUESTS_TOTAL.labels(model=model, status=status).inc()
        OPENAI_REQUEST_DURATION.observe(duration)
        OPENAI_TOKENS_USED.labels(type='total').inc(tokens_used)
    
    def record_error(self, service: str, error_type: str):
        """Record error occurrences"""
        ERROR_COUNT.labels(service=service, error_type=error_type).inc()
        logger.error(f"📊 Error recorded: {service} - {error_type}")
    
    def update_health_status(self, service: str, is_healthy: bool):
        """Update health check status"""
        HEALTH_CHECK_STATUS.labels(service=service).set(1 if is_healthy else 0)
    
    async def update_system_metrics(self):
        """Update system resource metrics"""
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            SYSTEM_CPU_USAGE.set(cpu_percent)
            
            # Memory usage
            memory = psutil.virtual_memory()
            SYSTEM_MEMORY_USAGE.set(memory.used)
            
            # Disk usage
            disk = psutil.disk_usage('/')
            disk_percent = (disk.used / disk.total) * 100
            SYSTEM_DISK_USAGE.set(disk_percent)
            
        except Exception as e:
            logger.error(f"Failed to update system metrics: {e}")
    
    def get_service_uptime(self) -> float:
        """Get service uptime in seconds"""
        return time.time() - self.start_time

# Global metrics collector
metrics_collector = MetricsCollector()

class HealthChecker:
    """Performs health checks on system components"""
    
    @staticmethod
    async def check_database() -> bool:
        """Check database connectivity"""
        try:
            # Add actual database connection check here
            return True
        except Exception:
            return False
    
    @staticmethod
    async def check_redis() -> bool:
        """Check Redis connectivity"""
        try:
            # Add actual Redis connection check here
            return True
        except Exception:
            return False
    
    @staticmethod
    async def check_openai() -> bool:
        """Check OpenAI API connectivity"""
        try:
            # Add actual OpenAI API check here
            return True
        except Exception:
            return False
    
    @staticmethod
    async def check_qdrant() -> bool:
        """Check Qdrant vector database"""
        try:
            # Add actual Qdrant connection check here
            return True
        except Exception:
            return False
    
    @classmethod
    async def comprehensive_health_check(cls) -> Dict[str, Any]:
        """Perform comprehensive health check"""
        checks = {
            "database": await cls.check_database(),
            "redis": await cls.check_redis(),
            "openai": await cls.check_openai(),
            "qdrant": await cls.check_qdrant()
        }
        
        # Update Prometheus metrics
        for service, is_healthy in checks.items():
            metrics_collector.update_health_status(service, is_healthy)
        
        overall_health = all(checks.values())
        
        return {
            "status": "healthy" if overall_health else "degraded",
            "timestamp": datetime.utcnow().isoformat(),
            "checks": checks,
            "uptime_seconds": metrics_collector.get_service_uptime(),
            "active_calls": len(metrics_collector.active_calls)
        }

def add_metrics_middleware(app: FastAPI):
    """Add metrics collection middleware to FastAPI app"""
    
    @app.middleware("http")
    async def metrics_middleware(request, call_next):
        start_time = time.time()
        
        try:
            response = await call_next(request)
            duration = time.time() - start_time
            
            # Record metrics
            metrics_collector.record_hospital_request(
                endpoint=request.url.path,
                method=request.method,
                duration=duration,
                status_code=response.status_code
            )
            
            return response
            
        except Exception as e:
            duration = time.time() - start_time
            
            # Record error
            metrics_collector.record_error(
                service="hospital_orchestrator",
                error_type=type(e).__name__
            )
            
            # Record failed request
            metrics_collector.record_hospital_request(
                endpoint=request.url.path,
                method=request.method,
                duration=duration,
                status_code=500
            )
            
            raise
    
    @app.get("/metrics")
    async def get_metrics():
        """Prometheus metrics endpoint"""
        await metrics_collector.update_system_metrics()
        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST
        )
    
    @app.get("/health/detailed")
    async def detailed_health():
        """Detailed health check endpoint"""
        return await HealthChecker.comprehensive_health_check()

# Background tasks for metrics collection
async def metrics_collection_task():
    """Background task for periodic metrics collection"""
    while True:
        try:
            await metrics_collector.update_system_metrics()
            await asyncio.sleep(30)  # Update every 30 seconds
        except Exception as e:
            logger.error(f"Metrics collection error: {e}")
            await asyncio.sleep(60)  # Wait longer on error

# Export for use in other modules
__all__ = ['metrics_collector', 'add_metrics_middleware', 'HealthChecker', 'metrics_collection_task']