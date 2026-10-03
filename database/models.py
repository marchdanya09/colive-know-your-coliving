from sqlalchemy import Column, Integer, BigInteger, String, Boolean, Float, ForeignKey, DateTime, Date, Text
from sqlalchemy.orm import relationship
from datetime import datetime, date, timezone
from database.db import Base

def utc_now():
    return datetime.now(timezone.utc)

class Coliving(Base):
    __tablename__ = "colivings"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    address = Column(String(255), nullable=False)
    invite_code = Column(String(16), unique=True, index=True, nullable=False)
    is_join_locked = Column(Boolean, default=False)
    
    group_chat_id = Column(BigInteger, nullable=True)
    duty_topic_id = Column(Integer, nullable=True)
    complaints_topic_id = Column(Integer, nullable=True)
    lost_found_topic_id = Column(Integer, nullable=True)
    announcements_topic_id = Column(Integer, nullable=True)
    
    default_fine_amount = Column(Float, default=50.0)
    fine_distribution = Column(String(20), default="ROOM")  # "ROOM" or "INDIVIDUAL"
    treasury_balance = Column(Float, default=0.0)
    
    total_people = Column(Integer, default=16)
    total_rooms = Column(Integer, default=4)
    custom_duty_rules = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    rooms = relationship("Room", back_populates="coliving", cascade="all, delete-orphan", order_by="Room.rotation_order")
    users = relationship("User", back_populates="coliving")
    join_requests = relationship("JoinRequest", back_populates="coliving", cascade="all, delete-orphan")
    duty_cycles = relationship("DutyCycle", back_populates="coliving", cascade="all, delete-orphan")
    complaints = relationship("Complaint", back_populates="coliving", cascade="all, delete-orphan")
    fines = relationship("Fine", back_populates="coliving", cascade="all, delete-orphan")
    blacklist = relationship("Blacklist", back_populates="coliving", cascade="all, delete-orphan")


class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    coliving_id = Column(Integer, ForeignKey("colivings.id"), nullable=False)
    name = Column(String(100), nullable=False)
    capacity = Column(Integer, default=4)
    rotation_order = Column(Integer, default=1)
    custom_duties = Column(Text, nullable=True)

    coliving = relationship("Coliving", back_populates="rooms")
    users = relationship("User", back_populates="room")
    complaints = relationship("Complaint", back_populates="target_room")
    fines = relationship("Fine", back_populates="room")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)
    coliving_id = Column(Integer, ForeignKey("colivings.id"), nullable=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    full_name = Column(String(120), nullable=False)
    username = Column(String(100), nullable=True)
    role = Column(String(20), default="RESIDENT")  # "SUPER_ADMIN", "SOTNIK", "RESIDENT"
    room_role = Column(String(50), default="Мешканець")  # "Староста" or "Мешканець"
    room_duty = Column(String(50), default="Не призначено")  # "🍳 Кухня", "🗑 Сміття", "🧼 Санвузол", "🧹 Порядок"
    is_approved = Column(Boolean, default=False)
    unpaid_fines = Column(Float, default=0.0)
    created_at = Column(DateTime, default=utc_now)

    coliving = relationship("Coliving", back_populates="users")
    room = relationship("Room", back_populates="users")
    complaints_made = relationship("Complaint", back_populates="reporter")
    fines = relationship("Fine", back_populates="user")


class JoinRequest(Base):
    __tablename__ = "join_requests"

    id = Column(Integer, primary_key=True, index=True)
    coliving_id = Column(Integer, ForeignKey("colivings.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    telegram_id = Column(BigInteger, index=True, nullable=False)
    full_name = Column(String(120), nullable=False)
    username = Column(String(100), nullable=True)
    target_role = Column(String(20), default="RESIDENT")  # "RESIDENT" or "SOTNIK"
    status = Column(String(20), default="PENDING")  # "PENDING", "APPROVED", "REJECTED", "BLOCKED"
    created_at = Column(DateTime, default=utc_now)

    coliving = relationship("Coliving", back_populates="join_requests")
    room = relationship("Room")


class DutyCycle(Base):
    __tablename__ = "duty_cycles"

    id = Column(Integer, primary_key=True, index=True)
    coliving_id = Column(Integer, ForeignKey("colivings.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    start_date = Column(Date, default=date.today)
    end_date = Column(Date, nullable=False)
    is_current = Column(Boolean, default=True)

    coliving = relationship("Coliving", back_populates="duty_cycles")
    room = relationship("Room")


class Complaint(Base):
    __tablename__ = "complaints"

    id = Column(Integer, primary_key=True, index=True)
    coliving_id = Column(Integer, ForeignKey("colivings.id"), nullable=False)
    reporter_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    photo_file_id = Column(String(255), nullable=True)
    comment = Column(Text, nullable=True)
    status = Column(String(20), default="OPEN")  # "OPEN", "RESOLVED", "FINED"
    created_at = Column(DateTime, default=utc_now)

    coliving = relationship("Coliving", back_populates="complaints")
    reporter = relationship("User", back_populates="complaints_made")
    target_room = relationship("Room", back_populates="complaints")


class Fine(Base):
    __tablename__ = "fines"

    id = Column(Integer, primary_key=True, index=True)
    coliving_id = Column(Integer, ForeignKey("colivings.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id"), nullable=True)
    amount = Column(Float, nullable=False)
    reason = Column(String(255), nullable=False)
    is_paid = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utc_now)

    coliving = relationship("Coliving", back_populates="fines")
    room = relationship("Room", back_populates="fines")
    user = relationship("User", back_populates="fines")


class Blacklist(Base):
    __tablename__ = "blacklist"

    id = Column(Integer, primary_key=True, index=True)
    coliving_id = Column(Integer, ForeignKey("colivings.id"), nullable=False)
    telegram_id = Column(BigInteger, index=True, nullable=False)
    reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utc_now)

    coliving = relationship("Coliving", back_populates="blacklist")
