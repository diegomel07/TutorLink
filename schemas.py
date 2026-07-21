"""
Esquemas Pydantic (request/response) para la API de TutorLink.
"""
from datetime import datetime, date, time
from typing import Optional, List

from pydantic import BaseModel, EmailStr, Field, ConfigDict

from models import RoleEnum, BookingStatus, DayOfWeek


# ---------------------------------------------------------------------------
# Auth / User
# ---------------------------------------------------------------------------
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str
    role: RoleEnum


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    role: RoleEnum
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Subject
# ---------------------------------------------------------------------------
class SubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class SubjectCreate(BaseModel):
    name: str


# ---------------------------------------------------------------------------
# Student profile (FR-03)
# ---------------------------------------------------------------------------
class StudentProfileUpsert(BaseModel):
    learning_goals: Optional[str] = None
    preferred_schedule: Optional[str] = None


class StudentProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    learning_goals: Optional[str]
    preferred_schedule: Optional[str]


# ---------------------------------------------------------------------------
# Tutor profile (FR-02)
# ---------------------------------------------------------------------------
class TutorProfileUpsert(BaseModel):
    bio: Optional[str] = None
    qualifications: Optional[str] = None
    hourly_rate: float = 0
    subject_ids: List[int] = []


class TutorProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    bio: Optional[str]
    qualifications: Optional[str]
    hourly_rate: float
    average_rating: float
    subjects: List[SubjectOut] = []


class TutorSearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    full_name: str
    bio: Optional[str]
    hourly_rate: float
    average_rating: float
    subjects: List[SubjectOut] = []


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------
class AvailabilityCreate(BaseModel):
    day_of_week: Optional[DayOfWeek] = None
    start_time: time
    end_time: time
    is_recurring: bool = True
    specific_date: Optional[date] = None


class AvailabilityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tutor_profile_id: int
    day_of_week: Optional[DayOfWeek]
    start_time: time
    end_time: time
    is_recurring: bool
    specific_date: Optional[date]
    is_available: bool


# ---------------------------------------------------------------------------
# Booking (FR-05, FR-06)
# ---------------------------------------------------------------------------
class BookingCreate(BaseModel):
    tutor_user_id: int
    subject_id: Optional[int] = None
    start_time: datetime
    end_time: datetime
    notes: Optional[str] = None


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    student_user_id: int
    tutor_user_id: int
    subject_id: Optional[int]
    start_time: datetime
    end_time: datetime
    status: BookingStatus
    notes: Optional[str]
    created_at: datetime


class BookingReschedule(BaseModel):
    start_time: datetime
    end_time: datetime


# ---------------------------------------------------------------------------
# Review (FR-10)
# ---------------------------------------------------------------------------
class ReviewCreate(BaseModel):
    booking_id: int
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = None


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    booking_id: int
    student_user_id: int
    rating: int
    comment: Optional[str]
    created_at: datetime
    is_flagged: bool