from flask import Blueprint, render_template, request, jsonify
from client.context_processors import inject_client_sidebar, inject_subscription_context

client_bp = Blueprint('client', __name__, template_folder='templates', static_folder='static')
client_bp.context_processor(inject_client_sidebar)
client_bp.context_processor(inject_subscription_context)


@client_bp.app_errorhandler(404)
def handle_404_error(e):
    if request.path.startswith('/api/') or request.accept_mimetypes.best == 'application/json':
        return jsonify({"error": "Resource not found", "status": 404}), 404
    return render_template('404.html'), 404


@client_bp.app_errorhandler(500)
def handle_500_error(e):
    if request.path.startswith('/api/') or request.accept_mimetypes.best == 'application/json':
        return jsonify({"error": "Internal server error", "status": 500}), 500
    return render_template('500.html'), 500
