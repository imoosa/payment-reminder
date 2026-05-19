# Maktronic Medical – Sundry Debtors App

A full-stack aging buckets dashboard for tracking and managing sundry debtor payments.

## Features
- 🔐 Login system (multi-user)
- 📊 Aging breakdown: <30d, 30-60d, 60-90d, 90-120d, 120-180d, >180d
- 🔍 Live search across all parties
- 📋 Party appears in ALL relevant buckets with both bucket amount and total pending
- 📧 Payment reminder system (email/WhatsApp)
- ⬆️ Excel file upload to refresh data
- 🔗 Google Sheets sync (public sheet URL)
- ⬇️ CSV export per bucket

## Quick Start

```bash
cd debtors_app
pip install -r requirements.txt
python app.py
```

Open http://localhost:5050

## Default Logins
| Username | Password    |
|----------|-------------|
| admin    | admin123    |
| manager  | manager123  |

> Change these in `app.py` → `USERS` dict using SHA-256 hashes.

## Google Sheets Integration

1. Open your Google Sheet
2. Go to **File → Share → Anyone with the link can view**
3. Copy the sheet URL
4. In the app click **Google Sheets** → paste the URL → **Sync Now**

The sheet must follow the same column format as the Excel file (Sundry Debtors sheet, data starting row 17).

## Excel Format Expected

The app reads the "Sundry Debtors" sheet with this column layout:
- Col 0: Party Name – Location
- Col 1: Contact Person
- Col 2: Phone
- Col 3: Total Pending (Debit)
- Col 5: < 30 days
- Col 7: 30-60 days
- Col 9: 60-90 days
- Col 11: 90-120 days
- Col 13: 120-180 days
- Col 15: > 180 days

## Production Deployment

For production use:
1. Change `app.secret_key` to a random 32-char string
2. Update `USERS` with strong hashed passwords
3. Run with gunicorn: `gunicorn -w 4 app:app`
4. Use nginx as a reverse proxy
5. Integrate with real email API (SMTP / SendGrid / WhatsApp Business)
