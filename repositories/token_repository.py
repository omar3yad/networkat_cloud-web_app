from extensions import db
from models.token import Token


class TokenRepository:

    @staticmethod
    def count_active():
        return Token.query.filter_by(is_active=True).count()


    @staticmethod
    def count_by_client(client_id):
        return Token.query.filter_by(client_id=client_id).count()

    @staticmethod
    def get_by_client(client_id):
        return Token.query.filter_by(client_id=client_id).all()

    @staticmethod
    def create(token_value, client_id, is_active=True):
        token = Token(token=token_value, client_id=client_id, is_active=is_active)
        db.session.add(token)
        return token

    @staticmethod
    def get_by_token_and_client(token_value, client_id):
        return Token.query.filter_by(token=token_value, client_id=client_id).first()

    @staticmethod
    def delete_by_client(client_id):
        Token.query.filter_by(client_id=client_id).delete()

    @staticmethod
    def get_active_by_token(token_value):
        return Token.query.filter_by(token=token_value, is_active=True).first()