import json
import random
import textwrap
from datetime import timedelta
from typing import Optional

import google.generativeai as genai
import pyarabic.araby as araby
import requests
from bson import ObjectId
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from jose import ExpiredSignatureError, JWTError, jwt
from pydantic import ValidationError
from pymongo import MongoClient

from .config import settings
from .models import Schedule, User, UserCreate, WeekDays
from .security import (
    OAuth2PasswordBearerWithCookie,
    OAuth2PasswordOrRefreshRequestForm,
    Token,
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)

# Create a new client and connect to the server
client = MongoClient(settings.mongodb_url)
# Send a ping to confirm a successful connection
try:
    client.admin.command("ping")
    print("Pinged your deployment. You successfully connected to MongoDB!")
except Exception as e:
    print(e)
    exit("Error: Could not connect to the database. Exiting...")

db = client["tutor_platform"]
users_collection = db["users"]
schedules_collection = db["schedules"]


genai.configure(api_key=settings.google_api_key)

model = genai.GenerativeModel("gemini-pro")

oauth2_scheme = OAuth2PasswordBearerWithCookie(
    tokenUrl="/token", refreshUrl="/token"
)  # changed to use our implementation


app = FastAPI()


origins = ["http://localhost:3000"]  # Add your Next.js frontend URL here


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def authenticate_user(username: str, password: str) -> Optional[dict]:
    try:
        user = users_collection.find_one({"username": username})
    except HTTPException:
        return None
    if not user:
        return None
    if not user["password"]:
        raise HTTPException(status_code=400, detail="Employee not registered")
    if not verify_password(password, user["password"]):
        return None
    return user


async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = users_collection.find_one({"username": username})
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# CRUD operations for users
@app.post("/users/", response_model=User)
async def create_user(user: UserCreate):
    existing_username = users_collection.find_one({"username": user.username})
    if existing_username:
        raise HTTPException(
            status_code=400, detail="Username already registered. Please login."
        )
    existing_email = users_collection.find_one({"email": user.email})
    if existing_email:
        raise HTTPException(
            status_code=400, detail="Email already registered. Please login."
        )

    user_data = user.model_dump()
    user_data["password"] = hash_password(user_data["password"])
    inserted_user = users_collection.insert_one(user_data)
    user_id = str(inserted_user.inserted_id)

    # create am empty schedule for the user
    schedule_data = {
        "days": {
            "monday": [],
            "tuesday": [],
            "wednesday": [],
            "thursday": [],
            "friday": [],
            "saturday": [],
            "sunday": [],
        },
        "tutor_id": inserted_user.inserted_id,
    }

    inserted_schedule = schedules_collection.insert_one(schedule_data)
    schedule_id = str(inserted_schedule.inserted_id)

    return {**user_data, "id": user_id}


@app.get("/users/{user_id}", response_model=User)
async def get_user(user_id: str):
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if user:
        user["_id"] = str(user["_id"])
        user["id"] = user.pop("_id")
        user["schedule"] = list(schedules_collection.find({"tutor_id": user_id}))
        return user
    raise HTTPException(status_code=404, detail="User not found")


@app.get("/me", response_model=User)
async def read_users_me(current_user: dict = Depends(get_current_user)):
    return current_user


@app.post("/schedule", response_model=Schedule)
async def create_schedule(schedule: WeekDays, user: dict = Depends(get_current_user)):
    schedule_data = {}
    schedule_data["days"] = schedule.model_dump()
    schedule_data["tutor_id"] = user["_id"]
    inserted_schedule = schedules_collection.insert_one(schedule_data)
    schedule_id = str(inserted_schedule.inserted_id)
    # remove old schedule
    schedules_collection.delete_many(
        {"tutor_id": user["_id"], "_id": {"$ne": inserted_schedule.inserted_id}}
    )

    return {**schedule_data, "id": schedule_id}


@app.get("/schedule", response_model=Schedule)
async def get_schedule(user: dict = Depends(get_current_user)):
    schedule = schedules_collection.find_one({"tutor_id": user["_id"]})
    if schedule:
        schedule["_id"] = str(schedule["_id"])
        schedule["id"] = schedule.pop("_id")
        return schedule
    raise HTTPException(status_code=404, detail="Schedule not found")


@app.get("/generate_schedule", response_model=WeekDays)
def generate_schedule(description: str, user: dict = Depends(get_current_user)):

    # description = """I am available between 7pm and 9pm on weekdays, and between 10am and 2pm on weekends"""

    prompt = (
        textwrap.dedent(
            """\
    Please return JSON the a weekly schedule from this decription using the following schema:

    {"day_name": list[TIMESLOT]}

    TIMESLOT = {start_time": str, "end_time": str}

    All fields are required.

    Important: Only return a single piece of valid JSON text.
    Important: Friday and Saturday are the only weekend days.
    Important: Sunday is a weekday.
    Important: The start_time and end_time are in 24-hour format.

    Here is the description to use for the schedule:

    """
        )
        + description
    )

    max_retries = 5
    retries = 0

    while retries < max_retries:
        response = model.generate_content(prompt)

        json_text = response.text.strip("`\r\n ").removeprefix("json")

        try:
            json_data = json.loads(json_text)
            data = {
                "sunday": [],
                "monday": [],
                "tuesday": [],
                "wednesday": [],
                "thursday": [],
                "friday": [],
                "saturday": [],
            }
            for key, value in json_data.items():
                data[key.lower()] = value

            try:
                weekdays = WeekDays(**data)
            except ValidationError as e:
                print("Validation Error:", e)
                retries += 1
                continue
            return weekdays
        except json.JSONDecodeError:
            print("Invalid JSON response!")

        retries += 1

    raise HTTPException(status_code=500, detail="Failed to generate schedule")


