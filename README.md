# Email Analyser

Connects to your Gmail, scores every email in your inbox and spam folder for signs of phishing or scams, and shows the results in a dashboard on your own computer. From the dashboard you can move an email to Trash or block its sender.

Every score comes with the reasons behind it, for example:
- failed sender authentication (SPF, DKIM, DMARC)
- lookalike or machine-generated sender domains, like `paypa1.com`
- a display name claiming a brand the sender isn't, like "PayPal" from a random domain
- links whose text shows one site but go to another, or point to free file hosting
- common scam phrasing
- risky attachments, like `invoice.pdf.exe`

An email is flagged at a score of 40 or more.

**Privacy:** everything runs on your machine. Your emails are downloaded to `samples/`, the results go into a local database (`analyser.db`), and nothing is sent anywhere except to Google's Gmail API.

## 1. Install

You need Python 3.12 or newer.

```bash
git clone https://github.com/noahpck/email_analyser.git
cd email_analyser
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Create your Google credentials

Gmail only lets apps in through credentials you create yourself. This takes about 5 minutes, and it's free.

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and create a new project. Any name works.
2. Open **APIs & Services → Library**, search for **Gmail API** and click **Enable**.
3. Open **Google Auth Platform** (called **OAuth consent screen** in some accounts) and click **Get started**:
   - **App name:** anything, like "Email Analyser". **Support email:** your Gmail address.
   - **Audience:** choose **External**.
   - Finish the setup.
4. Under **Audience → Test users**, add your own Gmail address. Only test users can sign in.
5. Under **Clients**, click **Create client**, choose **Desktop app**, then download the JSON file.
6. Rename the file to `credentials.json` and put it in the `email_analyser` folder.

## 3. Run it

```bash
python app.py
```

Open **http://localhost:8000**.

The first time, a browser window opens to sign in to Google:
- You'll see **"Google hasn't verified this app"**. That's expected, because it's your own app. Click **Continue**.
- **Tick every permission checkbox.** The app needs to read your mail, move mail to Trash and create filters. If you leave one unticked, it will ask you to sign in again.

Your login is saved to `token.json`, so you won't be asked again for a while.

The first sync downloads the latest 100 emails from your inbox and spam folder, so give it a minute. After that it checks for new mail every 5 minutes, fetching only what's new.

## 4. Use the dashboard

- **Open any email** to see its score breakdown, its security checks, the message as plain text, and every link with where it really goes. Suspicious links are marked, and links can't be clicked, so you can't open a scam link by accident.
- **Move to trash** sends it to Gmail Trash. You can recover it for 30 days.
- **Block sender & trash** also adds a Gmail filter, so future mail from that address goes straight to Trash.
- **✓ Safe / ⚠ Scam** records your own verdict. Use these when the score is wrong; see "Checking accuracy" below.
- **Sync now** checks for new mail straight away.
- **History & blocked** tab:
  - **Restore** brings a trashed email back. For blocked emails, it also removes the block.
  - **Unblock** removes a sender's block filter.

Use the search box, the inbox/spam buttons, the label menu and **Flagged only** to filter the list.

Emails you trash or delete in Gmail itself also disappear from the dashboard.

## Settings

Set these as environment variables before `python app.py`, for example `SYNC_MINUTES=10 python app.py`.

| Variable | Default | What it does |
| --- | --- | --- |
| `SYNC_MINUTES` | `5` | How often to check for new mail. `0` turns automatic sync off. |
| `PORT` | `8000` | Port for the dashboard. |

## Troubleshooting

**"Google sign-in didn't grant: …"**
You left a permission unticked. Delete `token.json`, restart the app, and tick every box.

**You have to sign in again after a week**
Google expires logins every 7 days for apps in Testing mode. Delete `token.json` and restart to sign in again. It's a Google restriction on unverified personal apps.

**"Access blocked" or "not a test user"**
Add your Gmail address under **Google Auth Platform → Audience → Test users**.

**"Port 8000 is in use"**
Something else is using the port. Run `PORT=8010 python app.py` and open http://localhost:8010.

**Keep these files private**
`credentials.json`, `token.json`, `analyser.db` and `samples/` contain your credentials and your email. Don't commit or share them. The first three are already git-ignored; if you fork this repo, add `samples/` to `.gitignore` too. `token.json` gives access to your mailbox, so if it ever leaks, remove the app's access at [myaccount.google.com/permissions](https://myaccount.google.com/permissions).

## Checking accuracy

The scorer is rule-based, so it will sometimes be wrong. Label emails **Safe** or **Scam** in the dashboard, then run:

```bash
python backend/evaluate.py              # scams caught, false alarms, and the emails it gets wrong
python backend/evaluate.py --labelled   # only count emails you've labelled
```

For emails you haven't labelled, it assumes anything in your spam folder is a scam and everything else is safe.

## Other commands

```bash
python backend/sync.py             # sync once without starting the dashboard
python backend/setup.py PROMOTIONS # download up to 100 emails from any Gmail label
python backend/analyse.py          # re-score every downloaded email
python -m unittest -v              # run the tests
```

## How it's built

| File | Purpose |
| --- | --- |
| `app.py` | Local web server: dashboard, API and background sync. Only reachable from your own computer. |
| `static/` | The dashboard page (plain HTML, CSS and JavaScript) |
| `backend/gmail.py` | Google sign-in, trash, block and restore |
| `backend/sync.py` | Fetches new inbox and spam mail using Gmail's history API |
| `backend/parse.py` | Reads headers, links, body text and attachments from each email |
| `backend/score.py` | The phishing checks and their scores |
| `backend/analyse.py` | Database helpers |
| `backend/evaluate.py` | Measures the scorer against your Safe/Scam labels |
| `tests/` | Unit tests with hand-made example emails |
