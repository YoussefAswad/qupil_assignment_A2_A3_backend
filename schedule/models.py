from typing import Annotated, Optional

from pydantic import BaseModel, BeforeValidator, EmailStr, Field

PyObjectId = Annotated[str, BeforeValidator(str)]


class UserBase(BaseModel):
    username: str
    password: str
    name: str
    email: Optional[EmailStr] = None


class UserCreate(UserBase):
    pass


class User(UserBase):

    class Config:
        from_attributes = True


class TimeSlot(BaseModel):
    start_time: str = Field(min_length=5, max_length=5, pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(min_length=5, max_length=5, pattern=r"^\d{2}:\d{2}$")


class WeekDays(BaseModel):
    sunday: list[TimeSlot]
    monday: list[TimeSlot]
    tuesday: list[TimeSlot]
    wednesday: list[TimeSlot]
    thursday: list[TimeSlot]
    friday: list[TimeSlot]
    saturday: list[TimeSlot]


class Schedule(BaseModel):
    days: WeekDays
    tutor_id: Optional[PyObjectId]
    id: str

    class Config:
        from_attributes = True