QURAN_API = "http://api.alquran.cloud/v1/ayah/{}/{}"


def get_ayah_clean(number: int):
    edition = "quran-simple-clean"
    url = QURAN_API.format(number, edition)
    response = requests.get(url)
    if response.status_code == 200:
        return {
            "text": response.json()["data"]["text"],
            "ayahNumber": response.json()["data"]["numberInSurah"],
            "surah": response.json()["data"]["surah"]["name"],
        }
    return None


def get_ayah_tashkeel(number: int):
    edition = "quran-unicode"
    url = QURAN_API.format(number, edition)
    response = requests.get(url)
    if response.status_code == 200:
        return {
            "text": response.json()["data"]["text"],
            "ayahNumber": response.json()["data"]["numberInSurah"],
            "surah": response.json()["data"]["surah"]["name"],
        }
    return None


@app.get("/ayah")
def get_ayah():
    random_ayah_no = random.randint(3, 6234)
    ayah_data = get_ayah_clean(random_ayah_no)
    ayah_data_tashkeel = get_ayah_tashkeel(random_ayah_no)
    if not ayah_data or not ayah_data_tashkeel:
        raise HTTPException(
            status_code=500, detail="Failed to fetch ayah, please try again later"
        )
    surah = ayah_data["surah"]
    ayah = ayah_data["text"]
    ayah_tashkeel = ayah_data_tashkeel["text"]
    word_index = random.randint(2, len(ayah.split(" ")) - 3)
    word = ayah.split(" ")[word_index]
    before_word = " ".join(ayah.split(" ")[:word_index])
    after_word = " ".join(ayah.split(" ")[word_index + 1 :])
    surrounding_ayat = f"{get_ayah_clean(random_ayah_no - 1)['text']} {get_ayah_clean(random_ayah_no + 1)['text']}"  # type: ignore
    # get three random words from the surrounding ayat
    surrounding_words = [
        w for w in surrounding_ayat.split(" ") if len(w) > 4 and w != word
    ]
    random_words = random.sample(surrounding_words, 2)
    choices = [word, *random_words]
    # shuffle the choices
    random.shuffle(choices)
    return {
        "surah": surah,
        "ayah_number": ayah_data["ayahNumber"],
        "ayah": ayah,
        "word": araby.normalize_alef(araby.strip_diacritics(word)),
        "before_word": before_word,
        "after_word": after_word,
        "choices": choices,
    }


@app.post("/token", response_model=Token)
def login_for_access_token(
    response: Response,
    request: Request,
    form_data: OAuth2PasswordOrRefreshRequestForm = Depends(),
):  # added response as a function parameter
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if form_data.grant_type == "refresh_token":
        try:
            refresh_token = request.cookies.get("refresh_token")
            if refresh_token is None:
                raise credentials_exception
            payload = jwt.decode(
                refresh_token, settings.secret_key, algorithms=[settings.algorithm]
            )
            username = payload.get("sub")

            if username is None:
                raise credentials_exception
            user = users_collection.find_one({"username": username})
            if user is None:
                raise credentials_exception
        except JWTError as e:
            print("JWT Decoding Error:", e)
            raise credentials_exception
    elif (
        form_data.grant_type == "password"
        and form_data.username is not None
        and form_data.password is not None
    ):
        user = authenticate_user(form_data.username, form_data.password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
            )
        refresh_token_expires = timedelta(days=settings.refresh_token_expire_days)
        refresh_token = create_refresh_token(
            {"sub": user["username"]}, refresh_token_expires
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect grant_type",
        )

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": user["username"]}, expires_delta=access_token_expires
    )

    # set cookie in response with access_token refresh_token and expires for them
    response.set_cookie(
        key="access_token",
        value=f"{access_token}",
        httponly=True,
        expires=settings.access_token_expire_minutes * 60,
    )  # set HttpOnly cookie in response
    response.set_cookie(
        key="refresh_token",
        value=f"{refresh_token}",
        httponly=True,
        expires=settings.refresh_token_expire_days * 24 * 60 * 60,
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": settings.access_token_expire_minutes * 60,
        "token_type": "bearer",
    }


@app.get("/token/validate", response_model=User)
def validate_token(
    current_user: dict = Depends(get_current_user),
):
    return current_user


@app.get("/token/validate/refresh")
def validate_refresh_token(request: Request):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Refresh token is not valid",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        refresh_token = request.cookies.get("refresh_token")
        if refresh_token is None:
            raise credentials_exception
        payload = jwt.decode(
            refresh_token, settings.secret_key, algorithms=[settings.algorithm]
        )
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
        user = users_collection.find_one({"username": username})
        if user is None:
            raise credentials_exception

        return {"message": "Refresh token is valid"}
    except JWTError as e:
        print("JWT Decoding Error:", e)
        raise credentials_exception


@app.post("/logout")
def logout(response: Response):
    response.delete_cookie(key="access_token")
    response.delete_cookie(key="refresh_token")
    return {"message": "Logged out"}


def main():
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
