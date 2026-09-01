# /opt/networkat_sdwan/core/web_app/repositories/client_repository.py
from datetime import datetime
from config.database import db
from models.client import Client
from werkzeug.security import generate_password_hash


class ClientRepository:

    def count(self):
        return Client.query.count()

    def get_all_desc(self):
        return Client.query.order_by(Client.created_at.desc()).all()

    def get_by_id(self, user_id):
        return Client.query.get(user_id)

    def get_by_username(self, username):
        return Client.query.filter_by(username=username).first()

    def get_by_email(self, email):
        return Client.query.filter_by(client_email=email).first()

    def create(
        self,
        username,
        raw_password,
        client_name,
        client_email,
        client_company_name=None,
        client_phone_number=None,
        client_country=None,
        subscription="free",
        active=True
    ):
        hashed_password = generate_password_hash(raw_password)
        client = Client(
            username=username,
            password_hashed=hashed_password,
            client_name=client_name,
            client_company_name=client_company_name,
            client_email=client_email,
            client_phone_number=client_phone_number,
            client_country=client_country,
            subscription=subscription,
            active=active
        )
        db.session.add(client)
        return client

    def update_password(self, client, raw_password):
        client.password_hashed = generate_password_hash(raw_password)

    def update_last_login(self, user_id):
        client = self.get_by_id(user_id)
        if client:
            client.last_login = datetime.utcnow()
            db.session.commit()

    def delete(self, client):
        db.session.delete(client)
        db.session.commit()

    def commit(self):
        db.session.commit()

    def rollback(self):
        db.session.rollback()

    def flush(self):
        db.session.flush()