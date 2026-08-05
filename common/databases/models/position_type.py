from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from common.databases.models.base import Base
from common.utils.snowflake import generate_id


class PositionType(Base):
    """Boss position taxonomy node with an exact, path-based tree identity."""

    __tablename__ = "position_type"
    __table_args__ = (
        UniqueConstraint("path", name="uq_position_type_path"),
        Index("idx_position_type_parent_order", "parent_id", "sort_order"),
        Index("idx_position_type_code_level", "code", "level"),
        Index("idx_position_type_name", "name"),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id)
    code = Column(Integer, nullable=False)
    name = Column(String(120), nullable=False)
    parent_id = Column(
        BigInteger,
        ForeignKey("position_type.id", ondelete="CASCADE"),
        nullable=True,
    )
    parent_code = Column(Integer, nullable=True)
    level = Column(Integer, nullable=False)
    path = Column(String(255), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    is_leaf = Column(Boolean, nullable=False, default=False)

    tip = Column(Text, nullable=True)
    first_char = Column(String(8), nullable=True)
    pinyin = Column(String(200), nullable=True)
    rank = Column(Integer, nullable=False, default=0)
    mark = Column(Integer, nullable=False, default=0)
    source_position_type = Column(Integer, nullable=False, default=0)
    city_type = Column(Integer, nullable=False, default=0)
    capital = Column(Integer, nullable=False, default=0)
    color = Column(String(50), nullable=True)
    recruitment_type = Column(String(50), nullable=True)
    city_code = Column(String(30), nullable=True)
    region_code = Column(Integer, nullable=False, default=0)
    center_geo = Column(JSONB, nullable=True)
    value = Column(JSONB, nullable=True)
    source_payload = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    parent = relationship(
        "PositionType",
        remote_side=[id],
        backref="children",
        foreign_keys=[parent_id],
    )

    def __repr__(self):
        return f"<PositionType(code={self.code}, name={self.name!r}, path={self.path!r})>"
