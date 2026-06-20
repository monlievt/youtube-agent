"""
app/services/telegram_service.py
Service untuk komunikasi interaktif dua arah via Telegram Bot API.
"""
import os
import json
import httpx
from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)
settings = get_settings()


class TelegramService:
    def __init__(self):
        self._token = settings.telegram_bot_token
        self._chat_id = settings.telegram_chat_id
        self._base_url = f"https://api.telegram.org/bot{self._token}" if self._token else None

    async def send_message(self, text: str, reply_markup: dict | None = None) -> bool:
        """Kirim pesan teks ke chat_id utama."""
        if not self._base_url or not self._chat_id:
            log.warning("telegram_send_message_skipped_no_config", text=text[:50])
            return False

        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(f"{self._base_url}/sendMessage", json=payload, timeout=10)
                res.raise_for_status()
                return True
        except Exception as e:
            log.error("telegram_send_message_failed", error=str(e))
            return False

    async def send_photo(self, photo_path: str, caption: str, reply_markup: dict | None = None) -> bool:
        """Kirim foto (untuk preview thumbnail) ke chat_id utama."""
        if not self._base_url or not self._chat_id or not os.path.exists(photo_path):
            log.warning("telegram_send_photo_skipped", photo_path=photo_path)
            return False

        url = f"{self._base_url}/sendPhoto"
        try:
            async with httpx.AsyncClient() as client:
                with open(photo_path, "rb") as f:
                    files = {"photo": f}
                    data = {
                        "chat_id": self._chat_id,
                        "caption": caption,
                        "parse_mode": "HTML"
                    }
                    if reply_markup:
                        data["reply_markup"] = json.dumps(reply_markup)
                    
                    res = await client.post(url, data=data, files=files, timeout=20)
                    res.raise_for_status()
                    return True
        except Exception as e:
            log.error("telegram_send_photo_failed", error=str(e))
            return False

    async def send_approval_request(self, queue_id: int, filename: str, title: str, description: str, scheduled_time: str) -> bool:
        """Kirim pesan persetujuan upload video dengan inline keyboard buttons."""
        desc_preview = description[:200] + "..." if len(description) > 200 else description
        text = (
            f"🎥 <b>Persetujuan Unggahan Baru</b>\n\n"
            f"• <b>Queue ID:</b> #{queue_id}\n"
            f"• <b>File:</b> <code>{filename}</code>\n"
            f"• <b>Judul AI:</b> {title}\n"
            f"• <b>Deskripsi AI:</b> {desc_preview}\n"
            f"• <b>Rencana Jadwal:</b> {scheduled_time}\n\n"
            f"Setujui untuk mempublikasikan video ini secara terjadwal di YouTube?"
        )
        
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ Setujui", "callback_data": f"approve_upload:{queue_id}"},
                    {"text": "❌ Tolak", "callback_data": f"reject_upload:{queue_id}"}
                ]
            ]
        }
        return await self.send_message(text, reply_markup)

    async def send_thumbnail_approval(self, queue_id: int, filename: str, thumbnail_path: str) -> bool:
        """Kirim preview thumbnail hasil AI dengan inline keyboard buttons."""
        caption = (
            f"🎨 <b>Persetujuan Gambar Mini (Thumbnail)</b>\n\n"
            f"• <b>Queue ID:</b> #{queue_id}\n"
            f"• <b>File Video:</b> <code>{filename}</code>\n\n"
            f"Apakah desain thumbnail di atas sudah sesuai?"
        )
        
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ Setujui", "callback_data": f"approve_thumb:{queue_id}"},
                    {"text": "🔄 Generate Ulang", "callback_data": f"recreate_thumb:{queue_id}"}
                ]
            ]
        }
        return await self.send_photo(thumbnail_path, caption, reply_markup)
