#!/usr/bin/env python3
"""
scripts/manual_upload.py
Upload manual 1 video ke 1 channel via script — sesuai blueprint Fase 1A.
Digunakan untuk test awal sebelum sistem otomatis berjalan.

Usage:
    python scripts/manual_upload.py \
        --channel_id 1 \
        --video /path/to/video.mp4 \
        --thumbnail /path/to/thumb.jpg \
        --title "Test Video" \
        --publish_at "2026-06-20T22:00:00+07:00"
"""
import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Tambahkan root project ke path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.gateways.youtube_gateway import YouTubeGateway
from app.core.database import AsyncSessionLocal
from app.services.credential_service import CredentialService


async def manual_upload(
    channel_id: int,
    video_path: str,
    thumbnail_path: str | None,
    title: str,
    description: str,
    publish_at: str,
) -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    print(f"\n=== Hermes Manual Upload ===")
    print(f"Channel ID  : {channel_id}")
    print(f"Video       : {video_path}")
    print(f"Thumbnail   : {thumbnail_path or '(tidak ada)'}")
    print(f"Judul       : {title}")
    print(f"Publish At  : {publish_at}")
    print("")

    if not Path(video_path).exists():
        print(f"ERROR: File video tidak ditemukan: {video_path}")
        sys.exit(1)

    # Parse publish_at
    try:
        publish_datetime = datetime.fromisoformat(publish_at)
    except ValueError as e:
        print(f"ERROR: Format publish_at tidak valid: {e}")
        print("Format: 2026-06-20T22:00:00+07:00")
        sys.exit(1)

    # Ambil credentials dari DB
    async with AsyncSessionLocal() as session:
        cred_service = CredentialService(session)
        try:
            client_id, client_secret, refresh_token = (
                await cred_service.get_decrypted_credentials(channel_id, actor="manual_upload_script")
            )
        except Exception as e:
            print(f"ERROR: Gagal ambil credentials untuk channel {channel_id}: {e}")
            print("Pastikan OAuth sudah di-setup via /auth/youtube/{channel_id}")
            sys.exit(1)

    # Upload
    yt = YouTubeGateway(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        channel_id=channel_id,
    )

    print("1. Mengupload video...")
    youtube_video_id = yt.upload_video(
        video_path=video_path,
        title=title,
        description=description,
        tags=["hermes", "test"],
    )
    print(f"   ✓ Video uploaded: {youtube_video_id}")

    if thumbnail_path and Path(thumbnail_path).exists():
        print("2. Mengupload thumbnail...")
        yt.upload_thumbnail(youtube_video_id, thumbnail_path)
        print("   ✓ Thumbnail uploaded")
    else:
        print("2. Skip thumbnail")

    print(f"3. Set scheduled publish: {publish_at}...")
    yt.set_scheduled(youtube_video_id, publish_datetime)
    print(f"   ✓ Dijadwalkan pada {publish_at}")

    print(f"\n✅ SELESAI!")
    print(f"   YouTube Video ID : {youtube_video_id}")
    print(f"   URL              : https://studio.youtube.com/video/{youtube_video_id}/edit")
    print(f"   Cek di YouTube Studio bahwa video muncul sebagai Scheduled\n")


def main():
    parser = argparse.ArgumentParser(description="Hermes Manual Upload")
    parser.add_argument("--channel_id", type=int, required=True)
    parser.add_argument("--video", required=True, help="Path ke file video")
    parser.add_argument("--thumbnail", default=None, help="Path ke thumbnail JPG")
    parser.add_argument("--title", required=True, help="Judul video (max 100 chars)")
    parser.add_argument("--description", default="", help="Deskripsi video")
    parser.add_argument(
        "--publish_at",
        required=True,
        help="Waktu publish ISO 8601: 2026-06-20T22:00:00+07:00",
    )

    args = parser.parse_args()

    if len(args.title) > 100:
        print(f"ERROR: Judul terlalu panjang ({len(args.title)} chars). Max 100.")
        sys.exit(1)

    asyncio.run(
        manual_upload(
            channel_id=args.channel_id,
            video_path=args.video,
            thumbnail_path=args.thumbnail,
            title=args.title,
            description=args.description,
            publish_at=args.publish_at,
        )
    )


if __name__ == "__main__":
    main()
