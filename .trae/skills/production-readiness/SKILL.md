---
name: "production-readiness"
description: "Ensures all development meets production-grade standards. Invoke when implementing new features, reviewing code, or before deployment. Validates error handling, performance, security, scalability, and infrastructure compatibility."
---

# Production Readiness Development Skill

## Purpose
This skill enforces production-grade standards throughout the entire development lifecycle of the Yugan Intelligence system. It acts as a mandatory checkpoint before any code reaches production, ensuring robustness, performance, security, and seamless deployment.

## When to Invoke (CRITICAL)
You MUST invoke this skill:
1. **Before implementing new features** - Validate production requirements first
2. **During code review** - Check against production standards
3. **Before deployment** - Final production readiness validation
4. **When user asks about production requirements** - Provide guidance
5. **When architectural decisions are made** - Validate scalability and compatibility
6. **After significant bug fixes** - Ensure fix doesn't introduce production risks

## Production Readiness Standards

### 1. Error Handling (Production-Grade)

#### Backend Error Handling
```python
# ❌ WRONG: Raw exception exposure
@app.get("/api/data")
def get_data():
    data = risky_operation()
    return data  # Unhandled exception crashes server

# ✅ CORRECT: Production-grade error handling
@app.get("/api/data")
async def get_data(db: Session = Depends(get_db)):
    try:
        data = await risky_operation(db)
        return {"success": True, "data": data}
    except BusinessException as e:
        logger.error(f"Business error: {e}", extra={"endpoint": "/api/data"})
        raise  # Global handler formats response
    except Exception as e:
        logger.exception(f"Unexpected error in get_data: {e}")
        raise BusinessException("Internal processing error", error_code="SYS_001")
```

#### Requirements:
- All API endpoints must have try-except blocks
- Never expose raw stack traces to clients
- Use structured error codes (e.g., `SYS_001`, `DB_002`, `RFID_003`)
- Log errors with context (endpoint, user_id, operation)
- Implement circuit breakers for external services (RFID, database)
- Timeout handling for all I/O operations (default: 30s for DB, 10s for RFID)

### 2. Performance Optimization Standards

#### Response Time Requirements
| Endpoint Type | Max Response Time | Measurement Point |
|---------------|-------------------|-------------------|
| Simple CRUD (GET) | 200ms | P95 latency |
| List/Filter (GET) | 500ms | P95 latency |
| Create/Update (POST/PUT) | 300ms | P95 latency |
| RFID Operations | 2s | P99 latency (hardware-dependent) |
| WebSocket streams | 50ms per message | Frame processing time |

#### Database Performance
```python
# ❌ WRONG: N+1 query problem
for drone in drones:
    tasks = db.query(Task).filter(Task.drone_id == drone.id).all()

# ✅ CORRECT: Optimized query with join
drones_with_tasks = db.query(Drone).options(
    joinedload(Drone.tasks)
).filter(Drone.status == 'active').all()
```

#### Requirements:
- Use SQLAlchemy `joinedload` or `selectinload` for relationships
- Implement pagination for all list endpoints (default: 20 items)
- Add database indexes for frequently queried fields:
  - `drone_code`, `task_code`, `epc` (RFID tags)
  - `created_at`, `updated_at` (time-series queries)
  - `status` (state filtering)
- Cache frequently accessed data in Redis (expiration: 5-60 minutes)
- Use asyncio for concurrent I/O operations

### 3. Security Best Practices

#### Authentication & Authorization
```python
# ❌ WRONG: No auth check
@app.delete("/api/users/{user_id}")
def delete_user(user_id: int):
    # Anyone can delete any user!

# ✅ CORRECT: RBAC enforcement
@app.delete("/api/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.has_permission("user:delete"):
        raise BusinessException("Permission denied", error_code="AUTH_001")
    if user_id == current_user.id:
        raise BusinessException("Cannot delete self", error_code="AUTH_002")
    # Proceed with deletion...
```

#### Input Validation
```python
# ❌ WRONG: No validation
@app.post("/api/skus")
def create_sku(data: dict):
    sku = SKU(**data)  # Arbitrary field injection!

# ✅ CORRECT: Pydantic validation
class SKUCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    epc: Optional[str] = Field(None, pattern=r'^[A-F0-9]{24}$')
    quantity: int = Field(0, ge=0, le=10000)

@app.post("/api/skus")
async def create_sku(sku_data: SKUCreate, db: Session = Depends(get_db)):
    # Automatically validated by Pydantic
```

#### Security Requirements:
- All endpoints (except `/health`, `/login`) require JWT authentication
- RBAC: Check permissions before sensitive operations
- Input validation with Pydantic schemas (all public endpoints)
- Rate limiting: 100 requests/minute per IP (Redis-based)
- CORS: Whitelist only production domains
- SQL injection prevention: Use SQLAlchemy ORM (never raw SQL with user input)
- Secrets management: Environment variables, never hardcode
- HTTPS mandatory in production (redirect HTTP)

### 4. Scalability Considerations

#### Horizontal Scaling Design
```yaml
# docker-compose.yml for production
services:
  warehouse:
    deploy:
      replicas: 3  # Multiple instances
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 3
```

