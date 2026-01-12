# Bandcamp Feed

A local Django web application that connects to your Gmail via IMAP, filters for Bandcamp "New Release" emails, parses them for metadata (album art, artist/label, release link), and displays them in a chronologically ordered feed.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![Django](https://img.shields.io/badge/Django-5.2-green)

<img width="3420" height="3960" alt="screencapture-localhost-8000-2026-01-12-11_40_47" src="https://github.com/user-attachments/assets/bf261519-1394-4a0c-b716-9d6e5fc68045" />

## Features

- **Gmail IMAP Integration**: Connects to Gmail to fetch Bandcamp notification emails from all folders
- **Email Parsing**: Extracts uploader (artist/label), release name, artwork URL, and Bandcamp links from email HTML using BeautifulSoup
- **SQLite Caching**: Stores parsed releases locally to avoid re-processing emails
- **Two-Phase Sync**: Prioritizes recent emails first, then processes historical backlog incrementally
- **Real-time Progress**: Server-Sent Events (SSE) provide live feedback during email sync
- **Search & Filter**: Filter releases by text search, date range, and sort order
- **Pagination**: Navigate through releases in pages of 25
- **Custom Domain Support**: Handles both `*.bandcamp.com` URLs and custom artist domains

## Tech Stack

- **Backend**: Django 5.2, Python 3.11+
- **Email Processing**: imap-tools (IMAP), BeautifulSoup4 (HTML parsing)
- **Frontend**: Django Templates, Tailwind CSS (CDN), HTMX
- **Database**: SQLite
- **Real-time Updates**: Server-Sent Events (SSE)

## Prerequisites

- Python 3.11+
- A Gmail account with Bandcamp notification emails
- Gmail App Password (see setup below)

## Installation

1. **Clone and navigate to the project:**
   ```bash
   cd bandcamp-feed
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables:**
   ```bash
   cp env.example .env
   ```
   
   Edit `.env` and add your Gmail credentials:
   ```
   EMAIL_USER=your-email@gmail.com
   EMAIL_PASSWORD=your-app-password
   EMAIL_SYNC_LIMIT=500
   ```

5. **Run database migrations:**
   ```bash
   python manage.py migrate
   ```

6. **Start the development server:**
   ```bash
   python manage.py runserver
   ```

7. **Open your browser:**
   Navigate to [http://127.0.0.1:8000](http://127.0.0.1:8000)

## Gmail App Password Setup

Gmail requires an App Password for IMAP access (your regular password won't work).

### Step 1: Enable 2-Factor Authentication
1. Go to your [Google Account](https://myaccount.google.com/)
2. Navigate to **Security** → **2-Step Verification**
3. Follow the prompts to enable 2FA if not already enabled

### Step 2: Create an App Password
1. Go to [App Passwords](https://myaccount.google.com/apppasswords)
2. Select **Mail** as the app
3. Select **Other** and enter "Bandcamp Feed"
4. Click **Generate**
5. Copy the 16-character password (without spaces)

### Step 3: Add to .env
```
EMAIL_USER=your-email@gmail.com
EMAIL_PASSWORD=abcd efgh ijkl mnop  # (remove spaces)
```

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `EMAIL_USER` | Gmail address | Required |
| `EMAIL_PASSWORD` | Gmail App Password | Required |
| `EMAIL_SYNC_LIMIT` | Max emails to process per sync | 500 |

## Usage

1. **View Feed**: The main page displays all cached Bandcamp releases in a grid
2. **Sync**: Click **Sync Emails** to fetch new releases from Gmail (progress shown in real-time)
3. **Search**: Type in the search box to filter by uploader or release name
4. **Filter by Date**: Use the dropdown to show releases from the last week, month, 3 months, or year
5. **Sort**: Order by newest, oldest, or uploader name (A-Z or Z-A)
6. **Browse**: Click any release card to open it on Bandcamp

<img width="3420" height="3960" alt="screencapture-localhost-8000-2026-01-12-11_42_24" src="https://github.com/user-attachments/assets/22755e72-10c7-49fa-81c4-43ac8e291e04" />

## Project Structure

```
bandcamp-feed/
├── bandcamp_feed/          # Django project settings
│   ├── settings.py         # Configuration with .env support
│   ├── urls.py             # Root URL routing
│   └── wsgi.py
├── feed/                   # Main application
│   ├── models.py           # Release model (email_id, uploader, release_name, etc.)
│   ├── services.py         # IMAP fetching & BeautifulSoup parsing logic
│   ├── views.py            # Views & SSE streaming endpoint
│   ├── urls.py             # App URL routing
│   └── templates/feed/     # HTML templates
│       ├── base.html       # Base template with Tailwind config
│       ├── index.html      # Main feed page
│       └── partials/       # HTMX partials
├── .env                    # Environment variables (not in git)
├── env.example             # Template for .env
├── requirements.txt        # Python dependencies
└── manage.py
```

## Data Model

The `Release` model stores:
- `email_id`: Unique identifier from the email
- `uploader`: Artist or label name
- `release_name`: Album/EP/track name
- `album_art_url`: URL to the cover artwork
- `bandcamp_url`: Link to the release on Bandcamp
- `received_at`: When the email was received
- `created_at`: When the record was added to the database

## Security Notes

- The `.env` file containing credentials is excluded from git via `.gitignore`
- Use Gmail App Passwords instead of your main account password
- This application is designed for local/personal use only
