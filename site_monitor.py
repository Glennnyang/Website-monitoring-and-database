#!/usr/bin/env python3
"""
STWDO apartment monitor.

Watches the Studierendenwerk Dortmund (stwdo.de) housing page, stores every
listing in a local SQLite database, tracks price changes over time, and sends
an email + desktop notification whenever a new apartment appears or a price
changes.

Secrets (email credentials) are loaded from a .env file and are never stored
in the source code. Copy .env.example to .env and fill in your own values.
"""

import os
import re
import time
import sqlite3
import traceback
from datetime import datetime
from email.mime.text import MIMEText
import smtplib

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ============================== CONFIG ===================================

load_dotenv()  # reads EMAIL_* values from a local .env file

URL = "https://www.stwdo.de/wohnen/aktuelle-wohnangebote"
CHECK_INTERVAL_SECONDS = 60          # how often to re-check the page
HEADLESS = True                      # run Chrome without a visible window
DATABASE = "apartments.db"

# Notifications
ENABLE_EMAIL_NOTIFICATION = True
ENABLE_DESKTOP_NOTIFICATION = True

# Email credentials come from the environment (.env), never hard-coded.
EMAIL_FROM = os.environ.get("EMAIL_FROM")
EMAIL_TO = os.environ.get("EMAIL_TO")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# Disable email cleanly if credentials are missing, instead of crashing later.
if ENABLE_EMAIL_NOTIFICATION and not all([EMAIL_FROM, EMAIL_TO, EMAIL_APP_PASSWORD]):
    print("[!] Email credentials missing in .env - email notifications disabled.")
    ENABLE_EMAIL_NOTIFICATION = False


# ===========================================================================
# DATABASE
# ===========================================================================

