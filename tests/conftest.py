"""
tests/conftest.py
Pytest fixtures untuk unit dan integration tests.
"""
import os
from cryptography.fernet import Fernet
if "HERMES_MASTER_KEY" not in os.environ:
    os.environ["HERMES_MASTER_KEY"] = Fernet.generate_key().decode()

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture
async def db_session():
    """In-memory SQLite session untuk unit tests (bukan MySQL)."""
    # Untuk integration tests pakai testcontainers dengan MySQL
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with session_factory() as session:
        yield session

    await engine.dispose()
