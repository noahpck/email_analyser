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

## Demo

Demo mode runs the dashboard on 17 fictional emails in `demo/samples/`: 9 scams and 8 legitimate emails. It has no Gmail access, so you can share it publicly.

```bash
DEMO=1 python app.py               # http://localhost:8000
```

In demo mode:
- Gmail actions and writes are turned off.
- Safe/Scam labels are saved in the visitor's own browser.
- The database is a throwaway one, rebuilt at startup.

One scam, the gift-card request, deliberately isn't flagged. It's properly authenticated and has no links, which shows what rule-based checks can't catch.

To host it for free on [Render](https://render.com):
1. In the Render dashboard, choose **New → Blueprint** and pick this repo. `render.yaml` sets everything up: `DEMO=1`, gunicorn and the free plan.
2. Once it's deployed, put the `onrender.com` URL at the top of this README.

The free plan sleeps after 15 minutes without visitors, so the first visit after that takes about 30 seconds.

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
python app.py                      # dashboard at http://localhost:8000
```

The app syncs your INBOX and SPAM every 5 minutes in the background. Use **Sync now** in the dashboard to sync straight away. The first sync downloads the latest 100 emails from each label. After that, Gmail's history API means each sync only fetches new mail. Emails you trash or delete in Gmail itself disappear from the dashboard too.

Settings, as environment variables:
- `SYNC_MINUTES=10` changes the interval; `0` turns background sync off.
- `PORT=8010` serves the dashboard on a different port.

Other commands:

```bash
python backend/sync.py             # one sync without the dashboard
python backend/setup.py PROMOTIONS # download up to 100 emails from any label into samples/<label>/
python backend/analyse.py          # re-score every sample (run after changing the scorer)
```

In the dashboard, open an email to see its score breakdown, its SPF/DKIM/DMARC results, the message as plain text and every link with its real destination. Suspicious links are marked, for example when the text says one site but the link goes to another, or when it points to free file hosting. Links are shown as text and can't be clicked, so you can't open one by accident. From there:
- **Move to trash** moves it to Gmail Trash, where it can be recovered for 30 days.
- **Block sender & trash** also adds a Gmail filter that sends future mail from that address to Trash.
- The **History & blocked** tab lists everything you've trashed or blocked. **Restore** takes an email out of Gmail Trash, and for blocked emails it also removes the block. **Unblock** deletes a sender's block filter. This includes "Delete it" filters you created in Gmail yourself.
- **✓ Safe / ⚠ Scam** records your verdict. Use the label filter to find emails you haven't labelled yet.

To check the scorer's accuracy after changing it:

```bash
python backend/evaluate.py              # scams caught, false alarms, and the emails it gets wrong
python backend/evaluate.py --labelled   # only count emails you've labelled
python backend/evaluate.py --all        # list every email with its reasons
```

`evaluate.py` treats your labels as the truth. Emails you haven't labelled count as scam if they came from `samples/spam` and safe otherwise, so labelling Gmail's mistakes makes the numbers more accurate.

## Tests

```bash
python -m unittest -v
```

The tests run the scorer on small hand-made emails in `tests/fixtures/`, such as a lookalike PayPal phish, the real PayPal, a scam newsletter and a draft. They also cover the helper functions. GitHub Actions runs them on every push. When you change the scorer, add a fixture for the case you're fixing.

## Layout

| File | Purpose |
| --- | --- |
| `backend/gmail.py` | Gmail auth, trash and block-sender helpers |
| `backend/sync.py` | Incremental INBOX/SPAM sync using Gmail's history API |
| `backend/setup.py` | Downloads raw `.eml` files from any Gmail label |
| `backend/parse.py` | Extracts headers, links, body text and attachments |
| `backend/score.py` | Phishing heuristics; an email is flagged at a score of 40 or more |
| `backend/analyse.py` | Database helpers; run directly to re-score every sample |
| `backend/evaluate.py` | Measures the scorer against your Safe/Scam labels |
| `demo/samples/` | Fictional emails for the public demo |
| `render.yaml` | Render config for hosting the demo |
| `tests/` | Unit tests and `.eml` fixtures for the scorer |
| `app.py` | Flask server: JSON API, trash/block endpoint and background sync, bound to localhost |
| `static/` | Dashboard page (plain HTML, CSS and JS, no build step) |
