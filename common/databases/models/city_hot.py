# models/city.py
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, Text, BigInteger
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.ext.declarative import declarative_base
from common.utils.snowflake import generate_id

Base = declarative_base()

class CityHot(Base):
    """
    城市表模型
    支持省-市-区县三级结构
    """
    __tablename__ = 'cities_hot'
    # 主键
    id = Column(BigInteger, primary_key=True, default=generate_id)

    # 城市编码（BOSS直聘的code字段）
    code = Column(Integer, nullable=False, unique=True, index=True, comment='城市编码')
    
    # 城市名称
    name = Column(String(100), nullable=False, comment='城市名称')
    
    # 拼音和首字母
    pinyin = Column(String(100), nullable=True, comment='拼音')
    first_char = Column(String(1), nullable=True, comment='首字母')
    
    # 层级关系
    parent_id = Column(BigInteger, ForeignKey('cities_hot.code'), nullable=True, comment='父级ID')
    level = Column(Integer, nullable=False, default=0, comment='层级：0-省，1-市，2-区县')
    
    # 地理信息
    center_geo = Column(String(50), nullable=True, comment='中心点坐标，格式：经度,纬度')
    region_code = Column(Integer, nullable=True, comment='行政区划代码')
    
    # 城市类型
    city_type = Column(Integer, nullable=True, comment='城市类型：0-省，1-市，2-区县，3-县级市')
    position_type = Column(Integer, nullable=True, default=0, comment='职位类型')
    
    # 其他属性
    tip = Column(Text, nullable=True, comment='提示信息')
    rank = Column(Integer, nullable=True, default=0, comment='排序')
    mark = Column(Integer, nullable=True, default=0, comment='标记')
    capital = Column(Integer, nullable=True, default=0, comment='是否省会：0-否，1-是')
    color = Column(String(20), nullable=True, comment='颜色')
    recruitment_type = Column(String(50), nullable=True, comment='招聘类型')
    city_code = Column(String(20), nullable=True, comment='城市代码')
    value = Column(String(100), nullable=True, comment='值')
    
    # 自关联关系
    parent = relationship('CityHot', remote_side=[code], backref='children',foreign_keys=[parent_id])  # 明确指定外键)
    
    def __repr__(self):
        return f"<City(id={self.id}, name='{self.name}', code={self.code}, level={self.level})>"
    
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
            'level': self.level
        }
