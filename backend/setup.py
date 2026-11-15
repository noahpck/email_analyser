import base64
import pathlib
import sys

from gmail import get_service

label = sys.argv[1] if len(sys.argv) > 1 else "SPAM"

svc = get_service()
resp = svc.users().messages().list(userId="me", labelIds=[label], maxResults=100).execute()
out = pathlib.Path("samples") / label.lower()
out.mkdir(parents=True, exist_ok=True)
for m in resp.get("messages", []):
    raw = svc.users().messages().get(userId="me", id=m["id"], format="raw").execute()["raw"]
    (out / f"{m['id']}.eml").write_bytes(base64.urlsafe_b64decode(raw))
