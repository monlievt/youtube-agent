"""
app/services/metadata_service.py
Hermes AI metadata generation service.
Sesuai blueprint Tahap 2: Generate title, description, tags via OpenRouter.
"""
import json
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import MetadataValidationError
from app.core.logging import get_logger
from app.gateways.openrouter_gateway import OpenRouterGateway
from app.models.history import MetadataHistory
from app.models.queue import UploadQueue, VideoTag
from app.repositories.config_repo import ConfigRepository
from app.repositories.queue_repo import QueueRepository
from app.schemas.metadata import MetadataOutput

log = get_logger(__name__)

# Prompt templates per genre
GENRE_PROMPTS: dict[str, str] = {
    "lofi": (
        "Kamu adalah ahli SEO YouTube untuk channel musik lofi. "
        "Buat metadata yang menarik, cozy, dan relevan untuk pendengar lofi hip hop."
    ),
    "phonk": (
        "Kamu adalah ahli SEO YouTube untuk channel musik phonk. "
        "Buat metadata yang energetik, dark, dan relevan untuk komunitas phonk."
    ),
    "jazz": (
        "Kamu adalah ahli SEO YouTube untuk channel musik jazz. "
        "Buat metadata yang elegan, sophisticated, dan relevan untuk pecinta jazz."
    ),
    "ambient": (
        "Kamu adalah ahli SEO YouTube untuk channel musik ambient. "
        "Buat metadata yang menenangkan, atmospheric, dan relevan untuk pendengar ambient."
    ),
    "default": (
        "Kamu adalah ahli SEO YouTube untuk channel musik. "
        "Buat metadata yang menarik dan relevan untuk video musik."
    ),
}

USER_PROMPT_TEMPLATE = """
Buatkan metadata YouTube untuk video musik berikut:
- Genre: {genre}
- Nama file: {filename}

Kembalikan HANYA JSON valid dengan format ini (tidak ada teks lain):
{{
  "title": "judul video (max 100 karakter, CTR-oriented, dalam Bahasa Indonesia)",
  "description": "deskripsi video (max 5000 karakter, keyword-rich, dalam Bahasa Indonesia, sertakan tracklist jika relevan)",
  "tags": ["tag1", "tag2", "tag3"]
}}

Aturan tags:
- Maksimal 15 tags
- Setiap tag maksimal 30 karakter
- Mix antara genre-specific dan general music tags
"""


