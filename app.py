from flask import Flask, request, jsonify
import requests
import os
from dotenv import load_dotenv
load_dotenv()
from config.settings import Config
import models  # Import models to register them with SQLAlchemy
from extensions import db, migrate, login_manager
from admin.routes import admin_bp

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

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
        
        netbird_url = 'https://api.networkat.cloud/api/v2/netbird/setup-keys'
        internal_key = os.environ.get('NETBIRD_API_TOKEN', '57e443f0625abfa313425a020626b078899d4db7ff8d09d59c5f7ae4d0c6d874')

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
    app.run(debug=True)