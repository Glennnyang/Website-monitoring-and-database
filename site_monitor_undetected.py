#!/usr/bin/env python3
"""
Site monitor with undetected-chromedriver (bypasses bot detection)
Tracks apartment price fluctuations over time
"""

import hashlib
import smtplib
import time
import traceback
import sqlite3
import re
from datetime import datetime
from email.mime.text import MIMEText

from bs4 import BeautifulSoup
import undetected_chromedriver as uc

# ============================== CONFIG ===================================

URL = "https://www.stwdo.de/wohnen/aktuelle-wohnangebote"
CHECK_INTERVAL_SECONDS = 10

# Email config
ENABLE_EMAIL_NOTIFICATION = True
EMAIL_FROM = "dzenyangglenn@gmail.com"
EMAIL_TO = "dzenyang4@gmail.com"
EMAIL_APP_PASSWORD = "ainf olpz zlqg dsrd"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

ENABLE_DESKTOP_NOTIFICATION = True

# Database
DATABASE = "apartments.db"
STATE_FILE = "site_monitor_state.txt"

# ===========================================================================
# DATABASE SETUP
# ===========================================================================

def init_database():
    """Create database tables if they don't exist."""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS apartments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT UNIQUE,
            title TEXT,
            link TEXT,
            first_seen TIMESTAMP,
            last_updated TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            apartment_id INTEGER,
            price TEXT,
            size TEXT,
            recorded_at TIMESTAMP,
            FOREIGN KEY (apartment_id) REFERENCES apartments(id)
        )
    """)
    
    conn.commit()
    conn.close()


def save_apartment(address: str, title: str, size: str, price: str, link: str) -> tuple[int, bool]:
    """Save apartment to database. Returns (apartment_id, is_new)."""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    now = datetime.now()
    is_new = False
    apartment_id = None
    
    cursor.execute("SELECT id FROM apartments WHERE address = ?", (address,))
    result = cursor.fetchone()
    
    if result:
        apartment_id = result[0]
        cursor.execute(
            "UPDATE apartments SET last_updated = ? WHERE id = ?",
            (now, apartment_id)
        )
    else:
        cursor.execute("""
            INSERT INTO apartments (address, title, link, first_seen, last_updated)
            VALUES (?, ?, ?, ?, ?)
        """, (address, title, link, now, now))
        apartment_id = cursor.lastrowid
        is_new = True
    
    # Save price/size history
    cursor.execute("""
        INSERT INTO price_history (apartment_id, price, size, recorded_at)
        VALUES (?, ?, ?, ?)
    """, (apartment_id, price, size, now))
    
    conn.commit()
    conn.close()
    
    return apartment_id, is_new


def check_price_change(apartment_id: int) -> tuple[bool, str]:
    """Check if price changed. Returns (changed, message)."""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT price FROM price_history 
        WHERE apartment_id = ? 
        ORDER BY recorded_at DESC 
        LIMIT 2
    """, (apartment_id,))
    
    results = cursor.fetchall()
    conn.close()
    
    if len(results) < 2:
        return False, ""
    
    current = results[0][0]
    previous = results[1][0]
    
    if current != previous:
        return True, f"Price: {previous} → {current}"
    
    return False, ""


def get_page_content(url: str) -> str:
    """Open page with undetected Chrome, read content, close."""
    print("[*] Opening undetected Chrome browser...")
    
    try:
        # Use undetected-chromedriver to bypass bot detection
        driver = uc.Chrome(headless=True)
        
        print(f"[*] Loading: {url}")
        driver.get(url)
        
        print("[*] Waiting for page to load (10 seconds)...")
        time.sleep(10)
        
        html = driver.page_source
        print("[*] Page loaded successfully")
        return html
        
    except Exception as e:
        print(f"[!] Error loading page: {e}")
        raise
    finally:
        try:
            driver.quit()
        except:
            pass
        print("[*] Browser closed")


