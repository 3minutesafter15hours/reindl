import os
import json
import time
import requests
from playwright.sync_api import sync_playwright

DB_FILE = 'wrestlers_db.json'
LOGO_DIR = os.path.join('static', 'logos')
os.makedirs(LOGO_DIR, exist_ok=True)

def gather_all_logo_urls():
    """Reads your database layout and extracts a clean list of absolute target URLs."""
    if not os.path.exists(DB_FILE):
        print(f"Error: {DB_FILE} not found!")
        return {}

    with open(DB_FILE, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    promo_logos_source = raw_data.get("promotion_logos", raw_data)
    
    url_to_filename_map = {}
    for p_id, entries in promo_logos_source.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            url = entry.get("logo_url", "")
            if not url:
                continue
            
            # Standardize absolute HTTPS paths
            if url.startswith("//"): url = "https:" + url
            elif url.startswith("/"): url = "https://www.cagematch.net" + url
            elif url.startswith("http://"): url = url.replace("http://", "https://")
            
            filename = url.split('/')[-1]
            if filename:
                url_to_filename_map[url] = filename
                
    return url_to_filename_map

def run_secure_download():
    url_map = gather_all_logo_urls()
    if not url_map:
        print("No logo assets discovered in database file.")
        return

    print(f"Found {len(url_map)} promotion logos. Stealing session headers from Chrome...")

    # 1. Connect to your active Chrome instance to read session auth tokens
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            
            # Grab user agent and active cookies from the scraping browser
            playwright_cookies = context.cookies("https://www.cagematch.net")
            user_agent = context.pages[0].evaluate("navigator.userAgent") if context.pages else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            browser.close()
        except Exception as e:
            print(f"\nCould not read active port 9222 session details. Ensure Chrome debug mode is running.\nError: {e}")
            return

    # 2. Convert Playwright cookie structures into a standard Python session jar
    session = requests.Session()
    for cookie in playwright_cookies:
        session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'], path=cookie['path'])

    # Inject standard headers alongside the stolen browser user identity
    session.headers.update({
        'User-Agent': user_agent,
        'Referer': 'https://www.cagematch.net/',
        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
    })

    # 3. Stream files safely inside Python with zero browser-tab crashes
    success_count = 0
    for url, filename in url_map.items():
        local_path = os.path.join(LOGO_DIR, filename)
        
        if os.path.exists(local_path):
            continue

        try:
            print(f"Downloading: {filename}...")
            response = session.get(url, timeout=10, stream=True)
            
            if response.status_code == 200:
                with open(local_path, 'wb') as img_file:
                    for chunk in response.iter_content(chunk_size=8192):
                        img_file.write(chunk)
                success_count += 1
                time.sleep(0.2)  # Respectful padding interval
            else:
                print(f" -> Skipped {filename} (HTTP Status {response.status_code})")
        except Exception as e:
            print(f" -> Error downloading {filename}: {e}")

    print(f"\nSuccess! Added {success_count} new local promotion graphics to {LOGO_DIR}.")

if __name__ == "__main__":
    run_secure_download()