"""
TutorLink — API principal (FastAPI).

Cubre el MVP Release 1 del User Story Mapping:
Onboarding -> Profile Setup -> Discovery -> Scheduling -> Session Delivery (básico)
+ Ratings & Reviews (FR-10), necesario para cerrar el ciclo de Booking.

Mensajería (FR-08) y Admin Dashboard (FR-11) quedan como siguiente iteración,
los modelos ya están listos en models.py.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from database import Base, engine, get_db
import models
import schemas
from security import (
    hash_password, verify_password, create_access_token,
    get_current_user, require_role,
)

# Crea las tablas si no existen (para desarrollo; en producción usar Alembic)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="TutorLink API", version="1.0.0")

# CORS para que React (localhost:3000/5173) pueda consumir la API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================================================
# AUTH (FR-01)
# ===========================================================================
@app.post("/auth/register", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED, tags=["auth"])
def register(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="El correo ya está registrado")

    user = models.User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Crea automáticamente el perfil vacío correspondiente al rol
    if user.role == models.RoleEnum.STUDENT:
        db.add(models.StudentProfile(user_id=user.id))
    elif user.role == models.RoleEnum.TUTOR:
        db.add(models.TutorProfile(user_id=user.id, hourly_rate=0))
    db.commit()

    return user


@app.post("/auth/login", response_model=schemas.Token, tags=["auth"])
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos",
        )
    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return schemas.Token(access_token=token)


@app.get("/users/me", response_model=schemas.UserOut, tags=["auth"])
def read_current_user(current_user: models.User = Depends(get_current_user)):
    return current_user


# ===========================================================================
# SUBJECTS (catálogo, usado por perfiles de tutor y búsqueda)
# ===========================================================================
@app.get("/subjects", response_model=List[schemas.SubjectOut], tags=["subjects"])
def list_subjects(db: Session = Depends(get_db)):
    return db.query(models.Subject).order_by(models.Subject.name).all()


@app.post("/subjects", response_model=schemas.SubjectOut, tags=["subjects"])
def create_subject(
    payload: schemas.SubjectCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_role(models.RoleEnum.ADMIN)),
):
    if db.query(models.Subject).filter(models.Subject.name == payload.name).first():
        raise HTTPException(status_code=400, detail="La materia ya existe")
    subject = models.Subject(name=payload.name)
    db.add(subject)
    db.commit()
    db.refresh(subject)
    return subject


# ===========================================================================
# STUDENT PROFILE (FR-03)
# ===========================================================================
@app.get("/students/me/profile", response_model=schemas.StudentProfileOut, tags=["students"])
def get_my_student_profile(
    current_user: models.User = Depends(require_role(models.RoleEnum.STUDENT)),
    db: Session = Depends(get_db),
):
    profile = db.query(models.StudentProfile).filter(
        models.StudentProfile.user_id == current_user.id
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    return profile


@app.put("/students/me/profile", response_model=schemas.StudentProfileOut, tags=["students"])
def update_my_student_profile(
    payload: schemas.StudentProfileUpsert,
    current_user: models.User = Depends(require_role(models.RoleEnum.STUDENT)),
    db: Session = Depends(get_db),
):
    profile = db.query(models.StudentProfile).filter(
        models.StudentProfile.user_id == current_user.id
    ).first()
    if not profile:
        profile = models.StudentProfile(user_id=current_user.id)
        db.add(profile)

    profile.learning_goals = payload.learning_goals
    profile.preferred_schedule = payload.preferred_schedule
    db.commit()
    db.refresh(profile)
    return profile


# ===========================================================================
# TUTOR PROFILE (FR-02) + AVAILABILITY
# ===========================================================================
def _get_or_404_tutor_profile(db: Session, user_id: int) -> models.TutorProfile:
    profile = db.query(models.TutorProfile).options(
        joinedload(models.TutorProfile.subjects)
    ).filter(models.TutorProfile.user_id == user_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Perfil de tutor no encontrado")
    return profile


@app.get("/tutors/me/profile", response_model=schemas.TutorProfileOut, tags=["tutors"])
def get_my_tutor_profile(
    current_user: models.User = Depends(require_role(models.RoleEnum.TUTOR)),
    db: Session = Depends(get_db),
):
    return _get_or_404_tutor_profile(db, current_user.id)


@app.put("/tutors/me/profile", response_model=schemas.TutorProfileOut, tags=["tutors"])
def update_my_tutor_profile(
    payload: schemas.TutorProfileUpsert,
    current_user: models.User = Depends(require_role(models.RoleEnum.TUTOR)),
    db: Session = Depends(get_db),
):
    profile = db.query(models.TutorProfile).filter(
        models.TutorProfile.user_id == current_user.id
    ).first()
    if not profile:
        profile = models.TutorProfile(user_id=current_user.id)
        db.add(profile)
        db.flush()

    profile.bio = payload.bio
    profile.qualifications = payload.qualifications
    profile.hourly_rate = payload.hourly_rate

    if payload.subject_ids:
        subjects = db.query(models.Subject).filter(
            models.Subject.id.in_(payload.subject_ids)
        ).all()
        profile.subjects = subjects

    db.commit()
    db.refresh(profile)
    return _get_or_404_tutor_profile(db, current_user.id)


@app.post(
    "/tutors/me/availability",
    response_model=schemas.AvailabilityOut,
    status_code=status.HTTP_201_CREATED,
    tags=["tutors"],
)
def add_my_availability(
    payload: schemas.AvailabilityCreate,
    current_user: models.User = Depends(require_role(models.RoleEnum.TUTOR)),
    db: Session = Depends(get_db),
):
    profile = _get_or_404_tutor_profile(db, current_user.id)

    if payload.end_time <= payload.start_time:
        raise HTTPException(status_code=400, detail="end_time debe ser mayor que start_time")

    availability = models.Availability(
        tutor_profile_id=profile.id,
        day_of_week=payload.day_of_week,
        start_time=payload.start_time,
        end_time=payload.end_time,
        is_recurring=payload.is_recurring,
        specific_date=payload.specific_date,
    )
    db.add(availability)
    db.commit()
    db.refresh(availability)
    return availability


@app.get(
    "/tutors/{tutor_user_id}/availability",
    response_model=List[schemas.AvailabilityOut],
    tags=["tutors"],
)
def get_tutor_availability(tutor_user_id: int, db: Session = Depends(get_db)):
    profile = _get_or_404_tutor_profile(db, tutor_user_id)
    return db.query(models.Availability).filter(
        models.Availability.tutor_profile_id == profile.id,
        models.Availability.is_available == True,  # noqa: E712
    ).all()


# ===========================================================================
# DISCOVERY — Tutor Search (FR-04)
# ===========================================================================
@app.get("/tutors/search", response_model=List[schemas.TutorSearchResult], tags=["discovery"])
def search_tutors(
    subject: Optional[str] = None,
    min_rating: Optional[float] = None,
    day_of_week: Optional[models.DayOfWeek] = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.TutorProfile).options(
        joinedload(models.TutorProfile.subjects),
        joinedload(models.TutorProfile.user),
    )

    if subject:
        query = query.join(models.TutorProfile.subjects).filter(
            models.Subject.name.ilike(f"%{subject}%")
        )

    if min_rating is not None:
        query = query.filter(models.TutorProfile.average_rating >= min_rating)

    if day_of_week is not None:
        query = query.join(models.TutorProfile.availabilities).filter(
            models.Availability.day_of_week == day_of_week,
            models.Availability.is_available == True,  # noqa: E712
        )

    results = query.distinct().all()

    return [
        schemas.TutorSearchResult(
            user_id=t.user_id,
            full_name=t.user.full_name,
            bio=t.bio,
            hourly_rate=float(t.hourly_rate),
            average_rating=float(t.average_rating),
            subjects=t.subjects,
        )
        for t in results
    ]


# ===========================================================================
# SCHEDULING — Booking (FR-05, FR-06, US-T2)
# ===========================================================================
def _check_overlap(db: Session, tutor_user_id: int, start_time: datetime, end_time: datetime,
                    exclude_booking_id: Optional[int] = None) -> bool:
    """Verifica que no exista otra reserva activa que se traslape (Availability CRC)."""
    query = db.query(models.Booking).filter(
        models.Booking.tutor_user_id == tutor_user_id,
        models.Booking.status.in_([models.BookingStatus.PENDING, models.BookingStatus.CONFIRMED]),
        models.Booking.start_time < end_time,
        models.Booking.end_time > start_time,
    )
    if exclude_booking_id:
        query = query.filter(models.Booking.id != exclude_booking_id)
    return db.query(query.exists()).scalar()


@app.post(
    "/bookings",
    response_model=schemas.BookingOut,
    status_code=status.HTTP_201_CREATED,
    tags=["bookings"],
)
def create_booking(
    payload: schemas.BookingCreate,
    current_user: models.User = Depends(require_role(models.RoleEnum.STUDENT)),
    db: Session = Depends(get_db),
):
    if payload.end_time <= payload.start_time:
        raise HTTPException(status_code=400, detail="end_time debe ser mayor que start_time")

    tutor = db.query(models.User).filter(
        models.User.id == payload.tutor_user_id, models.User.role == models.RoleEnum.TUTOR
    ).first()
    if not tutor:
        raise HTTPException(status_code=404, detail="Tutor no encontrado")

    if _check_overlap(db, payload.tutor_user_id, payload.start_time, payload.end_time):
        raise HTTPException(status_code=409, detail="El horario ya no está disponible")

    booking = models.Booking(
        student_user_id=current_user.id,
        tutor_user_id=payload.tutor_user_id,
        subject_id=payload.subject_id,
        start_time=payload.start_time,
        end_time=payload.end_time,
        notes=payload.notes,
        status=models.BookingStatus.PENDING,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    # TODO (FR-07): disparar notificación al tutor (email/push)
    return booking


@app.get("/bookings/me", response_model=List[schemas.BookingOut], tags=["bookings"])
def list_my_bookings(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(models.Booking).filter(
        or_(
            models.Booking.student_user_id == current_user.id,
            models.Booking.tutor_user_id == current_user.id,
        )
    ).order_by(models.Booking.start_time.desc()).all()


def _get_booking_or_404(db: Session, booking_id: int) -> models.Booking:
    booking = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")
    return booking


@app.patch("/bookings/{booking_id}/accept", response_model=schemas.BookingOut, tags=["bookings"])
def accept_booking(
    booking_id: int,
    current_user: models.User = Depends(require_role(models.RoleEnum.TUTOR)),
    db: Session = Depends(get_db),
):
    booking = _get_booking_or_404(db, booking_id)
    if booking.tutor_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No puedes modificar esta reserva")
    if booking.status != models.BookingStatus.PENDING:
        raise HTTPException(status_code=400, detail="Solo se pueden aceptar reservas pendientes")

    booking.status = models.BookingStatus.CONFIRMED
    db.commit()
    db.refresh(booking)
    # TODO (FR-07): notificar al estudiante
    return booking


@app.patch("/bookings/{booking_id}/decline", response_model=schemas.BookingOut, tags=["bookings"])
def decline_booking(
    booking_id: int,
    current_user: models.User = Depends(require_role(models.RoleEnum.TUTOR)),
    db: Session = Depends(get_db),
):
    booking = _get_booking_or_404(db, booking_id)
    if booking.tutor_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No puedes modificar esta reserva")
    if booking.status != models.BookingStatus.PENDING:
        raise HTTPException(status_code=400, detail="Solo se pueden rechazar reservas pendientes")

    booking.status = models.BookingStatus.CANCELLED
    db.commit()
    db.refresh(booking)
    return booking


@app.patch("/bookings/{booking_id}/cancel", response_model=schemas.BookingOut, tags=["bookings"])
def cancel_booking(
    booking_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    booking = _get_booking_or_404(db, booking_id)
    if current_user.id not in (booking.student_user_id, booking.tutor_user_id):
        raise HTTPException(status_code=403, detail="No puedes modificar esta reserva")
    if booking.status not in (models.BookingStatus.PENDING, models.BookingStatus.CONFIRMED):
        raise HTTPException(status_code=400, detail="Esta reserva ya no se puede cancelar")

    booking.status = models.BookingStatus.CANCELLED
    db.commit()
    db.refresh(booking)
    return booking


@app.patch("/bookings/{booking_id}/reschedule", response_model=schemas.BookingOut, tags=["bookings"])
def reschedule_booking(
    booking_id: int,
    payload: schemas.BookingReschedule,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    booking = _get_booking_or_404(db, booking_id)
    if current_user.id not in (booking.student_user_id, booking.tutor_user_id):
        raise HTTPException(status_code=403, detail="No puedes modificar esta reserva")
    if payload.end_time <= payload.start_time:
        raise HTTPException(status_code=400, detail="end_time debe ser mayor que start_time")
    if _check_overlap(db, booking.tutor_user_id, payload.start_time, payload.end_time, exclude_booking_id=booking.id):
        raise HTTPException(status_code=409, detail="El nuevo horario no está disponible")

    booking.start_time = payload.start_time
    booking.end_time = payload.end_time
    booking.status = models.BookingStatus.RESCHEDULED
    db.commit()
    db.refresh(booking)
    return booking


@app.patch("/bookings/{booking_id}/complete", response_model=schemas.BookingOut, tags=["bookings"])
def complete_booking(
    booking_id: int,
    current_user: models.User = Depends(require_role(models.RoleEnum.TUTOR)),
    db: Session = Depends(get_db),
):
    booking = _get_booking_or_404(db, booking_id)
    if booking.tutor_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No puedes modificar esta reserva")
    if booking.status != models.BookingStatus.CONFIRMED:
        raise HTTPException(status_code=400, detail="Solo reservas confirmadas pueden completarse")

    booking.status = models.BookingStatus.COMPLETED
    db.commit()
    db.refresh(booking)
    return booking


# ===========================================================================
# REVIEWS (FR-10)
# ===========================================================================
@app.post(
    "/reviews",
    response_model=schemas.ReviewOut,
    status_code=status.HTTP_201_CREATED,
    tags=["reviews"],
)
def create_review(
    payload: schemas.ReviewCreate,
    current_user: models.User = Depends(require_role(models.RoleEnum.STUDENT)),
    db: Session = Depends(get_db),
):
    booking = _get_booking_or_404(db, payload.booking_id)
    if booking.student_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No puedes reseñar esta reserva")
    if booking.status != models.BookingStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Solo se pueden reseñar sesiones completadas")
    if booking.review is not None:
        raise HTTPException(status_code=400, detail="Esta reserva ya tiene una reseña")

    review = models.Review(
        booking_id=booking.id,
        student_user_id=current_user.id,
        rating=payload.rating,
        comment=payload.comment,
    )
    db.add(review)

    # Actualiza el promedio del tutor (responsabilidad del CRC: Review)
    tutor_profile = db.query(models.TutorProfile).filter(
        models.TutorProfile.user_id == booking.tutor_user_id
    ).first()
    if tutor_profile:
        all_ratings = [r.rating for r in db.query(models.Review).join(models.Booking).filter(
            models.Booking.tutor_user_id == booking.tutor_user_id
        ).all()] + [payload.rating]
        tutor_profile.average_rating = sum(all_ratings) / len(all_ratings)

    db.commit()
    db.refresh(review)
    return review


@app.get("/tutors/{tutor_user_id}/reviews", response_model=List[schemas.ReviewOut], tags=["reviews"])
def list_tutor_reviews(tutor_user_id: int, db: Session = Depends(get_db)):
    return db.query(models.Review).join(models.Booking).filter(
        models.Booking.tutor_user_id == tutor_user_id,
        models.Review.is_flagged == False,  # noqa: E712
    ).all()


@app.get("/health", tags=["system"])
def health_check():
    return {"status": "ok"}