class MetadataService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._queue_repo = QueueRepository(session)
        self._config_repo = ConfigRepository(session)

    async def generate_for_queue_item(self, queue_item: UploadQueue) -> MetadataOutput:
        """
        Generate metadata AI untuk satu item queue.
        Menggunakan MetadataPattern jika tersedia dan aktif untuk channel bersangkutan.
        Retry max 2x jika validasi gagal, lalu FAILED_PERMANENT.
        """
        timeout_sec = await self._config_repo.get_int("openrouter_timeout_sec")
        primary_model = await self._config_repo.get_value("openrouter_primary")
        fallback_model = await self._config_repo.get_value("openrouter_fallback")
        last_resort_model = await self._config_repo.get_value("openrouter_last_resort")

        gateway = OpenRouterGateway(
            model_chain=[primary_model, fallback_model, last_resort_model],
            timeout_seconds=timeout_sec,
        )

        # Ambil genre dari channel
        channel = queue_item.channel
        genre = channel.genre if channel else "default"
        filename = queue_item.staging_path.split("/")[-1]

        # Ambil pola aktif jika ada
        from app.repositories.channel_repo import ChannelRepository
        channel_repo = ChannelRepository(self._session)
        patterns = await channel_repo.get_patterns(queue_item.channel_id)
        active_pattern = next((p for p in patterns if p.is_active), None)

        if active_pattern:
            queue_item.pattern_id = active_pattern.id
            system_prompt = (
                "Kamu adalah ahli SEO YouTube untuk channel musik. "
                "Buat metadata video yang sangat menarik dan CTR-oriented berdasarkan instruksi pola kustom dari pengguna."
            )
            user_prompt = f"""
Buatkan metadata YouTube untuk video musik berikut:
- Genre: {genre}
- Nama file: {filename}
- Pola/Aturan Judul: {active_pattern.title_template}
- Pola/Aturan Deskripsi: {active_pattern.description_template}
- Tag Tambahan/Pola Tag: {active_pattern.tags_template or "Tidak ada"}

Aturan Penting:
1. Ikuti pola/aturan judul dan deskripsi di atas dengan sangat ketat dan kreatif.
2. Pastikan hasil bervariasi dan unik untuk setiap nama file video yang berbeda.
3. Kembalikan HANYA JSON valid dengan format ini (tidak ada teks lain):
{{
  "title": "judul video (max 100 karakter)",
  "description": "deskripsi video (max 5000 karakter)",
  "tags": ["tag1", "tag2", "tag3"]
}}
"""
        else:
            system_prompt = GENRE_PROMPTS.get(genre.lower(), GENRE_PROMPTS["default"])
            user_prompt = USER_PROMPT_TEMPLATE.format(genre=genre, filename=filename)

        max_retries = 2
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                raw_text, model_used = gateway.generate_text(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                )

                metadata = self._parse_and_validate(raw_text)

                log.info(
                    "metadata_generated",
                    queue_id=queue_item.id,
                    channel_id=queue_item.channel_id,
                    model=model_used,
                    attempt=attempt + 1,
                    agent="hermes",
                    function="generate_for_queue_item",
                )
                return metadata

            except (MetadataValidationError, ValueError) as e:
                last_error = e
                log.warning(
                    "metadata_validation_failed_retrying",
                    queue_id=queue_item.id,
                    attempt=attempt + 1,
                    error=str(e),
                )
                continue

        raise MetadataValidationError(
            f"Metadata generation gagal setelah {max_retries + 1} percobaan. "
            f"Last error: {last_error}"
        )

    async def generate_test_pattern(
        self,
        channel_id: int,
        title_template: str,
        description_template: str,
        tags_template: str | None,
        filename: str,
    ) -> MetadataOutput:
        """Simulasi generate metadata menggunakan pola kustom untuk testing."""
        from app.repositories.channel_repo import ChannelRepository
        channel_repo = ChannelRepository(self._session)
        channel = await channel_repo.get_by_id(channel_id)
        genre = channel.genre if channel else "default"

        timeout_sec = await self._config_repo.get_int("openrouter_timeout_sec")
        primary_model = await self._config_repo.get_value("openrouter_primary")
        fallback_model = await self._config_repo.get_value("openrouter_fallback")
        last_resort_model = await self._config_repo.get_value("openrouter_last_resort")

        gateway = OpenRouterGateway(
            model_chain=[primary_model, fallback_model, last_resort_model],
            timeout_seconds=timeout_sec,
        )

        system_prompt = (
            "Kamu adalah ahli SEO YouTube untuk channel musik. "
            "Buat metadata video yang sangat menarik dan CTR-oriented berdasarkan instruksi pola kustom dari pengguna."
        )

        user_prompt = f"""
Buatkan metadata YouTube untuk video musik berikut:
- Genre: {genre}
- Nama file: {filename}
- Pola/Aturan Judul: {title_template}
- Pola/Aturan Deskripsi: {description_template}
- Tag Tambahan/Pola Tag: {tags_template or "Tidak ada"}

Aturan Penting:
1. Ikuti pola/aturan judul dan deskripsi di atas dengan sangat ketat dan kreatif.
2. Jangan membuat judul atau deskripsi yang sama persis jika diberikan input berbeda.
3. Kembalikan HANYA JSON valid dengan format ini (tidak ada teks lain):
{{
  "title": "judul video (max 100 karakter)",
  "description": "deskripsi video (max 5000 karakter)",
  "tags": ["tag1", "tag2", "tag3"]
}}
"""
        raw_text, model_used = gateway.generate_text(
            prompt=user_prompt,
            system_prompt=system_prompt,
        )
        return self._parse_and_validate(raw_text)


    def _parse_and_validate(self, raw_text: str) -> MetadataOutput:
        """Parse JSON dari AI output dan validasi via Pydantic."""
        # Extract JSON dari response (kadang ada text di sekitar JSON)
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if not json_match:
            raise MetadataValidationError(
                f"Tidak ada JSON dalam response AI: {raw_text[:200]}"
            )

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            raise MetadataValidationError(f"JSON tidak valid: {e}") from e

        try:
            return MetadataOutput(**data)
        except Exception as e:
            raise MetadataValidationError(f"Validasi Pydantic gagal: {e}") from e

    async def save_metadata_to_queue(
        self,
        queue_item: UploadQueue,
        metadata: MetadataOutput,
    ) -> None:
        """Simpan metadata hasil AI ke queue dan history."""
        # Update queue item
        queue_item.title_generated = metadata.title
        queue_item.description_generated = metadata.description
        queue_item.title_final = metadata.title  # Default, bisa di-override human
        queue_item.description_final = metadata.description

        # Simpan tags
        tags = [
            VideoTag(
                queue_id=queue_item.id,
                tag=tag,
                position=idx,
                source="AI",
            )
            for idx, tag in enumerate(metadata.tags)
        ]
        await self._queue_repo.add_tags(tags)

        # Audit trail
        for field_name, new_value in [
            ("title", metadata.title),
            ("description", metadata.description),
            ("tags", ", ".join(metadata.tags)),
        ]:
            await self._queue_repo.write_metadata_history(
                MetadataHistory(
                    queue_id=queue_item.id,
                    field_name=field_name,
                    old_value=None,
                    new_value=new_value[:500] if new_value else None,
                    changed_by="AI",
                    change_reason="Initial AI generation",
                )
            )

        await self._session.flush()
