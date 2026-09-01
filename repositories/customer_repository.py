# /opt/networkat_sdwan/core/web_app/repositories/customer_repository.py
from extensions import db
from models.client import Client


class CustomerRepository:

    @staticmethod
    def get_all_desc():
        return Client.query.order_by(Client.user_id.desc()).all()

    @staticmethod
    def get_by_id(customer_id):
        return Client.query.get(customer_id)

    @staticmethod
    def create(name):
        # للتوافق المؤقت فقط
        client = Client(client_name=name)
        db.session.add(client)
        db.session.flush()
        return client

    @staticmethod
    def delete(customer):
        db.session.delete(customer)
        db.session.commit()

    @staticmethod
    def count():
        return Client.query.count()

    @staticmethod
    def commit():
        db.session.commit()

    @staticmethod
    def rollback():
        db.session.rollback()