#### Stateless Design Requirements:
- No local file storage for session data (use Redis)
- Database connection pooling (max 10 connections per instance)
- WebSocket connections must handle reconnection gracefully
- Background tasks must be distributed-safe (use Redis locks)
- Configuration via environment variables, not local files

### 5. Production Infrastructure Compatibility

#### Environment Configuration
```python
# config.py production-ready pattern
class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = Field(..., env="DATABASE_URL")
    DB_POOL_SIZE: int = Field(10, env="DB_POOL_SIZE")
    DB_MAX_OVERFLOW: int = Field(20, env="DB_MAX_OVERFLOW")
    
    # Redis
    REDIS_URL: str = Field("redis://localhost:6379/0", env="REDIS_URL")
    
    # JWT
    JWT_SECRET_KEY: str = Field(..., env="JWT_SECRET_KEY")  # Required in production
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24
    
    # RFID Hardware
    RFID_DEVICE: str = Field("/dev/ttyUSB0", env="RFID_DEVICE")
    RFID_BAUD_RATE: int = 115200
    
    # Production flags
    DEBUG: bool = Field(False, env="DEBUG")
    ENABLE_CORS: bool = Field(True, env="ENABLE_CORS")
    
    class Config:
        env_file = ".env"
        case_sensitive = False
```

#### Docker Compose Requirements:
- Health checks for all services
- Volume persistence for database data
- Network isolation (internal network for backend)
- Resource limits (CPU, memory)
- Log rotation configuration
- Restart policies: `always` for production

#### Validation Checklist:
- [ ] All ports configurable via environment variables
- [ ] Database connection handles container network names (`postgres`, not `localhost`)
- [ ] RFID device path configurable (`/dev/ttyUSB0`, `/dev/ttyS6` for WSL)
- [ ] Docker volumes mapped correctly
- [ ] Health endpoints return proper status (`/health`)
- [ ] Log output to stdout/stderr (Docker logging)

### 6. Testing Standards

#### Unit Test Requirements
```python
# tests/test_inbound_service.py
@pytest.fixture
def mock_rfid_reader():
    return MockRFIDReader()

@pytest.fixture
def mock_db_session():
    return MockSessionLocal()

def test_inbound_process_tag_success(mock_rfid_reader, mock_db_session):
    """Test RFID tag processing with valid EPC"""
    tag = RFIDTag(epc="E2003412BDFDFFC000000001", rssi=-50)
    service = InboundService(mock_db_session, mock_rfid_reader)
    
    result = service.process_tag(tag)
    
    assert result.success is True
    assert result.sku_id is not None
    mock_db_session.commit.assert_called_once()

def test_inbound_process_tag_unknown_epc(mock_rfid_reader, mock_db_session):
    """Test handling of unknown EPC"""
    tag = RFIDTag(epc="UNKNOWN_EPC", rssi=-50)
    service = InboundService(mock_db_session, mock_rfid_reader)
    
    result = service.process_tag(tag)
    
    assert result.success is False
    assert "Unknown EPC" in result.message
    mock_db_session.rollback.assert_called_once()
```

#### Test Coverage Requirements:
- Core business logic: 100% coverage (services layer)
- API endpoints: 80% coverage (routers layer)
- Hardware drivers: 90% coverage (RFID reader)
- Error paths: All known error codes tested
- Edge cases: Empty inputs, max limits, concurrent access

#### Integration Test Requirements:
- End-to-end flow: Drone heartbeat → Gateway → Database
- RFID flow: Tag detection → Inbound service → Inventory update
- WebSocket flow: Client connection → Message streaming → Reconnection
- Database transactions: Rollback on failure, commit on success

### 7. Production Validation Process

#### Pre-Deployment Checklist (MANDATORY)
```bash
# Run before every deployment
1. Code Review: All changes reviewed by production-readiness skill
2. Test Coverage: pytest --cov=src --cov-report=term-missing (target: 80%)
3. Security Scan: bandit -r src/ (no high-severity issues)
4. Dependency Audit: pip-audit (no known vulnerabilities)
5. Performance Test: Locust load test (target: 100 concurrent users)
6. Docker Build Test: docker compose build (all images build successfully)
7. Environment Validation: All required env vars documented
8. Database Migration: Alembic upgrade head (test on staging DB)
9. Log Validation: Structured logging format verified
10. Health Check: All /health endpoints return 200
```

#### Staging Environment Validation
Before production deployment, validate in staging environment:
- Same Docker Compose configuration
- Same database schema (migrated)
- Same Redis configuration
- Hardware simulation (RFID mock)
- Load testing (2x expected production load)
- Failure recovery testing (database disconnect, RFID timeout)

### 8. Monitoring & Observability

#### Required Metrics
```python
# Prometheus metrics integration
from prometheus_client import Counter, Histogram, Gauge

API_REQUEST_COUNT = Counter(
    'api_request_count',
    'API request count',
    ['method', 'endpoint', 'status']
)

API_RESPONSE_TIME = Histogram(
    'api_response_time_seconds',
    'API response time',
    ['endpoint']
)

RFID_READ_SUCCESS = Counter(
    'rfid_read_success',
    'Successful RFID reads'
)

RFID_READ_FAILURE = Counter(
    'rfid_read_failure',
    'Failed RFID reads',
    ['error_code']
)
```

