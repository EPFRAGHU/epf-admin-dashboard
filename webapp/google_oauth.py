"""
Google OAuth ("Sign in with Google") — shared Authlib client for both the login
and public signup flows.

Credentials come from GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET environment
variables, following the exact same never-hardcoded pattern as
CASHFREE_APP_ID/CASHFREE_SECRET_KEY in cashfree_client.py. Registering the app
in Google Cloud Console (creating the OAuth 2.0 client, adding authorized
redirect URIs for localhost + the production domain) is a manual step done
outside this codebase -- this module only consumes the resulting credentials.
"""

import os
from authlib.integrations.starlette_client import OAuth

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()


def is_configured() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


oauth = OAuth()
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)
