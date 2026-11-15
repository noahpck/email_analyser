import os
import pathlib

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# modify: read + move to trash. settings.basic: create filters (block sender).
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.settings.basic",
]


def get_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json")
        if not creds.has_scopes(SCOPES):  # old read-only token: re-consent
            creds = None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Google may return extra previously-granted scopes (e.g. gmail.readonly),
            # which oauthlib treats as an error by default. Allow it, then check below.
            os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
            missing = set(SCOPES) - set(creds.granted_scopes or [])
            if missing:
                raise RuntimeError(
                    "Google sign-in didn't grant: " + ", ".join(sorted(missing))
                    + ". Sign in again and tick every permission checkbox."
                )
        pathlib.Path("token.json").write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def trash_message(svc, msg_id):
    """Move a message to Trash (recoverable for 30 days)."""
    svc.users().messages().trash(userId="me", id=msg_id).execute()


def block_sender(svc, sender):
    """Create a filter that sends all future mail from `sender` straight to Trash."""
    body = {"criteria": {"from": sender}, "action": {"addLabelIds": ["TRASH"]}}
    try:
        svc.users().settings().filters().create(userId="me", body=body).execute()
    except HttpError as err:
        if "exists" not in str(err).lower():  # same filter already there is fine
            raise
