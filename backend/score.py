import re
import sys
import unicodedata
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlparse

import tldextract
from rapidfuzz import fuzz

from parse import Email, parse_eml

# brand keyword -> registered domains it legitimately sends from
BRANDS = {
    "paypal": {"paypal.com"},
    "microsoft": {"microsoft.com", "office.com", "outlook.com"},
    "apple": {"apple.com", "icloud.com"},
    "google": {"google.com", "gmail.com", "youtube.com"},
    "amazon": {"amazon.com", "amazon.co.nz", "amazon.com.au"},
    "netflix": {"netflix.com"},
    "mychart": {"mychart.com", "epic.com"},
    "medicare": {"medicare.gov", "cms.gov"},
    "nzpost": {"nzpost.co.nz"},
    "dhl": {"dhl.com", "dhl.co.nz"},
    "fedex": {"fedex.com"},
    "ups": {"ups.com"},
    "usps": {"usps.com"},
    "lowes": {"lowes.com"},
    "tractorsupply": {"tractorsupply.com"},
    "costco": {"costco.com"},
    "walmart": {"walmart.com"},
    "facebook": {"facebook.com", "facebookmail.com", "meta.com"},
    "instagram": {"instagram.com", "facebookmail.com"},
    "linkedin": {"linkedin.com"},
    "docusign": {"docusign.com", "docusign.net"},
    "dropbox": {"dropbox.com"},
    "norton": {"norton.com", "nortonlifelock.com"},
    "mcafee": {"mcafee.com"},
    "coinbase": {"coinbase.com"},
    "binance": {"binance.com"},
    "anz": {"anz.co.nz", "anz.com"},
    "asb": {"asb.co.nz"},
    "westpac": {"westpac.co.nz", "westpac.com.au"},
    "kiwibank": {"kiwibank.co.nz"},
    "ird": {"ird.govt.nz"},
    "nzta": {"nzta.govt.nz"},
}
# Legit infrastructure whose names happen to resemble a brand
LOOKALIKE_OK = {"amazonaws.com", "amazonses.com", "googleapis.com", "googleusercontent.com",
                "gstatic.com", "microsoftonline.com", "applemusic.com"}
# Click-tracking / email-service redirectors: link text != href is normal for these
TRACKERS = {
    "sendgrid.net", "list-manage.com", "mcsv.net", "klclick.com", "klclick1.com", "klclick2.com",
    "klclick3.com", "awstrack.me", "cmail19.com", "cmail20.com", "createsend1.com",
    "customeriomail.com", "c.gle", "custhelp.com", "hubspotlinks.com", "hs-sites.com",
    "sparkpostmail.com", "mandrillapp.com", "exacttarget.com", "rs6.net", "mailgun.org",
    "vialoops.com", "safelinks.protection.outlook.com", "mjt.lu", "sailthru.com",
    "braze.com", "iterable.com", "mailchi.mp",
}
# Free hosting that phishing kits use for landing pages
FREE_HOSTING = re.compile(
    r"(^|\.)(storage\.googleapis\.com|firebasestorage\.googleapis\.com|firebaseapp\.com|web\.app"
    r"|blob\.core\.windows\.net|r2\.dev|pages\.dev|workers\.dev|netlify\.app|vercel\.app"
    r"|weebly\.com|wixsite\.com|glitch\.me|000webhostapp\.com|ipfs\.[\w.]+|dweb\.link)$"
)
# Phrases common in scams but absent from normal marketing (checked against the inbox)
LURES = ["payment failed", "claim your", "you have won", "been chosen", "medicare",
         "action required", "storage is full", "storage 100%", "account suspended",
         "verify your account", "unusual sign-in", "final notice"]
DANGEROUS_EXT = {"exe", "scr", "js", "jse", "vbs", "vbe", "bat", "cmd", "com", "pif", "msi",
                 "hta", "jar", "iso", "img", "lnk", "html", "htm", "shtml", "svg", "xlsm",
                 "docm", "pptm"}
ARCHIVE_EXT = {"zip", "rar", "7z"}  # common and usually fine, but can hide the above

FLAG_AT = 40
DOMAIN_IN_TEXT = re.compile(r"\b((?:[a-z0-9-]+\.)+[a-z]{2,})\b", re.I)
EMAIL_IN_TEXT = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
MATH_ALNUM = re.compile(r"[\U0001D400-\U0001D7FF]")  # 𝖬𝗒𝖢𝗁𝖺𝗋𝗍-style fancy letters
COMMON_BIGRAMS = set((Path(__file__).parent / "english_bigrams.txt").read_text().split())


