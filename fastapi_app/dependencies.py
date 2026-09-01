import os
from fastapi import Security, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi_app.database import SessionLocal

# API_SECRET_KEY = os.getenv("INTERNAL_API_KEY")
API_SECRET_KEY = "57e443f0625abfa313425a020626b078899d4db7ff8d09d59c5f7ae4d0c6d874"

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