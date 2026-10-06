from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta

from .. import models, database
from . import utils
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

class UserCreate(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class PasswordReset(BaseModel):
    email: str
    new_password: str

@router.post("/register", response_model=Token)
def register(user: UserCreate, db: Session = Depends(database.get_db)):
    clean_email = user.email.strip().lower()
    db_user = db.query(models.User).filter(models.User.email.ilike(clean_email)).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = utils.get_password_hash(user.password)
    new_user = models.User(email=clean_email, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    access_token = utils.create_access_token(
        data={"sub": new_user.email}, expires_delta=timedelta(minutes=utils.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(database.get_db)):
    clean_email = form_data.username.strip().lower()
    user = db.query(models.User).filter(models.User.email.ilike(clean_email)).first()
    if not user or not utils.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = utils.create_access_token(
        data={"sub": user.email}, expires_delta=timedelta(minutes=utils.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/reset-password", response_model=Token)
def reset_password(req: PasswordReset, db: Session = Depends(database.get_db)):
    clean_email = req.email.strip().lower()
    user = db.query(models.User).filter(models.User.email.ilike(clean_email)).first()
    if not user:
        raise HTTPException(status_code=404, detail="No account found with this email address")
    
    user.hashed_password = utils.get_password_hash(req.new_password)
    db.commit()
    
    access_token = utils.create_access_token(
        data={"sub": user.email}, expires_delta=timedelta(minutes=utils.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": access_token, "token_type": "bearer"}

class CurrentUser(BaseModel):
    id: int
    email: str


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(database.get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = utils.jwt.decode(token, utils.SECRET_KEY, algorithms=[utils.ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except utils.JWTError:
        raise credentials_exception
    
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        raise credentials_exception
    return user


@router.get("/me", response_model=CurrentUser)
def read_current_user(current_user: models.User = Depends(get_current_user)):
    """The signed-in platform account.

    This is the authoritative "meeting host / organizer" identity. It is
    deliberately separate from the Google integration email and from
    settings.BOT_EMAIL — the bot is an invited attendee, never the host.
    """
    return CurrentUser(id=current_user.id, email=current_user.email)
