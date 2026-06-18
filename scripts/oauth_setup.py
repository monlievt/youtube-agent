#!/usr/bin/env python3
"""
scripts/oauth_setup.py
Helper interaktif untuk OAuth setup channel baru.
Jalankan ini untuk onboard channel tanpa perlu dashboard.

Usage:
    python scripts/oauth_setup.py --channel_id 1
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
from google_auth_oauthlib.flow import InstalledAppFlow
from app.core.database import AsyncSessionLocal
from app.services.credential_service import CredentialService

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


async def setup_oauth(channel_id: int, credentials_file: str) -> None:
    print(f"\n=== Hermes OAuth Setup ===")
    print(f"Channel ID      : {channel_id}")
    print(f"Credentials file: {credentials_file}")
    print("")

    if not Path(credentials_file).exists():
        print(f"ERROR: File credentials.json tidak ditemukan: {credentials_file}")
        print("Download dari Google Cloud Console > APIs & Services > Credentials")
        sys.exit(1)

    # Jalankan OAuth flow via browser lokal
    flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
    print("Membuka browser untuk authorization...")
    credentials = flow.run_local_server(port=0)

    print("\n✓ Authorization berhasil!")
    print("Menyimpan token ke database...")

    async with AsyncSessionLocal() as session:
        cred_service = CredentialService(session)
        await cred_service.save_credentials(
            channel_id=channel_id,
            client_id=credentials.client_id,
            client_secret=credentials.client_secret,
            refresh_token=credentials.refresh_token,
            actor="oauth_setup_script",
        )
        await session.commit()

    print(f"\n✅ Token berhasil disimpan untuk channel {channel_id}!")
    print("Sekarang channel siap digunakan oleh Hermes.\n")


def main():
    parser = argparse.ArgumentParser(description="Hermes OAuth Setup")
    parser.add_argument("--channel_id", type=int, required=True)
    parser.add_argument("--credentials", default="credentials.json", help="Path ke credentials.json")
    args = parser.parse_args()
    asyncio.run(setup_oauth(args.channel_id, args.credentials))


if __name__ == "__main__":
    main()
