"""
tests/unit/test_metadata_service.py
Unit tests untuk MetadataOutput Pydantic validation.
"""
import pytest
from pydantic import ValidationError

from app.schemas.metadata import MetadataOutput


def test_valid_metadata():
    metadata = MetadataOutput(
        title="Lofi Hip Hop Mix — Relaxing Study Music 2026",
        description="Koleksi lofi terbaik untuk belajar dan bekerja.",
        tags=["lofi", "study music", "relaxing"],
    )
    assert len(metadata.title) <= 100
    assert len(metadata.tags) <= 15


def test_title_too_long():
    with pytest.raises(ValidationError):
        MetadataOutput(
            title="A" * 101,
            description="Valid description",
            tags=["tag1"],
        )


def test_too_many_tags():
    with pytest.raises(ValidationError):
        MetadataOutput(
            title="Valid title",
            description="Valid description",
            tags=[f"tag{i}" for i in range(16)],  # 16 tags — lebih dari max 15
        )


def test_tag_too_long():
    with pytest.raises(ValidationError):
        MetadataOutput(
            title="Valid title",
            description="Valid description",
            tags=["a" * 31],  # Tag 31 karakter — lebih dari max 30
        )


def test_empty_title():
    with pytest.raises(ValidationError):
        MetadataOutput(
            title="   ",  # Whitespace saja
            description="Valid description",
            tags=["tag1"],
        )


def test_title_stripped():
    metadata = MetadataOutput(
        title="  Lofi Mix  ",
        description="Valid",
        tags=["lofi"],
    )
    assert metadata.title == "Lofi Mix"  # Harus di-strip


def test_description_max_length():
    with pytest.raises(ValidationError):
        MetadataOutput(
            title="Valid title",
            description="X" * 5001,  # Lebih dari 5000
            tags=["tag1"],
        )