def init_database() -> None:
    """Create the tables if they don't exist yet."""
    with sqlite3.connect(DATABASE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS apartments (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                address      TEXT UNIQUE,
                title        TEXT,
                link         TEXT,
                first_seen   TIMESTAMP,
                last_updated TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                apartment_id INTEGER,
                price        TEXT,
                size         TEXT,
                recorded_at  TIMESTAMP,
                FOREIGN KEY (apartment_id) REFERENCES apartments(id)
            )
        """)


def save_apartment(address: str, title: str, size: str, price: str, link: str) -> tuple[int, bool]:
    """Insert or update an apartment and append a price/size snapshot.

    Returns (apartment_id, is_new).
    """
    now = datetime.now()
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM apartments WHERE address = ?", (address,))
        row = cursor.fetchone()

        if row:
            apartment_id = row[0]
            is_new = False
            cursor.execute(
                "UPDATE apartments SET last_updated = ? WHERE id = ?",
                (now, apartment_id),
            )
        else:
            cursor.execute(
                """INSERT INTO apartments (address, title, link, first_seen, last_updated)
                   VALUES (?, ?, ?, ?, ?)""",
                (address, title, link, now, now),
            )
            apartment_id = cursor.lastrowid
            is_new = True

        cursor.execute(
            """INSERT INTO price_history (apartment_id, price, size, recorded_at)
               VALUES (?, ?, ?, ?)""",
            (apartment_id, price, size, now),
        )

    return apartment_id, is_new


def check_price_change(apartment_id: int) -> tuple[bool, str]:
    """Compare the two most recent prices for an apartment."""
    with sqlite3.connect(DATABASE) as conn:
        rows = conn.execute(
            """SELECT price FROM price_history
               WHERE apartment_id = ?
               ORDER BY recorded_at DESC
               LIMIT 2""",
            (apartment_id,),
        ).fetchall()

    if len(rows) < 2:
        return False, ""

    current, previous = rows[0][0], rows[1][0]
    if current != previous:
        return True, f"Preis: {previous} -> {current}"
    return False, ""


# ===========================================================================
# SCRAPING
# ===========================================================================

def get_page_content(url: str) -> str:
    """Load the page in Chrome (headless by default) and return its HTML."""
    options = webdriver.ChromeOptions()
    if HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    print("[*] Starting Chrome...")
    driver = webdriver.Chrome(options=options)
    try:
        print(f"[*] Loading: {url}")
        driver.get(url)
        WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.TAG_NAME, "body"))
        )
        time.sleep(5)  # allow client-side rendering to finish
        return driver.page_source
    finally:
        driver.quit()


def extract_apartments(html: str) -> list[dict]:
    """Parse apartment listings out of the stwdo.de HTML."""
    soup = BeautifulSoup(html, "html.parser")
    apartments = []

    items = soup.select("a[class*='group']")
    print(f"[*] Found {len(items)} candidate listings")

    for item in items:
        try:
            link = item.get("href", "")
            if not link or "/freie-zimmer/" not in link:
                continue

            address_elem = item.select_one("p.text-dobrand-700")
            address = address_elem.get_text(strip=True) if address_elem else "Unknown"

            title_elem = item.select_one("h4")
            title = title_elem.get_text(strip=True) if title_elem else "Unnamed"

            price, size = "N/A", "N/A"
            for span in item.find_all("span"):
                text = span.get_text(strip=True)
                if "\u20ac" in text:
                    price = text
                elif "m\u00b2" in text or "m2" in text:
                    size = text

            apartments.append(
                {"address": address, "title": title, "price": price, "size": size, "link": link}
            )
        except Exception as exc:  # keep going even if one listing is malformed
            print(f"[!] Could not parse a listing: {exc}")

    return apartments


# ===========================================================================
# NOTIFICATIONS
# ===========================================================================

def notify_desktop(title: str, message: str) -> None:
    try:
        from plyer import notification
        notification.notify(title=title, message=message, timeout=10)
    except Exception as exc:
        print(f"[!] Desktop notification failed: {exc}")


def notify_email(subject: str, body: str) -> None:
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
            server.send_message(msg)
        print("[i] Email sent")
    except Exception as exc:
        print(f"[!] Email failed: {exc}")


def send(title: str, body: str) -> None:
    if ENABLE_DESKTOP_NOTIFICATION:
        notify_desktop(title, body)
    if ENABLE_EMAIL_NOTIFICATION:
        notify_email(title, body)


# ===========================================================================
# MAIN LOOP
# ===========================================================================

def run_once(check_number: int) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'=' * 70}\n[{stamp}] Check #{check_number}\n{'=' * 70}")

    html = get_page_content(URL)
    apartments = extract_apartments(html)

    new_apartments, price_changes = [], []
    for apt in apartments:
        apt_id, is_new = save_apartment(
            apt["address"], apt["title"], apt["size"], apt["price"], apt["link"]
        )
        if is_new:
            new_apartments.append(apt)
            print(f"[NEW]   {apt['address']} - {apt['price']} ({apt['size']})")
        else:
            changed, msg = check_price_change(apt_id)
            if changed:
                price_changes.append((apt["address"], msg))
                print(f"[PRICE] {apt['address']}: {msg}")

    if new_apartments:
        body = "Neue Wohnungen:\n\n" + "".join(
            f"- {a['address']}\n  {a['title']}\n  {a['size']} | {a['price']}\n\n"
            for a in new_apartments[:5]
        )
        send(f"{len(new_apartments)} neue Wohnung(en)!", body)

    if price_changes:
        body = "Preisaenderungen:\n\n" + "".join(
            f"- {addr}\n  {msg}\n" for addr, msg in price_changes[:5]
        )
        send(f"{len(price_changes)} Preisaenderung(en)!", body)

    if not new_apartments and not price_changes:
        print("[ok] No new apartments or price changes.")


def main() -> None:
    print("=" * 70)
    print("STWDO APARTMENT MONITOR")
    print(f"URL:      {URL}")
    print(f"Interval: {CHECK_INTERVAL_SECONDS}s")
    print("=" * 70)

    init_database()

    check_number = 0
    try:
        while True:
            check_number += 1
            try:
                run_once(check_number)
            except Exception:
                print("[ERROR] Check failed:")
                traceback.print_exc()
            print(f"[*] Sleeping {CHECK_INTERVAL_SECONDS}s... (Ctrl+C to stop)")
            time.sleep(CHECK_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n[*] Stopped by user. Bye.")


if __name__ == "__main__":
    main()
