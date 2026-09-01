# /opt/networkat_sdwan/core/web_app/tests/test_dns.py
import pytest
from unittest.mock import patch, MagicMock
import requests

from fastapi_app.services.adguard.adguard_service import AdGuardService

@pytest.mark.anyio
@patch("fastapi_app.database.SessionLocal")
@patch("requests.get")
async def test_get_adguard_password_from_db(mock_get, mock_session_local):
    """
    Test that when a custom password exists in the database,
    it is returned directly and the agent is not queried.
    """
    # Mock database session returning a custom password
    mock_session = MagicMock()
    mock_session_local.return_value = mock_session
    mock_session.__enter__.return_value = mock_session
    
    mock_result = MagicMock()
    mock_result.fetchone.return_value = ("custom_db_password",)
    mock_session.execute.return_value = mock_result

    # Run method
    password = await AdGuardService._get_adguard_password("peer_123", "10.0.0.1")
    
    # Assertions
    assert password == "custom_db_password"
    mock_get.assert_not_called()
    mock_session.execute.assert_called_once()


@pytest.mark.anyio
@patch("fastapi_app.database.SessionLocal")
@patch("requests.get")
async def test_get_adguard_password_fallback_to_agent_success(mock_get, mock_session_local):
    """
    Test that when the database does not have a custom password (returns None or default),
    it queries the agent API, updates the database, and returns the agent password.
    """
    # Mock database session returning 'default_password' on first check
    mock_session = MagicMock()
    mock_session_local.return_value = mock_session
    mock_session.__enter__.return_value = mock_session
    
    mock_result = MagicMock()
    mock_result.fetchone.return_value = ("default_password",)
    mock_session.execute.return_value = mock_result

    # Mock agent API response returning json
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"password": "agent_retrieved_password"}
    mock_get.return_value = mock_response

    # Run method
    password = await AdGuardService._get_adguard_password("peer_123", "10.0.0.1")
    
    # Assertions
    assert password == "agent_retrieved_password"
    
    # Verify agent was called
    mock_get.assert_called_once_with("http://10.0.0.1:8765/adguard-credential", timeout=3.0)
    
    # Verify database was updated
    # 2 calls: one to SELECT, one to UPDATE
    assert mock_session.execute.call_count == 2
    mock_session.commit.assert_called_once()


@pytest.mark.anyio
@patch("fastapi_app.database.SessionLocal")
@patch("requests.get")
async def test_get_adguard_password_fallback_to_agent_success_plain_text(mock_get, mock_session_local):
    """
    Test that when the agent returns plain text instead of JSON, it is parsed and used.
    """
    # Mock database session returning None (no peer entry yet)
    mock_session = MagicMock()
    mock_session_local.return_value = mock_session
    mock_session.__enter__.return_value = mock_session
    
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_session.execute.return_value = mock_result

    # Mock agent API response returning plain text
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.side_effect = ValueError("Not JSON")
    mock_response.text = "  plain_text_password_123 \n"
    mock_get.return_value = mock_response

    # Run method
    password = await AdGuardService._get_adguard_password("peer_123", "10.0.0.1")
    
    # Assertions
    assert password == "plain_text_password_123"


@pytest.mark.anyio
@patch("fastapi_app.database.SessionLocal")
@patch("requests.get")
async def test_get_adguard_password_fallback_to_env_if_all_fail(mock_get, mock_session_local):
    """
    Test that when database is empty and agent API call fails (timeout or error),
    it falls back to the default env variable ADGUARD_PASSWORD.
    """
    # Mock database session returning None
    mock_session = MagicMock()
    mock_session_local.return_value = mock_session
    mock_session.__enter__.return_value = mock_session
    
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_session.execute.return_value = mock_result

    # Mock agent API failing
    mock_get.side_effect = requests.RequestException("Connection failed")

    # Run method
    password = await AdGuardService._get_adguard_password("peer_123", "10.0.0.1")
    
    # Assertions
    from fastapi_app.services.adguard.adguard_service import ADGUARD_PASSWORD
    assert password == ADGUARD_PASSWORD


@pytest.mark.anyio
@patch("fastapi_app.database.SessionLocal")
@patch("requests.request")
@patch("requests.get")
def test_sync_call_adguard_api_self_healing_on_401(mock_get, mock_request, mock_session_local):
    """
    Test that when an API call fails with 401 Unauthorized, _sync_call_adguard_api queries
    the agent to refresh the credentials, saves the new password to DB, and retries the call.
    """
    # First request call raises HTTPError with 401 status
    mock_resp_401 = MagicMock()
    mock_resp_401.status_code = 401
    
    # We raise an HTTPError
    from requests.exceptions import HTTPError
    mock_http_err = HTTPError(response=mock_resp_401)
    
    # Second request call succeeds
    mock_resp_success = MagicMock()
    mock_resp_success.status_code = 200
    mock_resp_success.content = b'{"success": true}'
    mock_resp_success.json.return_value = {"success": True}
    
    mock_request.side_effect = [mock_http_err, mock_resp_success]
    
    # Agent query succeeds and returns new password
    mock_agent_resp = MagicMock()
    mock_agent_resp.status_code = 200
    mock_agent_resp.json.return_value = {"password": "refreshed_agent_password"}
    mock_get.return_value = mock_agent_resp
    
    # DB mock
    mock_session = MagicMock()
    mock_session_local.return_value = mock_session
    mock_session.__enter__.return_value = mock_session
    
    # Call the sync API wrapper
    result = AdGuardService._sync_call_adguard_api(
        peer_id="peer_abc",
        peer_ip="10.0.0.100",
        adguard_password="old_wrong_password",
        endpoint="status",
    )
    
    # Assertions
    assert result == {"success": True}
    
    # Assert requests.request was called twice (first with wrong pass, second with refreshed pass)
    assert mock_request.call_count == 2
    
    # First call args
    first_call_kwargs = mock_request.call_args_list[0][1]
    assert first_call_kwargs["auth"] == ("admin", "old_wrong_password")
    
    # Second call args (refreshed)
    second_call_kwargs = mock_request.call_args_list[1][1]
    assert second_call_kwargs["auth"] == ("admin", "refreshed_agent_password")
    
    # Verify agent was called to get credentials
    mock_get.assert_called_once_with("http://10.0.0.100:8765/adguard-credential", timeout=3.0)
    
    # Verify database update was executed
    mock_session.execute.assert_called_once()
    mock_session.commit.assert_called_once()
