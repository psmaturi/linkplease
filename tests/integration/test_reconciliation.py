"""
tests/integration/test_reconciliation.py — Tests for bounded reconciliation.
"""
import asyncio
from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, patch

from app.models.dm_attempt import DmAttempt
from app.services.reconciliation_service import reconcile_sent_dms, MAX_RECONCILIATION_ATTEMPTS


@pytest.mark.asyncio
async def test_reconciliation_flow():
    """
    Test 202 -> accepted -> unresolved (timeout) and delivered states.
    """
    # Create fake DmAttempts
    attempt_delivered = DmAttempt(
        id="00000000-0000-0000-0000-000000000001",
        rule_id="00000000-0000-0000-0000-000000000000",
        recipient_user_id="user_1",
        external_dm_id="dm_1",
        status="accepted",
        reconciliation_attempts=0
    )
    
    attempt_stalled = DmAttempt(
        id="00000000-0000-0000-0000-000000000002",
        rule_id="00000000-0000-0000-0000-000000000000",
        recipient_user_id="user_2",
        external_dm_id="dm_2",
        status="accepted",
        reconciliation_attempts=MAX_RECONCILIATION_ATTEMPTS - 1
    )

    attempt_failed = DmAttempt(
        id="00000000-0000-0000-0000-000000000003",
        rule_id="00000000-0000-0000-0000-000000000000",
        recipient_user_id="user_3",
        external_dm_id="dm_3",
        status="accepted",
        reconciliation_attempts=0
    )

    attempts = [attempt_delivered, attempt_stalled, attempt_failed]

    mock_db = AsyncMock()
    class MockResult:
        def scalars(self):
            class MockScalars:
                def all(self):
                    return attempts
            return MockScalars()
            
    mock_db.execute.return_value = MockResult()
    
    mock_pg = AsyncMock()
    
    # Mock responses
    class MockStatus:
        def __init__(self, status):
            self.status = status
            
    async def get_dm_status(dm_id):
        if dm_id == "dm_1":
            return MockStatus("delivered")
        elif dm_id == "dm_2":
            return MockStatus("queued")
        elif dm_id == "dm_3":
            return MockStatus("failed")
        return None
        
    mock_pg.get_dm_status.side_effect = get_dm_status
    
    summary = await reconcile_sent_dms(mock_db, mock_pg)
    
    # Verify summary
    assert summary["checked"] == 3
    assert summary["delivered"] == 1
    assert summary["unresolved"] == 1
    assert summary["newly_failed"] == 1
    
    # Verify state updates
    assert attempt_delivered.status == "delivered"
    assert attempt_stalled.status == "unresolved"
    assert attempt_stalled.reconciliation_attempts == MAX_RECONCILIATION_ATTEMPTS
    assert attempt_failed.status == "failed"
    
    # Verify DB commit was called
    mock_db.commit.assert_called_once()
