from sqlalchemy import text
from extensions import db
def check_database_connection():
    with db.engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return True