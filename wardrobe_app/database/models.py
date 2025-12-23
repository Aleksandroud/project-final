from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime, time
import enum

# Создаем базовый класс для всех наших моделей (таблиц)
# Все наши таблицы будут наследоваться от этого Base
Base = declarative_base()

class Gender(enum.Enum):
    """
    Перечисление возможных значений пола.
    Храним как строки, но в базе это будет специальный тип ENUM.
    """
    MALE = "male"
    FEMALE = "female"

class User(Base):
    """
    Основная таблица пользователей.
    Хранит техническую информацию о пользователе из Telegram.
    """
    __tablename__ = "users"  # Название таблицы в базе данных

    id = Column(Integer, primary_key=True)

    telegram_id = Column(Integer, unique=True, nullable=False, index=True)

    username = Column(String(100))

    first_name = Column(String(100))

    created_at = Column(DateTime, default=datetime.utcnow())

    preferences = relationship("UserPreferences", back_populates="user", uselist=False)

class UserPreferences(Base):
    """
    Таблица с настройками и предпочтениями пользователя.
    Все данные из опросника хранятся здесь.
    """
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True)

    user_id = Column(Integer, ForeignKey("users.id"), unique=True)

    name = Column(String(100), nullable=False)

    gender = Column(Enum(Gender), nullable=False)

    city = Column(String(100), nullable=False)

    clothing_style = Column(Integer, nullable=False)

    wants_dispatch = Column(Boolean, default=False)

    # String(10) - строка типа "UTC+3", "UTC-5"
    # Хранится только если wants_dispatch=True
    timezone = Column(String(10))

    # dispatch_time - время рассылки в формате "08:30", "09:00"
    # String(5) - строка из 5 символов
    # Хранится только если wants_dispatch=True
    dispatch_time = Column(String(5))



    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="preferences")


class WeatherCache(Base):
    """Таблица для кэша погоды"""
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
    """Таблица для системной статистики"""
    __tablename__ = "system_stats"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    cache_size = Column(Integer)
    db_cache_size = Column(Integer)
    redis_connected = Column(Boolean)