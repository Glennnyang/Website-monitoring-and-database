# STWDO Apartment Monitor

A small automation tool that watches the [Studierendenwerk Dortmund housing page](https://www.stwdo.de/wohnen/aktuelle-wohnangebote), tracks apartment listings and their prices over time in a local database, and notifies me by email (and desktop) the moment a new apartment appears or a price changes.

## Why I built it

Student housing in Dortmund goes fast, and the offers page changes without warning. Instead of refreshing it by hand several times a day, I automated the whole task: the script does the checking, remembers what it has already seen, and only pings me when something actually changes.

## What it does

- Loads the JavaScript-rendered listings page with a headless Chrome browser (Selenium)
- Parses each listing (address, title, size, price, link) with BeautifulSoup
- Stores everything in a **SQLite** database with two tables:
  - `apartments` — one row per unique apartment
  - `price_history` — a time-stamped snapshot of every price/size, linked to its apartment by foreign key
- Detects two kinds of events: **new apartments** and **price changes** (by comparing the two most recent snapshots)
- Sends an email (Gmail SMTP) and a desktop notification when either happens
- Runs continuously on a configurable interval

## Tech stack

Python · Selenium · BeautifulSoup · SQLite · SMTP (email automation)

## Setup

```bash
# 1. Install dependencies (a virtual environment is recommended)
pip install -r requirements.txt

# 2. Configure your email credentials
cp .env.example .env
#    then edit .env and add your Gmail address + app password

# 3. Run
python site_monitor.py
```

> **Note:** email uses a Gmail [app password](https://support.google.com/accounts/answer/185833), not your normal password. Credentials live only in `.env`, which is git-ignored and never committed.

## Possible next steps

- Summarise *what* changed in plain language with an LLM before sending the email
- Add filters (max rent, minimum size, preferred districts)
- Deploy it to run 24/7 on a small server instead of my laptop