#### Required Log Fields
```json
{
  "timestamp": "2026-07-03T10:30:00Z",
  "level": "INFO",
  "service": "warehouse-inspection-system",
  "endpoint": "/api/v1/inbound/start",
  "user_id": "user_123",
  "trace_id": "abc-123-def",
  "message": "Inbound started",
  "duration_ms": 150,
  "extra": {
    "rfid_device": "/dev/ttyUSB0",
    "drone_code": "DRONE001"
  }
}
```

### 9. Integration with Yugan Intelligence Skill

This skill works in conjunction with the main `yugan-intelligence` skill:

1. **yugan-intelligence** defines architecture and coding standards
2. **production-readiness** validates against production requirements
3. Both skills must be invoked for complete development workflow

#### Workflow Integration:
```
New Feature Development Flow:
┌─────────────────────────────────────┐
│ 1. Invoke yugan-intelligence        │ ← Architecture & standards
│ 2. Invoke production-readiness      │ ← Validate requirements
│ 3. Implement with both constraints  │
│ 4. Test against production checklist│
│ 5. Deploy to staging                │
│ 6. Validate in staging              │
│ 7. Deploy to production             │
└─────────────────────────────────────┘
```

## Production Deployment Gate

Before ANY code reaches production, you must ask:

> "Has this implementation passed the production readiness checklist?"

If ANY item is unchecked or uncertain, STOP deployment and:
1. Document the gap
2. Implement missing requirements
3. Re-validate

## Forbidden Patterns (Production Risk)

| Pattern | Why Forbidden | Correct Alternative |
|---------|---------------|---------------------|
| `print()` statements | Logs lost in Docker | `logger.info()` |
| Hardcoded secrets | Security breach | Environment variables |
| No timeout on I/O | Production hangs | `asyncio.wait_for(timeout=30)` |
| N+1 queries | Performance crash | `joinedload()` |
| No input validation | Injection attacks | Pydantic schemas |
| Global state in backend | Scaling failure | Redis/Database state |
| No health check | Deployment failure | `/health` endpoint |
| Raw exception return | Client confusion | Structured error codes |

## Examples from Current Project

### RFID Driver Production Readiness
```python
# src/hardware/rfid_reader.py - Production validation points

# ✅ Circuit breaker for serial failures
def connect(self) -> bool:
    if self._connection_attempts >= self._max_retries:
        logger.error(f"RFID connection circuit breaker triggered")
        return False
    try:
        self.ser = serial.Serial(self.port, self.baud, timeout=self.read_timeout)
        self._connection_attempts = 0  # Reset on success
        return True
    except serial.SerialException as e:
        self._connection_attempts += 1
        logger.error(f"RFID connection failed (attempt {self._connection_attempts}): {e}")
        return False

# ✅ Graceful shutdown
def disconnect(self):
    if self.ser and self.ser.is_open:
        try:
            self.ser.close()
            logger.info("RFID disconnected successfully")
        except Exception as e:
            logger.warning(f"RFID disconnect warning: {e}")
```

### Inbound Service Production Readiness
```python
# services/inbound_service.py - Production validation points

# ✅ Transaction safety
async def process_tag(self, tag: RFIDTag) -> InboundResult:
    try:
        # Lookup SKU
        sku = self.db.query(SKU).filter(SKU.epc == tag.epc).first()
        if not sku:
            logger.warning(f"Unknown EPC: {tag.epc}")
            return InboundResult(success=False, message="Unknown EPC")
        
        # Update inventory with transaction
        self.db.execute(
            "UPDATE inventory SET quantity = quantity + 1 WHERE sku_id = :sku_id",
            {"sku_id": sku.id}
        )
        self.db.commit()
        logger.info(f"Inventory updated for SKU {sku.id}")
        return InboundResult(success=True, sku_id=sku.id)
        
    except Exception as e:
        self.db.rollback()
        logger.exception(f"Inbound processing failed: {e}")
        raise BusinessException("Inbound processing error", error_code="INB_001")
```

## Usage Instructions

When user invokes this skill, follow this process:

1. **Assess current implementation state**
   - What feature/module is being developed?
   - What production requirements apply?

2. **Run production readiness checklist**
   - Check all items in Section 7
   - Document any gaps

3. **Validate against forbidden patterns**
   - Scan for patterns in Section 9
   - Fix any violations

4. **Provide production recommendations**
   - Specific improvements needed
   - Priority order (security > reliability > performance)

5. **Generate production deployment decision**
   - READY: All checks pass
   - NOT READY: List specific gaps and remediation steps

## Continuous Improvement

This skill should be updated when:
- New production requirements emerge
- New forbidden patterns discovered
- Performance benchmarks change
- Security vulnerabilities found
- Deployment process improvements

Update process:
1. Identify the change
2. Validate with production evidence
3. Update this SKILL.md
4. Communicate to development team
5. Enforce in next development cycle