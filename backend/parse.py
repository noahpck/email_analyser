import re
import sys
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from pathlib import Path

from bs4 import BeautifulSoup

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")


@dataclass
class Link:
    href: str
    text: str


@dataclass
class Email:
    msg_id: str
    subject: str
    from_name: str
    from_addr: str
    reply_to: str
    return_path: str
    auth_results: str
    date: str
    delivered_to: str = ""  # the mailbox owner, added by Gmail
    to_addrs: list[str] = field(default_factory=list)  # To + Cc
    message_id: str = ""
    is_reply: bool = False  # has In-Reply-To / References
    text: str = ""  # visible body text, truncated
    links: list[Link] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)


def _date(msg):
    try:
        return parsedate_to_datetime(str(msg.get("Date"))).isoformat()
    except Exception:
        return ""

def _body(part):
    try:
        return part.get_content()
    except Exception:
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")


def _trusted_auth(msg):
    """Only the topmost Authentication-Results is written by Gmail; any lower ones
    came with the message and can be forged by the sender. Comments in (...) are
    dropped so nested results like arc=pass (... dmarc=pass) aren't misread."""
    headers = msg.get_all("Authentication-Results", [])
    if not headers or not str(headers[0]).strip().startswith("mx.google.com"):
        return ""
    return re.sub(r"\([^)]*\)", "", str(headers[0]))


def parse_eml(path):
    msg = BytesParser(policy=policy.default).parsebytes(Path(path).read_bytes())
    from_name, from_addr = parseaddr(str(msg.get("From", "")))
    links, attachments, text = [], [], []

    for part in msg.walk():
        if part.is_multipart():
            continue
        if part.get_content_disposition() == "attachment":
            attachments.append(part.get_filename() or "(unnamed)")
            continue
        ctype = part.get_content_type()
        if ctype == "text/html":
            soup = BeautifulSoup(_body(part), "html.parser")
            for a in soup.find_all("a", href=True):
                links.append(Link(a["href"].strip(), a.get_text(" ", strip=True)))
            text.append(soup.get_text(" ", strip=True))
        elif ctype == "text/plain":
            body = _body(part)
            for url in URL_RE.findall(body):
                links.append(Link(url, url))
            text.append(body)

    return Email(
        msg_id=Path(path).stem,
        subject=str(msg.get("Subject", "")),
        from_name=from_name,
        from_addr=from_addr.lower(),
        reply_to=parseaddr(str(msg.get("Reply-To", "")))[1].lower(),
        return_path=parseaddr(str(msg.get("Return-Path", "")))[1].lower(),
        auth_results=_trusted_auth(msg),
        date=_date(msg),
        delivered_to=parseaddr(str(msg.get("Delivered-To", "")))[1].lower(),
        to_addrs=[a.lower() for _, a in getaddresses(
            [str(h) for h in msg.get_all("To", []) + msg.get_all("Cc", [])]) if a],
        message_id=str(msg.get("Message-ID", "")).strip(),
        is_reply=bool(msg.get("In-Reply-To") or msg.get("References")),
        text=" ".join(" ".join(text).split())[:5000],
        links=links,
        attachments=attachments,
    )


if __name__ == "__main__":
    for p in sorted(Path(sys.argv[1] if len(sys.argv) > 1 else "samples").glob("*.eml")):
        e = parse_eml(p)
        print(f"\n{e.subject!r}")
        print(f"  from:     {e.from_name} <{e.from_addr}>")
        print(f"  reply-to: {e.reply_to or '-'}   return-path: {e.return_path or '-'}")
        print(f"  auth:     {e.auth_results[:120]}")
        print(f"  links:    {len(e.links)}   attachments: {e.attachments or '-'}")