from flask import Flask
from config.settings import Config
import models
from extensions import db, migrate, login_manager
from client.routes import client_bp


def create_client_app():
    app = Flask(__name__, template_folder='client/templates', static_folder='client/static')

    app.config.from_object(Config)

    db.init_app(app)

    migrate.init_app(app, db)

    login_manager.init_app(app)

    login_manager.login_view = "client.login"

    @login_manager.user_loader
    def load_user(user_id):
        return None

    app.register_blueprint(client_bp)
    return app


app = create_client_app()


if __name__ == "__main__":
    app.run(port=8097, debug=True)
