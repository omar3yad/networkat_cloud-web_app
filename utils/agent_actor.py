# Marks client-portal changes sent straight to a peer agent, so the peer's
# system logs record them as the customer ("You") and not as "controller".
CLIENT_ACTOR_HEADERS = {"X-Networkat-Actor": "client"}
