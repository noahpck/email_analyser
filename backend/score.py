import re
import sys
import unicodedata
from dataclasses import dataclass, field
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
    "google": {"google.com", "gmail.com"},
    "amazon": {"amazon.com", "amazon.co.nz"},
    "netflix": {"netflix.com"},
    "mychart": {"mychart.com", "epic.com"},
    "nzpost": {"nzpost.co.nz"},
}
FLAG_AT = 40
DOMAIN_IN_TEXT = re.compile(r"\b((?:[a-z0-9-]+\.)+[a-z]{2,})\b", re.I)
CONSONANT_RUN = re.compile(r"[bcdfghjklmnpqrstvwxyz]{5,}")


@dataclass
class Result:
    score: int = 0
    reasons: list[str] = field(default_factory=list)

    def add(self, points, reason):
        self.score += points
        self.reasons.append(f"+{points} {reason}")


def reg_domain(value):
    """'x@mail.paypal.com' or 'https://mail.paypal.com/a' -> 'paypal.com'"""
    if "://" in value:
        host = urlparse(value).hostname or ""
    else:
        host = value.rsplit("@", 1)[-1]
    ext = tldextract.extract(host)
    return f"{ext.domain}.{ext.suffix}".lower() if ext.domain and ext.suffix else ""


def auth_result(auth, name):
    m = re.search(rf"\b{name}=(\w+)", auth)
    return m.group(1).lower() if m else "none"


def lookalike_brand(dom):
    label = dom.split(".")[0]
    for brand, domains in BRANDS.items():
        if dom in domains or label == brand or len(brand) < 4:
            continue
        if fuzz.ratio(label, brand) >= 80:
            return brand
    return None


def score(e: Email) -> Result:
    r = Result()
    from_dom = reg_domain(e.from_addr)

    # authentication and alignment
    spf, dkim, dmarc = (auth_result(e.auth_results, k) for k in ("spf", "dkim", "dmarc"))
    if dmarc == "fail":
        r.add(30, "DMARC failed")
    if spf in ("fail", "softfail"):
        r.add(15, f"SPF {spf}")
    dkim_dom = re.search(r"header\.[id]=@?([\w.-]+)", e.auth_results)
    dkim_aligned = dkim == "pass" and dkim_dom and reg_domain(dkim_dom.group(1)) == from_dom
    spf_aligned = spf == "pass" and reg_domain(e.return_path) == from_dom
    if not (dkim_aligned or spf_aligned):
        r.add(20, f"no SPF/DKIM pass aligned with From domain {from_dom}")

    # reply-to
    if e.reply_to and reg_domain(e.reply_to) != from_dom:
        r.add(20, f"Reply-To goes to {reg_domain(e.reply_to)}, From is {from_dom}")

    # display name
    name = unicodedata.normalize("NFKC", e.from_name)
    if name != e.from_name and name.isascii():
        r.add(25, f"display name uses lookalike Unicode ({e.from_name!r} -> {name!r})")
    for brand, domains in BRANDS.items():
        if brand in name.lower().replace(" ", "") and from_dom not in domains:
            r.add(30, f"display name claims '{brand}' but sent from {from_dom}")
            break

    # sender domain shape
    if CONSONANT_RUN.search(from_dom.split(".")[0]):
        r.add(15, f"sender domain looks random ({from_dom})")
    rp_host = e.return_path.rsplit("@", 1)[-1]
    if rp_host.count(".") >= 5 or len(rp_host) > 60:
        r.add(10, "unusually deep/long Return-Path domain")
    if brand := lookalike_brand(from_dom):
        r.add(30, f"sender domain {from_dom} resembles {brand}")

    # links
    for link in e.links:
        href_dom = reg_domain(link.href)
        if not href_dom:
            continue
        m = DOMAIN_IN_TEXT.search(link.text)
        if m and (text_dom := reg_domain(m.group(1))) and text_dom != href_dom:
            r.add(25, f"link text shows {text_dom} but goes to {href_dom}")
            break
    for link in e.links:
        if brand := lookalike_brand(reg_domain(link.href)):
            r.add(30, f"link domain {reg_domain(link.href)} resembles {brand}")
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