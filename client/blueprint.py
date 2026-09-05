from flask import Blueprint
from client.context_processors import inject_client_sidebar

client_bp = Blueprint('client', __name__, template_folder='templates', static_folder='static')
client_bp.context_processor(inject_client_sidebar)
