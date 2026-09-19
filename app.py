from flask import Flask, request, jsonify
import requests
import os
from dotenv import load_dotenv
load_dotenv(override=True)
from config.settings import Config
import models  # Import models to register them with SQLAlchemy
from extensions import db, migrate, login_manager
from admin.routes import admin_bp

def create_app():
    from flask import send_from_directory
    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)

    # Add client templates directory so admin blueprint can render client pages
    import os
    from jinja2 import FileSystemLoader, ChoiceLoader
    client_templates = os.path.join(os.path.dirname(__file__), 'client', 'templates')
    app.jinja_loader = ChoiceLoader([
        app.jinja_loader,
        FileSystemLoader(client_templates),
    ])

    root_static_dir = os.path.join(os.path.dirname(__file__), 'static')
    client_static_dir = os.path.join(os.path.dirname(__file__), 'client', 'static')

    @app.route('/static/<path:filename>', endpoint='static')
    def serve_static(filename):
        root_file = os.path.join(root_static_dir, filename)
        if os.path.exists(root_file) and os.path.isfile(root_file):
            return send_from_directory(root_static_dir, filename)
        return send_from_directory(client_static_dir, filename)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    login_manager.login_view = "client.login"

    @login_manager.user_loader
    def load_user(user_id):
        return None

    # Auto-seed default admin user if system_users table is empty
    with app.app_context():
        try:
            from services.auth_service import AuthService
            AuthService().seed_default_admin()
        except Exception as e:
            app.logger.warning(f"Could not seed default admin user: {e}")

    app.register_blueprint(admin_bp)
    return app



app = create_app()


@app.route('/api/setup-keys', methods=['GET'])
def get_netbird_setup_keys():
    try:
        customer_name = request.args.get('customer_name', '').strip()
        
        internal_key = os.environ.get('NETBIRD_API_TOKEN') or os.environ.get('INTERNAL_API_KEY', '')

        headers = {
            'accept': 'application/json',
            'Authorization': f'Bearer {internal_key}'
        }
        
        # جلب كل المفاتيح من NetBird
        response = requests.get(netbird_url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return jsonify(response.json()), response.status_code
            
        all_tokens = response.json()
        if isinstance(all_tokens, dict):
            all_tokens = [all_tokens]
        
        # الفلترة: إذا تم إرسال اسم عميل، سنبقي فقط على المفاتيح التي تحتوي على اسمه
        if customer_name:
            filtered_tokens = [
                token for token in all_tokens 
                if customer_name.lower() in token.get('name', '').lower()
            ]
        else:
            filtered_tokens = all_tokens
            
        return jsonify(filtered_tokens), 200

    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Failed to connect to NetBird API", "details": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=False)