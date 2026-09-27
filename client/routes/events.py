from flask import render_template, session

from client.blueprint import client_bp
from client.decorators import login_required


# Render only. The page loads its data from FastAPI in the browser
# (/api/v2/client/peers/<peer_id>/events/..., fastapi_app/routes/client/events.py),
# which also checks that the peer is the client's.
@client_bp.route('/peers/<peer_id>/events')
@login_required
def peer_events(peer_id):
    return render_template(
        'events.html',
        peer_id=peer_id,
        customer_name=session.get('client_customer_name'),
    )