@dataclass
class Result:
    score: int = 0
    reasons: list[str] = field(default_factory=list)

    def add(self, points, reason):
        self.score += points
        self.reasons.append(f"+{points} {reason}")


def _host(value):
    if "://" in value:
        return (urlparse(value).hostname or "").lower()
    return value.rsplit("@", 1)[-1].lower()


def reg_domain(value):
    """'x@mail.paypal.com' or 'https://mail.paypal.com/a' -> 'paypal.com'"""
    ext = tldextract.extract(_host(value))
    return f"{ext.domain}.{ext.suffix}".lower() if ext.domain and ext.suffix else ""


COUNTRY_SUFFIXES = {"com", "net", "org", "nz", "co.nz", "org.nz", "net.nz", "com.au", "au",
                    "co.uk", "uk", "ca", "us", "io"}


def same_org(a, b):
    """seek.com and seek.co.nz belong to the same organisation; paypal.xyz does not."""
    if a == b:
        return True
    (la, _, sa), (lb, _, sb) = a.partition("."), b.partition(".")
    return bool(la) and la == lb and sa in COUNTRY_SUFFIXES and sb in COUNTRY_SUFFIXES


def auth_result(auth, name):
    m = re.search(rf"\b{name}=(\w+)", auth)
    return m.group(1).lower() if m else "none"


def dkim_pass_domains(auth):
    """Every domain with a passing DKIM signature (mail is often signed twice)."""
    return {reg_domain(m.group(1)) for m in
            re.finditer(r"dkim=pass\s+header\.[id]=@?([\w.-]+)", auth)}


def looks_random(label):
    """Machine-generated labels like 'ylwfrqnox' or 'pf0ux39x': several letter pairs that
    (almost) never occur in English, or letters and digits shuffled together."""
    label = label.lower()
    pairs = [p[i:i + 2] for p in re.findall(r"[a-z]+", label) for i in range(len(p) - 1)]
    rare = sum(p not in COMMON_BIGRAMS for p in pairs)
    switches = len(re.findall(r"(?<=[a-z])\d|(?<=\d)[a-z]", label))
    return rare >= 3 or switches >= 3


def lookalike_brand(dom):
    if dom in LOOKALIKE_OK:
        return None
    label = dom.split(".")[0]
    for brand, domains in BRANDS.items():
        if dom in domains or label == brand or len(brand) < 5:
            continue
        if fuzz.ratio(label, brand) >= 80:
            return brand
    return None


def claimed_brand(display_name):
    """Brand named in the display name: whole word for short brands ('UPS' but not
    'groups'), substring for longer ones ('Lowe's-Rewards', 'TractorSupply Co')."""
    words = re.findall(r"[a-z0-9]+", display_name.lower().replace("'", "").replace("’", ""))
    joined = "".join(words)
    for brand in BRANDS:
        if brand in words or (len(brand) >= 5 and brand in joined):
            return brand
    return None


