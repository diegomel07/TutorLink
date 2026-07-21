"""
Modelo de dominio (ORM) de TutorLink.

Refleja el Class Diagram y el ER Diagram del Workshop 2:
- User (base) <- Student / Tutor no se modelan como tablas separadas por
  herencia física; en su lugar se usa "Table per type" con perfiles 1:1
  (student_profiles / tutor_profiles) tal como se definió en el ER Diagram,
  ya que es la estrategia que se documentó en el apartado de la BD relacional.
"""
import enum
from datetime import datetime, date, time

from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Boolean, DateTime, Date, Time,
    Numeric, ForeignKey, Enum, UniqueConstraint, CheckConstraint, Table
)
from sqlalchemy.orm import relationship

from database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class RoleEnum(str, enum.Enum):
    STUDENT = "STUDENT"
    TUTOR = "TUTOR"
    ADMIN = "ADMIN"


class BookingStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    RESCHEDULED = "RESCHEDULED"


class DayOfWeek(str, enum.Enum):
    MONDAY = "MONDAY"
    TUESDAY = "TUESDAY"
    WEDNESDAY = "WEDNESDAY"
    THURSDAY = "THURSDAY"
    FRIDAY = "FRIDAY"
    SATURDAY = "SATURDAY"
    SUNDAY = "SUNDAY"


# ---------------------------------------------------------------------------
# Tabla de asociación many-to-many: tutor_subjects
# ---------------------------------------------------------------------------
tutor_subjects = Table(
    "tutor_subjects",
    Base.metadata,
    Column("tutor_profile_id", ForeignKey("tutor_profiles.id"), primary_key=True),
    Column("subject_id", ForeignKey("subjects.id"), primary_key=True),
)


# ---------------------------------------------------------------------------
# User (FR-01, CRC: User)
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(RoleEnum), nullable=False)
    full_name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True, nullable=False)

    student_profile = relationship(
        "StudentProfile", back_populates="user", uselist=False,
        cascade="all, delete-orphan"
    )
    tutor_profile = relationship(
        "TutorProfile", back_populates="user", uselist=False,
        cascade="all, delete-orphan"
    )

    bookings_as_student = relationship(
        "Booking", back_populates="student", foreign_keys="Booking.student_user_id"
    )
    bookings_as_tutor = relationship(
        "Booking", back_populates="tutor", foreign_keys="Booking.tutor_user_id"
    )

    sent_messages = relationship(
        "Message", back_populates="sender", foreign_keys="Message.sender_user_id"
    )
    received_messages = relationship(
        "Message", back_populates="receiver", foreign_keys="Message.receiver_user_id"
    )


# ---------------------------------------------------------------------------
# StudentProfile (FR-03)
# ---------------------------------------------------------------------------
class StudentProfile(Base):
    __tablename__ = "student_profiles"

    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), unique=True, nullable=False)
    learning_goals = Column(Text, nullable=True)
    preferred_schedule = Column(Text, nullable=True)  # JSON serializado como texto

    user = relationship("User", back_populates="student_profile")


# ---------------------------------------------------------------------------
# TutorProfile (FR-02)
# ---------------------------------------------------------------------------
class TutorProfile(Base):
    __tablename__ = "tutor_profiles"

    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), unique=True, nullable=False)
    bio = Column(Text, nullable=True)
    qualifications = Column(Text, nullable=True)
    hourly_rate = Column(Numeric(10, 2), nullable=False, default=0)
    average_rating = Column(Numeric(3, 2), nullable=False, default=0)

    user = relationship("User", back_populates="tutor_profile")
    subjects = relationship("Subject", secondary=tutor_subjects, back_populates="tutors")
    availabilities = relationship(
        "Availability", back_populates="tutor_profile", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Subject
# ---------------------------------------------------------------------------
class Subject(Base):
    __tablename__ = "subjects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), unique=True, nullable=False)

    tutors = relationship("TutorProfile", secondary=tutor_subjects, back_populates="subjects")


# ---------------------------------------------------------------------------
# Availability (CRC: Availability)
# ---------------------------------------------------------------------------
class Availability(Base):
    __tablename__ = "availabilities"
    __table_args__ = (
        CheckConstraint("end_time > start_time", name="ck_availability_time_order"),
    )

    id = Column(BigInteger, primary_key=True, index=True)
    tutor_profile_id = Column(BigInteger, ForeignKey("tutor_profiles.id"), nullable=False)
    day_of_week = Column(Enum(DayOfWeek), nullable=True)  # null si es specific_date
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    is_recurring = Column(Boolean, default=True, nullable=False)
    specific_date = Column(Date, nullable=True)
    is_available = Column(Boolean, default=True, nullable=False)

    tutor_profile = relationship("TutorProfile", back_populates="availabilities")


# ---------------------------------------------------------------------------
# Booking (CRC: Booking, FR-05, FR-06)
# ---------------------------------------------------------------------------
class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("end_time > start_time", name="ck_booking_time_order"),
    )

    id = Column(BigInteger, primary_key=True, index=True)
    student_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    tutor_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=True)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    status = Column(Enum(BookingStatus), default=BookingStatus.PENDING, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    student = relationship("User", back_populates="bookings_as_student", foreign_keys=[student_user_id])
    tutor = relationship("User", back_populates="bookings_as_tutor", foreign_keys=[tutor_user_id])
    subject = relationship("Subject")
    review = relationship("Review", back_populates="booking", uselist=False, cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="booking")


# ---------------------------------------------------------------------------
# Review (CRC: Review, FR-10)
# ---------------------------------------------------------------------------
class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_review_rating_range"),
    )

    id = Column(BigInteger, primary_key=True, index=True)
    booking_id = Column(BigInteger, ForeignKey("bookings.id"), unique=True, nullable=False)
    student_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_flagged = Column(Boolean, default=False, nullable=False)

    booking = relationship("Booking", back_populates="review")


# ---------------------------------------------------------------------------
# Message (FR-08) — modelo listo, endpoints se implementarán en Release 2
# ---------------------------------------------------------------------------
class Message(Base):
    __tablename__ = "messages"

    id = Column(BigInteger, primary_key=True, index=True)
    sender_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    receiver_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    booking_id = Column(BigInteger, ForeignKey("bookings.id"), nullable=True)
    content = Column(Text, nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_read = Column(Boolean, default=False, nullable=False)

    sender = relationship("User", back_populates="sent_messages", foreign_keys=[sender_user_id])
    receiver = relationship("User", back_populates="received_messages", foreign_keys=[receiver_user_id])
    booking = relationship("Booking", back_populates="messages")