"""
tests/unit/test_alert_service.py
Unit tests untuk AlertService.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.alert_service import AlertService


@pytest.mark.asyncio
async def test_send_alert_without_webhook():
    """Memastikan alert diskip gracefully jika tidak ada webhook URL."""
    service = AlertService(webhook_url=None)
    result = await service.send_alert("Test message")
    assert result is False


@pytest.mark.asyncio
async def test_send_alert_success():
    """Memastikan webhook alert berhasil dikirim ke URL."""
    service = AlertService(webhook_url="https://discord.com/api/webhooks/mock")
    
    mock_response = AsyncMock()
    mock_response.status_code = 204
    mock_response.raise_for_status = MagicMock()
    
    # Mock httpx AsyncClient
    with patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
        result = await service.alert_upload_failed(
            queue_id=1,
            filename="staging/test.mp4",
            error_message="Connection timeout"
        )
        assert result is True
        mock_post.assert_called_once()
        
        # Verify payload structure
        args, kwargs = mock_post.call_args
        assert "embeds" in kwargs["json"]
        assert "Upload Gagal Permanen" in kwargs["json"]["embeds"][0]["description"]