def extract_apartments(html: str) -> list[dict]:
    """Extract apartment data from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    apartments = []
    
    # Find apartment links
    all_links = soup.find_all("a", href=lambda x: x and "/freie-zimmer/" in x)
    print(f"[*] Found {len(all_links)} apartment listings")
    
    for link_elem in all_links:
        try:
            link = link_elem.get("href", "")
            
            # Get address
            address_elem = link_elem.select_one("p.text-dobrand-700")
            address = address_elem.get_text(strip=True) if address_elem else "Unknown"
            
            if address == "Unknown":
                continue
            
            # Get title
            title_elem = link_elem.select_one("h4")
            title = title_elem.get_text(strip=True) if title_elem else "Unnamed"
            
            # Get price and size
            spans = link_elem.find_all("span")
            price = "N/A"
            size = "N/A"
            
            for span in spans:
                text = span.get_text(strip=True)
                if "€" in text and price == "N/A":
                    price = text
                elif ("m²" in text or "m2" in text) and size == "N/A":
                    size = text
            
            apartments.append({
                "address": address,
                "title": title,
                "price": price,
                "size": size,
                "link": link
            })
            
        except Exception as e:
            print(f"[!] Error parsing apartment: {e}")
            continue
    
    return apartments


def notify_desktop(title: str, message: str) -> None:
    try:
        from plyer import notification
        notification.notify(title=title, message=message, timeout=10)
        print(f"[i] Desktop notification: {title}")
    except Exception as e:
        print(f"[!] Desktop notification failed: {e}")


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
    except Exception as e:
        print(f"[!] Email failed: {e}")


def load_previous_hash() -> str | None:
    try:
        with open(STATE_FILE, "r") as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def save_hash(digest: str) -> None:
    with open(STATE_FILE, "w") as f:
        f.write(digest)


def main() -> None:
    print("=" * 80)
    print("APARTMENT MONITOR - stwdo.de (Undetected Mode)")
    print("=" * 80)
    print(f"URL: {URL}")
    print(f"Check interval: {CHECK_INTERVAL_SECONDS} seconds")
    print("=" * 80 + "\n")
    
    init_database()
    
    previous_hash = load_previous_hash()
    check_count = 0
    
    while True:
        check_count += 1
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        print(f"\n{'=' * 80}")
        print(f"[{timestamp}] Check #{check_count}")
        print("=" * 80)
        
        try:
            html = get_page_content(URL)
            apartments = extract_apartments(html)
            
            current_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
            
            new_apartments = []
            price_changes = []
            
            for apt in apartments:
                apt_id, is_new = save_apartment(
                    apt["address"],
                    apt["title"],
                    apt["size"],
                    apt["price"],
                    apt["link"]
                )
                
                if is_new:
                    new_apartments.append(apt)
                    print(f"[NEW] {apt['address']} - {apt['price']} ({apt['size']})")
                else:
                    changed, msg = check_price_change(apt_id)
                    if changed:
                        price_changes.append((apt["address"], msg))
                        print(f"[PRICE] {apt['address']}: {msg}")
            
            # Notifications
            if new_apartments:
                title = f"🏠 {len(new_apartments)} New Apartment(s)!"
                body = "New apartments found:\n\n"
                for apt in new_apartments[:3]:
                    body += f"• {apt['address']}\n  {apt['title']}\n  {apt['size']} | {apt['price']}\n\n"
                if len(new_apartments) > 3:
                    body += f"... and {len(new_apartments) - 3} more"
                
                if ENABLE_DESKTOP_NOTIFICATION:
                    notify_desktop(title, body)
                if ENABLE_EMAIL_NOTIFICATION:
                    notify_email(title, body)
            
            if price_changes:
                title = f"💰 {len(price_changes)} Price Change(s)!"
                body = "Price changes detected:\n\n"
                for addr, msg in price_changes[:3]:
                    body += f"• {addr}\n  {msg}\n"
                if len(price_changes) > 3:
                    body += f"\n... and {len(price_changes) - 3} more"
                
                if ENABLE_DESKTOP_NOTIFICATION:
                    notify_desktop(title, body)
                if ENABLE_EMAIL_NOTIFICATION:
                    notify_email(title, body)
            
            if not new_apartments and not price_changes:
                print("[✓] No new apartments or price changes")
            
            previous_hash = current_hash
            save_hash(current_hash)
            
        except Exception as e:
            print(f"[ERROR] Failed:")
            traceback.print_exc()
        
        print(f"\n[*] Sleeping {CHECK_INTERVAL_SECONDS} seconds...")
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
