"""
Integration tests — DB layer (requires running postgres via docker-compose).
Run: pytest src/tests/test_integration_db.py -v -m integration

Skips automatically if postgres is not reachable.
"""
import json
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
async def db_pool():
    """Initialize real DB pool. Skip module if postgres not reachable."""
    try:
        from src.db.database import init_db, close_db
        pool = await init_db()
        yield pool
        await close_db()
    except Exception as e:
        pytest.skip(f"Postgres not reachable: {e}")


class TestAuditLoggerDBPersistence:

    async def test_persist_writes_row(self, db_pool):
        from src.security.audit_logger import AuditLogger, AuditEvent, AuditEventType

        inst = AuditLogger(log_to_db=True)
        event = AuditEvent(
            AuditEventType.CALL_START,
            session_id="int-test-session-001",
            caller_hash="a" * 64,
            language="es",
            call_sid="CAinttest001",
        )

        await inst._persist_to_db(event)

        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT event_type, session_id FROM audit_logs WHERE event_id = $1",
                event.event_id,
            )
            await conn.execute(
                "DELETE FROM audit_logs WHERE event_id = $1", event.event_id
            )

        assert row is not None
        assert row["event_type"] == "call_start"
        assert row["session_id"] == "int-test-session-001"

    async def test_duplicate_event_id_ignored(self, db_pool):
        from src.security.audit_logger import AuditLogger, AuditEvent, AuditEventType

        inst = AuditLogger(log_to_db=True)
        event = AuditEvent(
            AuditEventType.CALL_END,
            session_id="int-test-session-002",
            caller_hash="b" * 64,
        )

        await inst._persist_to_db(event)
        await inst._persist_to_db(event)  # ON CONFLICT DO NOTHING — must not raise

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM audit_logs WHERE event_id = $1", event.event_id
            )
            await conn.execute(
                "DELETE FROM audit_logs WHERE event_id = $1", event.event_id
            )

        assert count == 1

    async def test_data_stored_as_jsonb(self, db_pool):
        from src.security.audit_logger import AuditLogger, AuditEvent, AuditEventType

        inst = AuditLogger(log_to_db=True)
        event = AuditEvent(
            AuditEventType.RAG_QUERY,
            session_id="int-test-session-003",
            caller_hash="c" * 64,
            chunks_returned=3,
            top_score=0.87,
            evidence_found=True,
        )

        await inst._persist_to_db(event)

        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT data FROM audit_logs WHERE event_id = $1", event.event_id
            )
            await conn.execute(
                "DELETE FROM audit_logs WHERE event_id = $1", event.event_id
            )

        assert row is not None
        data = row["data"]
        assert data["chunks_returned"] == 3
        assert data["evidence_found"] is True

    async def test_db_error_does_not_raise(self, db_pool):
        """_persist_to_db swallows exceptions to avoid interrupting a live call."""
        from src.security.audit_logger import AuditLogger, AuditEvent, AuditEventType
        from unittest.mock import AsyncMock, patch, MagicMock

        inst = AuditLogger(log_to_db=True)
        event = AuditEvent(AuditEventType.ERROR, session_id="err-test")

        # Simulate DB failure
        broken_pool = MagicMock()
        broken_pool.acquire.return_value.__aenter__ = AsyncMock(
            side_effect=RuntimeError("DB gone")
        )
        broken_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("src.db.database.get_db_pool", AsyncMock(return_value=broken_pool)):
            await inst._persist_to_db(event)  # must not raise


class TestAuditLogsTableConstraints:

    async def test_event_id_unique_constraint_exists(self, db_pool):
        """Verify audit_logs table has unique constraint on event_id."""
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT constraint_name FROM information_schema.table_constraints
                WHERE table_name = 'audit_logs'
                  AND constraint_type = 'UNIQUE'
                  AND constraint_name LIKE '%event_id%'
                """
            )
        assert row is not None

    async def test_v_daily_metrics_view_queryable(self, db_pool):
        """v_daily_metrics view must be queryable (GDPR dashboard)."""
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM v_daily_metrics LIMIT 1")
        assert isinstance(rows, list)
