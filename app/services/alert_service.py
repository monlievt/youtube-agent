"""
app/services/alert_service.py
Service untuk mengirim notifikasi peringatan (alert) otomatis via webhook (Discord/Telegram).
"""
import httpx
from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)
settings = get_settings()


class AlertService:
    def __init__(self, webhook_url: str | None = None):
        self._webhook_url = webhook_url or settings.discord_webhook_url

    async def send_alert(self, message: str, level: str = "WARNING") -> bool:
        """
        Kirim pesan alarm ke Discord Webhook secara async.
        """
        if not self._webhook_url:
            log.warning("alert_skipped_no_webhook_configured", message=message, level=level)
            return False

        # Format embed Discord agar terlihat premium
        color = 16711680 if level == "CRITICAL" else 16753920  # Red for CRITICAL, Orange for WARNING
        payload = {
            "embeds": [
                {
                    "title": f"⚠️ HERMES ALERT [{level}]",
                    "description": message,
                    "color": color,
                    "timestamp": "" # Discord auto-timestamp if omitted
                }
            ]
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(self._webhook_url, json=payload, timeout=10)
                response.raise_for_status()
                log.info("alert_sent_successfully", message=message[:50])
                return True
        except Exception as e:
            log.error("failed_to_send_alert_webhook", error=str(e), message=message[:50])
            return False

    async def alert_upload_failed(self, queue_id: int, filename: str, error_message: str) -> bool:
        """Kirim alert untuk upload gagal permanen."""
        msg = (
            f"**Upload Gagal Permanen!**\n"
            f"• **Queue ID:** `{queue_id}`\n"
            f"• **File:** `{filename}`\n"
            f"• **Error:** `{error_message}`\n\n"
            f"Silakan periksa di dashboard untuk me-requeue."
        )
        return await self.send_alert(msg, level="CRITICAL")

    async def alert_low_disk(self, path: str, usage_percent: float) -> bool:
        """Kirim alert jika kapasitas storage menipis."""
        msg = (
            f"**Kapasitas Storage Kritis!**\n"
            f"• **Path:** `{path}`\n"
            f"• **Penggunaan:** `{usage_percent}%`"
        )
        return await self.send_alert(msg, level="CRITICAL")
