import base64, os, pathlib
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

def get_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        pathlib.Path("token.json").write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds)

svc = get_service()
resp = svc.users().messages().list(userId="me", labelIds=["SPAM"], maxResults=50).execute()
out = pathlib.Path("samples"); out.mkdir(exist_ok=True)
for m in resp.get("messages", []):
    raw = svc.users().messages().get(userId="me", id=m["id"], format="raw").execute()["raw"]
    (out / f"{m['id']}.eml").write_bytes(base64.urlsafe_b64decode(raw))