"""
Tests for Feature Gating:
1. System Logs 3-record limit & masking for trial users
2. MPLS 3-day trial limit for trial users vs unlimited for paid users
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from models.client import Client


class TestFeatureGating:

    def test_client_is_paid_property(self):
        # Trial user with starter plan
        trial_client = Client(username="test_trial", subscription="starter", is_trial=True, subscription_status="active")
        assert trial_client.is_paid is False

        # Paid user with starter plan
        paid_client = Client(username="test_paid", subscription="starter", is_trial=False, subscription_status="active")
        assert paid_client.is_paid is True

        # Inactive user
        inactive_client = Client(username="test_inact", subscription="pro", is_trial=False, subscription_status="inactive")
        assert inactive_client.is_paid is False

    def test_client_mpls_allowed_property(self):
        # Paid client: always allowed
        paid_client = Client(username="paid_mpls", is_trial=False, subscription_status="active")
        assert paid_client.is_mpls_allowed is True
        assert paid_client.mpls_days_remaining is None

        # Trial client with fresh trial (3 days)
        fresh_trial = Client(
            username="fresh_trial",
            is_trial=True,
            subscription_status="active",
            mpls_activated_at=datetime.utcnow(),
            mpls_trial_expires_at=datetime.utcnow() + timedelta(days=3)
        )
        assert fresh_trial.is_mpls_allowed is True
        assert fresh_trial.mpls_days_remaining >= 1

        # Trial client with expired trial
        expired_trial = Client(
            username="expired_trial",
            is_trial=True,
            subscription_status="active",
            mpls_activated_at=datetime.utcnow() - timedelta(days=4),
            mpls_trial_expires_at=datetime.utcnow() - timedelta(days=1)
        )
        assert expired_trial.is_mpls_allowed is False
        assert expired_trial.mpls_days_remaining == 0

    def test_fastapi_system_logs_gating_logic(self):
        from fastapi_app.routes.client.system_logs import list_logs
        from fastapi_app.services.client.session import ClientSession

        # Mock 5 entries
        raw_entries = [
            {"id": i, "time": "2026-09-28T10:00:00Z", "level": "notice", "category": "system", "message": f"Log msg {i}"}
            for i in range(1, 6)
        ]

        with patch("fastapi_app.services.client.system_logs_service.list_logs") as mock_list, \
             patch("fastapi_app.routes.client.system_logs.is_paid_client") as mock_paid:

            mock_list.side_effect = lambda *a, **kw: {
                "entries": [dict(e) for e in raw_entries],
                "page": {"limit": 50, "count": 5, "has_more": False},
                "last_id": 5
            }

            # 1. Unpaid trial client
            mock_paid.return_value = False
            session = ClientSession(customer_id="trial-id", csrf_token="tok")
            peer = {"id": "peer-1", "ip": "100.64.0.1", "connected": True}

            res = list_logs(peer=peer, session=session)
            assert res["is_gated"] is True
            assert res["gated_count"] == 2
            assert len(res["entries"]) == 5
            # First 3 are intact
            assert res["entries"][0]["message"] == "Log msg 1"
            assert res["entries"][1]["message"] == "Log msg 2"
            assert res["entries"][2]["message"] == "Log msg 3"
            # Entries 4 and 5 are masked
            assert res["entries"][3]["code"] == "premium_only"
            assert res["entries"][3]["message"] == "Available with Premium plan"
            assert res["entries"][4]["code"] == "premium_only"

            # 2. Paid client
            mock_paid.return_value = True
            res_paid = list_logs(peer=peer, session=session)
            assert res_paid.get("is_gated") in (False, None)
            assert res_paid["entries"][3]["message"] == "Log msg 4"
