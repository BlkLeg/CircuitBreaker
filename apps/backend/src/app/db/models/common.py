"""Cross-cutting labels and documents, and the polymorphic join tables that attach them to
any entity.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models._shared import _now
from app.db.session import Base

# ── Common ─────────────────────────────────────────────────────────────────


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    color: Mapped[str | None] = mapped_column(String, nullable=True)


class Doc(Base):
    __tablename__ = "docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    # v0.1.2: sidebar organisation & per-doc identity
    category: Mapped[str] = mapped_column(String, nullable=False, server_default="")
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    icon: Mapped[str] = mapped_column(String, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class EntityTag(Base):
    __tablename__ = "entity_tags"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id", "tag_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    tag_id: Mapped[int] = mapped_column(Integer, ForeignKey("tags.id"), nullable=False)

    tag: Mapped["Tag"] = relationship("Tag")


class EntityDoc(Base):
    __tablename__ = "entity_docs"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id", "doc_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    doc_id: Mapped[int] = mapped_column(Integer, ForeignKey("docs.id"), nullable=False)

    doc: Mapped["Doc"] = relationship("Doc")
