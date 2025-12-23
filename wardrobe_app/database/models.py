from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

Base = declarative_base()

class Gender(enum.Enum):
    MALE = "male"
    FEMALE = "female"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False, index=True)
    username = Column(String(100))
    first_name = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)

    preferences = relationship("UserPreferences", back_populates="user", uselist=False)

class UserPreferences(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    name = Column(String(100), nullable=False)
    gender = Column(Enum(Gender), nullable=False)
    city = Column(String(100), nullable=False)
    clothing_style = Column(Integer, nullable=False)
    wants_dispatch = Column(Boolean, default=False)
    timezone = Column(String(10))
    dispatch_time = Column(String(5))
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="preferences")

class WeatherCache(Base):
    __tablename__ = "weather_cache"

    city = Column(String(100), primary_key=True)
    temperature = Column(Float)
    feels_like = Column(Float)
    conditions = Column(String(100))
    humidity = Column(Integer)
    wind_speed = Column(Float)
    pressure = Column(Integer)
    icon = Column(String(10))
    sunrise = Column(Integer, nullable=True)
    sunset = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)

class SystemStats(Base):
    __tablename__ = "system_stats"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    cache_size = Column(Integer)
    db_cache_size = Column(Integer)
    redis_connected = Column(Boolean)