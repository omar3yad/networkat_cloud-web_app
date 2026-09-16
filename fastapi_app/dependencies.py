import os
from dotenv import load_dotenv

load_dotenv(override=True)

from fastapi import Security, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi_app.database import SessionLocal

API_SECRET_KEY = os.getenv("INTERNAL_API_KEY")

security_scheme = HTTPBearer()

def verify_api_key(credentials: HTTPAuthorizationCredentials = Security(security_scheme)):
    if not API_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API Key security misconfiguration on server",
        )
        
    if credentials.credentials != API_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Authentication Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials

def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()