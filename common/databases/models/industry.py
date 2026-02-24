from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint, BigInteger
from sqlalchemy.orm import relationship
from .base import Base
from common.utils.snowflake import generate_id


class Industry(Base):
    """
    行业表模型
    支持行业-子行业多级结构
    """
    __tablename__ = 'industries'
    
    # 主键
    id = Column(BigInteger, primary_key=True, default=generate_id)
    
    __table_args__ = (
        UniqueConstraint('code', name='uq_industry_code'),
    )

    # 行业编码（BOSS直聘的code字段）
    code = Column(Integer, nullable=False, unique=True, index=True, comment='行业编码')
    
    # 行业名称
    name = Column(String(100), nullable=False, comment='行业名称')
    
    # 拼音和首字母
    pinyin = Column(String(100), nullable=True, comment='拼音')
    first_char = Column(String(1), nullable=True, comment='首字母')
    
    # 层级关系
    parent_id = Column(Integer, ForeignKey('industries.code'), nullable=True, comment='父级ID')
    level = Column(Integer, nullable=False, default=0, comment='层级：0-一级行业，1-二级行业')
    
    # 其他属性
    tip = Column(Text, nullable=True, comment='提示信息')
    rank = Column(Integer, nullable=True, default=0, comment='排序')
    mark = Column(Integer, nullable=True, default=0, comment='标记')
    position_type = Column(Integer, nullable=True, default=0, comment='职位类型')
    city_type = Column(Integer, nullable=True, comment='城市类型')
    capital = Column(Integer, nullable=True, default=0, comment='是否省会')
    color = Column(String(20), nullable=True, comment='颜色')
    recruitment_type = Column(String(50), nullable=True, comment='招聘类型')
    city_code = Column(String(20), nullable=True, comment='城市代码')
    region_code = Column(Integer, nullable=True, comment='行政区划代码')
    center_geo = Column(String(50), nullable=True, comment='中心点坐标')
    value = Column(String(100), nullable=True, comment='值')
    
    # 时间戳
    created_at = Column(DateTime, nullable=True, comment='创建时间')
    updated_at = Column(DateTime, nullable=True, comment='更新时间')
    
    # 自关联关系
    parent = relationship('Industry', remote_side=[code], backref='children',foreign_keys=[parent_id])
    
    jobs = relationship('Job', back_populates='industry')
    
    
    def __repr__(self):
        return f"<Industry(id={self.id}, name='{self.name}')>"
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'tip': self.tip,
            'firstChar': self.first_char,
            'pinyin': self.pinyin,
            'rank': self.rank,
            'mark': self.mark,
            'positionType': self.position_type,
            'cityType': self.city_type,
            'capital': self.capital,
            'color': self.color,
            'recruitmentType': self.recruitment_type,
            'cityCode': self.city_code,
            'regionCode': self.region_code,
            'centerGeo': self.center_geo,
            'value': self.value,
            'parentId': self.parent_id,
            'level': self.level,
            'createdAt': self.created_at,
            'updatedAt': self.updated_at
        }
