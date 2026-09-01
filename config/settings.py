# /opt/networkat_sdwan/core/web_app/config/settings.py
import os
from dotenv import load_dotenv
load_dotenv()
class Config:
    """
    Base Application Configuration
    """
    SECRET_KEY = os.getenv("SECRET_KEY")
    RECAPTCHA_SITE_KEY = os.getenv("RECAPTCHA_SITE_KEY")
    RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY")
    MAIL_SERVER = os.getenv("MAIL_SERVER", "premium155.web-hosting.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "no_reply@networkat.net")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "bePositive\"2006\"")
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "True") == "True"
    SQLALCHEMY_DATABASE_URI = (
        f"postgresql+psycopg2://"
        f"{os.getenv('DB_USER')}:"
        f"{os.getenv('DB_PASSWORD')}@"
        f"{os.getenv('DB_HOST')}:"
        f"{os.getenv('DB_PORT', 5432)}/"
        f"{os.getenv('DB_NAME')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_size": 10,
        "max_overflow": 20,
        "echo": False
    }