def score(e: Email) -> Result:
    r = Result()
    from_dom = reg_domain(e.from_addr)
    from_host = _host(e.from_addr)
    name = unicodedata.normalize("NFKC", e.from_name)

    # --- authentication (only Gmail's own header; drafts/self-sent mail have none) ---
    if e.auth_results:
        spf, dmarc = auth_result(e.auth_results, "spf"), auth_result(e.auth_results, "dmarc")
        if dmarc == "fail":
            r.add(30, "DMARC failed")
        if spf in ("fail", "softfail"):
            r.add(15, f"SPF {spf}")
        aligned = (dmarc == "pass"
                   or from_dom in dkim_pass_domains(e.auth_results)
                   or (spf == "pass" and reg_domain(e.return_path) == from_dom))
        if not aligned:
            r.add(20, f"no SPF/DKIM pass aligned with From domain {from_dom or from_host}")
    else:
        aligned = False

    # --- sender domain ---
    if not from_dom:
        r.add(40, f"sender domain {from_host} has no real top-level domain")
    elif looks_random(from_dom.split(".")[0]):
        r.add(20, f"sender domain looks machine-generated ({from_dom})")
    if brand := lookalike_brand(from_dom):
        r.add(30, f"sender domain {from_dom} resembles {brand}")
    rp_host = _host(e.return_path)
    if rp_host.count(".") >= 5 or len(rp_host) > 60:
        r.add(10, "unusually deep/long Return-Path domain")
    elif rp_host and not same_org(reg_domain(rp_host), from_dom) and any(
            looks_random(lab) for lab in rp_host.split(".")[:-1]):
        r.add(10, f"Return-Path domain looks machine-generated ({rp_host})")
    if "SMTPIN_ADDED" in e.message_id or not e.message_id:
        r.add(15, "sender didn't set a Message-ID (bulk-mailer tell)")
    elif ((mid_host := e.message_id.rstrip(">").rsplit("@", 1)[-1])
          and re.search(r"\.[a-z]{2,3}$", mid_host, re.I) and not reg_domain(mid_host)):
        # internal hosts like 'mta1.xt.local' are normal; 'abc.csi' is invented
        r.add(10, f"Message-ID uses fake domain {mid_host}")

    # --- reply-to (common and harmless on authenticated bulk mail) ---
    if e.reply_to and not same_org(reg_domain(e.reply_to), from_dom):
        r.add(5 if aligned else 20,
              f"Reply-To goes to {reg_domain(e.reply_to)}, From is {from_dom}")

    # --- display name ---
    if MATH_ALNUM.search(e.from_name) or (name != e.from_name and name.isascii()):
        r.add(25, f"display name uses lookalike Unicode ({e.from_name!r} -> {name!r})")
    if (brand := claimed_brand(name)) and not any(
            same_org(from_dom, d) for d in BRANDS[brand]):
        r.add(30, f"display name claims '{brand}' but sent from {from_dom or from_host}")
    if (m := EMAIL_IN_TEXT.search(name)) and m.group(0).lower() != e.from_addr:
        r.add(25, f"display name contains a different address ({m.group(0)})")

    # --- recipient: scams address you by your username and BCC you ---
    me = e.delivered_to
    user = me.split("@")[0]
    if user and e.from_addr != me and (user in name.lower() or user in e.subject.lower()):
        r.add(25, f"uses your email username '{user}' as your name")
    if me and e.to_addrs and me not in e.to_addrs and user.replace(".", "") not in {
            a.split("@")[0].replace(".", "") for a in e.to_addrs}:
        r.add(10, f"you aren't in To/Cc (addressed to {e.to_addrs[0]})")

    # --- subject and content ---
    if re.match(r"\s*(re|fwd?)\s*:", e.subject, re.I) and not e.is_reply:
        r.add(15, "subject says Re:/Fwd: but it isn't a reply")
    if MATH_ALNUM.search(e.subject + e.text):
        r.add(15, "uses fancy Unicode letters to dodge filters")
    blob = f"{e.subject} {e.text}".lower()
    if lures := [p for p in LURES if p in blob]:
        r.add(min(10 * len(lures), 20), f"scam phrasing: {', '.join(lures[:3])}")

    # --- links ---
    for link in e.links:
        href_dom = reg_domain(link.href)
        if not href_dom or same_org(href_dom, from_dom) or href_dom in TRACKERS:
            continue
        m = DOMAIN_IN_TEXT.search(link.text)
        if m and (text_dom := reg_domain(m.group(1))) and not same_org(text_dom, href_dom):
            r.add(25, f"link text shows {text_dom} but goes to {href_dom}")
            break
    for link in e.links:
        if brand := lookalike_brand(reg_domain(link.href)):
            r.add(30, f"link domain {reg_domain(link.href)} resembles {brand}")
            break
    hosts = {(urlparse(l.href).hostname or "").lower() for l in e.links if "://" in l.href}
    if hosted := sorted(h for h in hosts if FREE_HOSTING.search(h)):
        r.add(25, f"links to free file hosting ({hosted[0]})")
    for h in hosts:
        try:
            ip_address(h.strip("[]"))
        except ValueError:
            continue
        r.add(25, f"link goes to a raw IP address ({h})")
        break
    if any("@" in (urlparse(l.href).netloc or "") for l in e.links if "://" in l.href):
        r.add(25, "link hides its real destination with user@host")

    # --- attachments ---
    for fname in e.attachments:
        parts = fname.lower().rsplit(".", 2)
        if len(parts) > 1 and parts[-1] in DANGEROUS_EXT:
            double = len(parts) == 3 and len(parts[1]) <= 4  # invoice.pdf.exe
            r.add(40 if double else 25, f"risky attachment {fname}")
            break
        if len(parts) > 1 and parts[-1] in ARCHIVE_EXT:
            r.add(10, f"archive attachment {fname}")
            break

    return r


if __name__ == "__main__":
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "samples")
    results = [(score(e), e) for e in map(parse_eml, sorted(folder.glob("*.eml")))]
    for res, e in sorted(results, key=lambda x: -x[0].score):
        flag = "FLAG" if res.score >= FLAG_AT else "    "
        print(f"{flag} {res.score:>3}  {e.subject[:60]!r}")
        for reason in res.reasons:
            print(f"            {reason}")
