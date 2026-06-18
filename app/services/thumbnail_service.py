"""
app/services/thumbnail_service.py
Thumbnail generation: FFmpeg frame extraction + Pillow overlay.
Sesuai blueprint Tahap 3: output 1280x720 JPG < 2MB.
"""
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.core.exceptions import InfrastructureError
from app.core.logging import get_logger

log = get_logger(__name__)

THUMBNAIL_WIDTH = 1280
THUMBNAIL_HEIGHT = 720
MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024  # 2MB


class ThumbnailService:

    def __init__(self, templates_dir: str):
        self._templates_dir = Path(templates_dir)

    def extract_frame(self, video_path: str, position_ratio: float = 0.3) -> str:
        """
        Extract frame pada position_ratio dari durasi total video.
        Return: path ke PNG frame sementara di /tmp.
        """
        if not os.path.exists(video_path):
            raise InfrastructureError(f"File video tidak ditemukan: {video_path}")

        # Dapatkan durasi video
        duration = self._get_video_duration(video_path)
        seek_seconds = duration * position_ratio

        # Output ke temp file
        _, frame_path = tempfile.mkstemp(suffix=".png", prefix="hermes_frame_")

        cmd = [
            "ffmpeg",
            "-ss", str(seek_seconds),
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",
            "-y",  # Overwrite tanpa konfirmasi
            frame_path,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )
            log.info(
                "frame_extracted",
                video_path=video_path,
                seek_seconds=seek_seconds,
                frame_path=frame_path,
                function="extract_frame",
            )
            return frame_path

        except subprocess.CalledProcessError as e:
            log.error(
                "frame_extraction_failed",
                video_path=video_path,
                stderr=e.stderr[:500],
                error_message=str(e),
            )
            # Cleanup temp file jika gagal
            if os.path.exists(frame_path):
                os.unlink(frame_path)
            raise InfrastructureError(f"FFmpeg gagal extract frame: {e.stderr[:200]}") from e

    def _get_video_duration(self, video_path: str) -> float:
        """Dapatkan durasi video dalam detik via ffprobe."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True, timeout=30
            )
            return float(result.stdout.strip())
        except Exception as e:
            raise InfrastructureError(f"Tidak bisa baca durasi video: {e}") from e

    def load_template(self, channel_id: int, genre: str) -> str:
        """
        Cari template PNG untuk channel.
        Fallback: genre default → default.png
        """
        # 1. Template spesifik channel
        channel_template = self._templates_dir / str(channel_id) / "default.png"
        if channel_template.exists():
            return str(channel_template)

        # 2. Template genre
        genre_template = self._templates_dir / f"{genre.lower()}_default.png"
        if genre_template.exists():
            return str(genre_template)

        # 3. Default fallback
        default_template = self._templates_dir / "default.png"
        if default_template.exists():
            return str(default_template)

        raise InfrastructureError(
            f"Tidak ada template thumbnail di {self._templates_dir}. "
            "Buat minimal satu file 'default.png' (1280x720 PNG)."
        )

    def create_thumbnail(
        self,
        frame_path: str,
        template_path: str,
        title: str,
        output_path: str,
    ) -> str:
        """
        Composite frame + template overlay + judul teks.
        Output: JPG 1280x720, < 2MB.
        Return: output_path.
        """
        # Buka frame dan template
        with Image.open(frame_path) as frame:
            frame = frame.convert("RGBA").resize(
                (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), Image.LANCZOS
            )

        with Image.open(template_path) as template:
            template = template.convert("RGBA").resize(
                (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), Image.LANCZOS
            )

        # Composite: frame sebagai background, template di atas
        composite = Image.alpha_composite(frame, template)

        # Overlay judul teks
        composite = self._add_title_overlay(composite, title)

        # Convert ke RGB untuk JPG
        rgb_image = composite.convert("RGB")

        # Simpan dan compress jika perlu
        quality = 95
        while True:
            rgb_image.save(output_path, "JPEG", quality=quality)
            file_size = os.path.getsize(output_path)
            if file_size <= MAX_THUMBNAIL_BYTES or quality <= 50:
                break
            quality -= 5

        log.info(
            "thumbnail_created",
            output_path=output_path,
            file_size_kb=int(file_size / 1024),
            quality=quality,
            function="create_thumbnail",
        )
        return output_path

    def _add_title_overlay(self, image: Image.Image, title: str) -> Image.Image:
        """Tambahkan teks judul dengan word wrap dan drop shadow."""
        draw = ImageDraw.Draw(image)

        # Font — gunakan default jika tidak ada font custom
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        except OSError:
            font = ImageFont.load_default()

        # Word wrap sederhana
        max_width = THUMBNAIL_WIDTH - 80  # 40px padding kanan-kiri
        words = title.split()
        lines = []
        current_line = ""

        for word in words:
            test_line = f"{current_line} {word}".strip()
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)

        # Gambar teks di bawah gambar dengan drop shadow
        y = THUMBNAIL_HEIGHT - (len(lines) * 60) - 30
        for line in lines:
            # Drop shadow
            draw.text((42, y + 2), line, font=font, fill=(0, 0, 0, 200))
            # Teks utama
            draw.text((40, y), line, font=font, fill=(255, 255, 255, 255))
            y += 60

        return image
