"""长期记忆表模型（SQLAlchemy）。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, JSON, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AgentUserProfile(Base):
    __tablename__ = "agent_user_profile"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    genre_prefs: Mapped[dict | None] = mapped_column(JSON)
    actor_prefs: Mapped[dict | None] = mapped_column(JSON)
    director_prefs: Mapped[dict | None] = mapped_column(JSON)
    region_prefs: Mapped[dict | None] = mapped_column(JSON)
    rating_tendency: Mapped[dict | None] = mapped_column(JSON)
    scene_prefs: Mapped[dict | None] = mapped_column(JSON)
    watch_prefs: Mapped[dict | None] = mapped_column(JSON)
    profile_summary: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class AgentPreferenceEvent(Base):
    __tablename__ = "agent_preference_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[int | None] = mapped_column()
    item_type: Mapped[str | None] = mapped_column(String(20))
    item_value: Mapped[str | None] = mapped_column(String(100))
    weight: Mapped[int | None] = mapped_column(default=1)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
