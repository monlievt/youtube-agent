"""
app/schemas/metadata.py
Pydantic schema untuk output AI — validasi WAJIB sebelum simpan ke DB.
Sesuai blueprint: title <= 100, description <= 5000, tags <= 15 x <= 30 chars.
"""
from pydantic import BaseModel, Field, field_validator


class MetadataOutput(BaseModel):
    """Output wajib dari Hermes metadata generation."""
    title: str = Field(max_length=100, description="Judul video, CTR-oriented")
    description: str = Field(max_length=5000, description="Deskripsi keyword-rich")
    tags: list[str] = Field(max_length=15, description="List tags, max 15 items")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: list[str]) -> list[str]:
        for tag in tags:
            if len(tag) > 30:
                raise ValueError(f"Tag terlalu panjang ({len(tag)} chars): '{tag}'. Max 30 chars.")
        return tags

    @field_validator("title")
    @classmethod
    def validate_title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title tidak boleh kosong")
        return v.strip()


from datetime import datetime

class MetadataPatternCreate(BaseModel):
    name: str = Field(max_length=100)
    title_template: str = Field(max_length=200)
    description_template: str
    tags_template: str | None = Field(default=None, max_length=500)
    is_active: bool = True


class MetadataPatternResponse(BaseModel):
    id: int
    channel_id: int
    name: str
    title_template: str
    description_template: str
    tags_template: str | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class MetadataPatternUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    title_template: str | None = Field(default=None, max_length=200)
    description_template: str | None = None
    tags_template: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None

