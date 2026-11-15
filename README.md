# Email Analyser

Pulls emails from Gmail, scores each one for phishing/scam signals, and shows the results in a local dark-mode dashboard where you can trash an email or block its sender.

The scorer (`backend/score.py`) checks things like:
- SPF, DKIM and DMARC results
- lookalike or machine-generated sender domains
- brand impersonation in the display name
- mismatched or free-hosted links
- scam phrasing
- risky attachments

Every flag comes with the reasons behind it.

## Setup

Requires Python 3.12+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project and enable the **Gmail API**.
2. Create an **OAuth client ID** (application type: Desktop app) and save the downloaded file as `credentials.json` in the project root.
3. If the OAuth consent screen is in Testing mode, add your Gmail address as a test user.

The first Gmail call opens a browser to sign in. Tick **every** permission checkbox: the app needs to read mail, move mail to Trash and create filters. The login is saved to `token.json`.

`credentials.json`, `token.json` and `analyser.db` are git-ignored. Don't commit them.

## Usage

Run everything from the project root:

```bash
python backend/setup.py SPAM       # download up to 100 emails from a label into samples/spam/
python backend/setup.py INBOX      # ...or samples/inbox/
python backend/analyse.py          # score all samples into analyser.db
python app.py                      # dashboard at http://localhost:8000
```

In the dashboard, open an email to see its score breakdown, then:
- **Move to trash** moves it to Gmail Trash, where it can be recovered for 30 days.
- **Block sender & trash** also adds a Gmail filter that sends future mail from that address to Trash. Undo it in Gmail under Settings → Filters and Blocked Addresses.

To check the scorer's accuracy after changing it:

```bash
python backend/evaluate.py --show spam    # flag rate per folder, with reasons
```

## Layout

| File | Purpose |
| --- | --- |
| `backend/gmail.py` | Gmail auth, trash and block-sender helpers |
| `backend/setup.py` | Downloads raw `.eml` files from a Gmail label |
| `backend/parse.py` | Extracts headers, links, body text and attachments |
| `backend/score.py` | Phishing heuristics; an email is flagged at a score of 40 or more |
| `backend/analyse.py` | Scores every sample and stores the results in SQLite |
| `backend/evaluate.py` | Reports how many emails in each folder get flagged |
| `app.py` | Flask server: JSON API plus trash/block endpoint, bound to localhost |
| `static/` | Dashboard page (plain HTML, CSS and JS, no build step) |
