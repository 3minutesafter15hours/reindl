import json
import re
import time
import os
import shutil
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

TITLE_IDS = ["73", "72", "71", "2699", "726", "1836", "1420", "3797", "4922", "3796", "5889", "3800", "3802", "3798", "3801", "3799", "7408", "7963", "7325", "7326", "718", "1020", "1022", "1019", "1023", "3492", "1255", "3466", "4714", "1435", "3500", "1436", "3456", "756", "3462", "3465", "1448", "1447", "3894", "1062", "1063", "2346", "2381", "1032", "780", "135", "799", "4459", "800", "2746", "4484", "2745", "179", "46", "2842", "799", "800", "741", "4380", "4503", "739", "1903", "740", "3441", "2995", "4332", "7071", "2422", "2535", "221", "4382", "5177", "2327", "2224", "410"]
DB_FILE = 'wrestlers_db.json'

def parse_cagematch_date(date_text):
    try:
        clean_date = date_text.strip()
        if re.match(r'^\d{2}\.\d{2}\.\d{4}$', clean_date):
            dt = datetime.strptime(clean_date, "%d.%m.%Y")
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    return None

def parse_history_date(date_str):
    try:
        clean_str = date_str.strip().lower()
        if clean_str in ["today", "now", "present"]:
            return datetime.max
            
        parts = clean_str.split('.')
        if len(parts) == 3:
            day = "01" if "x" in parts[0] else parts[0]
            month = "01" if "x" in parts[1] else parts[1]
            year = parts[2]
            return datetime.strptime(f"{day}.{month}.{year}", "%d.%m.%Y")
    except Exception:
        pass
    return datetime(1970, 1, 1)

def parse_logo_date_bound(date_str, is_end=False):
    if not date_str:
        return "2050-12-31" if is_end else "1910-01-01"
        
    clean_str = date_str.strip().lower()
    if clean_str in ["today", "now", "present", ""]:
        return "2050-12-31"

    if re.match(r'^\d{2}\.\d{2}\.\d{4}$', clean_str):
        parts = clean_str.split('.')
        return f"{parts[2]}-{parts[1]}-{parts[0]}"

    if re.match(r'^\d{2}\.\d{4}$', clean_str):
        parts = clean_str.split('.')
        month = int(parts[0])
        year = int(parts[1])
        if is_end:
            if month == 12:
                month = 1
                year += 1
            else:
                month += 1
        return f"{year}-{month:02d}-01"

    if re.match(r'^\d{4}$', clean_str):
        if is_end:
            return f"{str(int(clean_str) + 1)}-01-01"
        return f"{clean_str}-01-01"

    return "2050-12-31" if is_end else "1910-01-01"

def extract_logo_timeline_from_text(text_val):
    text_val = text_val.strip()
    if not text_val or text_val == "()":
        return {"start": "1910-01-01", "end": "2050-12-31", "is_current": True}

    match_range = re.search(r'\(([^)]+)\s*-\s*([^)]+)\)', text_val)
    if match_range:
        start_raw = match_range.group(1).strip()
        end_raw = match_range.group(2).strip()
        return {
            "start": parse_logo_date_bound(start_raw, is_end=False),
            "end": parse_logo_date_bound(end_raw, is_end=True),
            "is_current": "today" in end_raw.lower() or end_raw == ""
        }

    match_single = re.search(r'\((\d{4})\)', text_val)
    if match_single:
        year_raw = match_single.group(1).strip()
        return {
            "start": parse_logo_date_bound(year_raw, is_end=False),
            "end": parse_logo_date_bound(year_raw, is_end=True),
            "is_current": False
        }

    return {"start": "1910-01-01", "end": "2050-12-31", "is_current": False}

def extract_rows_by_label(soup, label_text):
    try:
        tables = soup.find_all('div', class_='InformationBoxTable')
        for table in tables:
            rows = table.find_all('div', class_='InformationBoxRow')
            for row in rows:
                title_col = row.find('div', class_='InformationBoxTitle')
                content_col = row.find('div', class_='InformationBoxContents')
                
                if title_col and content_col:
                    current_title = title_col.get_text().strip().lower()
                    target_title = label_text.lower()
                    
                    if target_title == current_title or current_title.startswith(target_title):
                        raw_html = str(content_col)
                        clean_html = raw_html.replace("<br/>", "\n").replace("<br>", "\n")
                        sub_soup = BeautifulSoup(clean_html, 'html.parser')
                        lines = [line.strip() for line in sub_soup.get_text().split('\n')]
                        return content_col, lines, current_title
    except Exception as e:
        print(f"    ⚠️ Error isolating label context blocks for '{label_text}': {e}")
    return None, [], ""

def fetch_title_history_names(soup, title_id):
    history_map = []
    _, lines, _ = extract_rows_by_label(soup, "Names:")
    
    for line in lines:
        if not line: continue
        match = re.match(r'^(.+?)\s*\((?:since\s+([\d\.xX]+)|([\d\.xX]+)\s*-\s*([\d\.xX]+))\)', line)
        if match:
            name = match.group(1).strip()
            if match.group(2):
                start_dt = parse_history_date(match.group(2))
                end_dt = datetime.max
            else:
                start_dt = parse_history_date(match.group(3))
                end_dt = parse_history_date(match.group(4))
            
            history_map.append({
                "name": name, 
                "start": start_dt.strftime("%Y-%m-%d") if start_dt != datetime.min else "1910-01-01", 
                "end": end_dt.strftime("%Y-%m-%d") if end_dt != datetime.max else "2050-12-31"
            })
            
    if not history_map:
        h1_text = soup.find('h1')
        fallback_name = h1_text.get_text().strip() if h1_text else f"Title ID {title_id}"
        history_map.append({"name": fallback_name, "start": "1910-01-01", "end": "2050-12-31"})
            
    return history_map

def fetch_promotion_history(soup, title_id):
    promotion_map = []
    content_block, lines, _ = extract_rows_by_label(soup, "Promotion")
    
    if not content_block:
        return promotion_map
        
    all_links = content_block.find_all('a', href=True)
    extracted_ids = []
    for link in all_links:
        if "id=8&" in link['href']:  
            id_match = re.search(r'nr=(\d+)', link['href'])
            if id_match:
                extracted_ids.append(id_match.group(1))

    link_index = 0
    for line in lines:
        if not line: continue
        match = re.search(r'\((?:since\s+([\d\.xX]+)|([\d\.xX]+)\s*-\s*([\w\.xX]+))\)', line)
        if match and link_index < len(extracted_ids):
            if match.group(1):
                start_dt = parse_history_date(match.group(1))
                end_dt = datetime.max
            else:
                start_dt = parse_history_date(match.group(2))
                end_dt = parse_history_date(match.group(3))
            
            promotion_map.append({
                "promotion_id": extracted_ids[link_index],
                "start": start_dt.strftime("%Y-%m-%d") if start_dt != datetime.min else "1910-01-01",
                "end": end_dt.strftime("%Y-%m-%d") if end_dt != datetime.max else "2050-12-31"
            })
            link_index += 1
            
    if not promotion_map and extracted_ids:
        for pid in extracted_ids:
            promotion_map.append({
                "promotion_id": pid,
                "start": "1910-01-01",
                "end": "2050-12-31"
            })
            
    return promotion_map

def scrape_promotion_logos(page, promo_id):
    url = f"https://www.cagematch.net/?id=8&nr={promo_id}"
    print(f"🎨 Scrape Promotion Logo History for ID: {promo_id}...")
    timeline = []
    
    try:
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(0.3)
        soup = BeautifulSoup(page.content(), 'html.parser')
        
        content_block, _, _ = extract_rows_by_label(soup, "Logo")
        
        if content_block:
            raw_html = str(content_block)
            segments = re.split(r'<br\s*/?>|\n', raw_html)
            
            for seg in segments:
                seg_soup = BeautifulSoup(seg, 'html.parser')
                text_val = seg_soup.get_text().strip()
                img_tag = seg_soup.find('img')
                
                if img_tag and (text_val == "" or text_val.startswith("(")):
                    src = img_tag.get('src', '')
                    if src:
                        full_img_url = f"https://www.cagematch.net/{src.lstrip('/')}" if not src.startswith('http') else src
                        bounds = extract_logo_timeline_from_text(text_val)
                        
                        timeline.append({
                            "logo_url": full_img_url,
                            "date_start": bounds["start"],
                            "date_end": bounds["end"],
                            "is_current": bounds["is_current"],
                            "raw_text": text_val
                        })
                        
        if not timeline:
            header_div = soup.find('div', class_='LayoutBodyHeader')
            if header_div:
                img_tag = header_div.find('img')
                if img_tag and img_tag.get('src'):
                    src = img_tag['src']
                    full_img_url = f"https://www.cagematch.net/{src.lstrip('/')}" if not src.startswith('http') else src
                    timeline.append({
                        "logo_url": full_img_url,
                        "date_start": "1910-01-01",
                        "date_end": "2050-12-31"
                    })
        else:
            dated_entries = [e for e in timeline if e["raw_text"] != "" and e["raw_text"] != "()"]
            blank_entries = [e for e in timeline if e["raw_text"] == "" or e["raw_text"] == "()"]
            
            if dated_entries:
                dated_entries.sort(key=lambda x: x["date_start"])
                if blank_entries:
                    oldest_dated_start = dated_entries[0]["date_start"]
                    for b_entry in blank_entries:
                        b_entry["date_start"] = "1910-01-01"
                        b_entry["date_end"] = oldest_dated_start
                    timeline = blank_entries + dated_entries
                else:
                    timeline = dated_entries
            else:
                for entry in timeline:
                    entry["date_start"] = "1910-01-01"
                    entry["date_end"] = "2050-12-31"

            if timeline:
                newest_entry = timeline[-1]
                newest_text = newest_entry.get("raw_text", "").lower()
                is_active = "today" in newest_text or "present" in newest_text or newest_text == "" or newest_text == "()" or newest_text.endswith("- )")
                
                if not is_active and newest_entry["date_end"] != "2050-12-31":
                    try:
                        date_parts = newest_entry["date_end"].split('-')
                        padded_year = str(int(date_parts[0]) + 1)
                        newest_entry["date_end"] = f"{padded_year}-{date_parts[1]}-{date_parts[2]}"
                    except Exception:
                        pass

            for entry in timeline:
                entry.pop("is_current", None)
                entry.pop("raw_text", None)

    except Exception as e:
        print(f"    ⚠️ Failed capturing promotion logo sequence for ID {promo_id}: {e}")
        
    return timeline

def get_wrestler_aliases(html_content, worker_id):
    aliases = []
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        h1_element = soup.find('h1')
        if h1_element:
            h1_text = h1_element.get_text().strip()
            if h1_text and h1_text not in aliases:
                aliases.append(h1_text)
                
        h2_elements = soup.find_all('h2')
        for h2 in h2_elements:
            raw_text = h2.get_text() or ""
            if "also known as " in raw_text.lower():
                clean_string = re.sub(r'(?i)^also known as\s+', '', raw_text.strip())
                for name in clean_string.split(';'):
                    for split_name in name.split(','):
                        final_name = split_name.strip()
                        if final_name and final_name not in aliases:
                            aliases.append(final_name)
                break
    except Exception as e:
        print(f"    ⚠️ Alias parsing failure for worker {worker_id}: {e}")
    return aliases

def secure_browser_scrape():
    # 1. Initialize master layout structure
    master_output = {
        "wrestlers": {},
        "titles_metadata": {},
        "promotion_logos": {}
    }
    
    # 2. READ existing data first if database exists, protecting history
    if os.path.exists(DB_FILE):
        print(f"📖 Existing database file '{DB_FILE}' found. Loading historical entries into memory...")
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                historical_db = json.load(f)
                master_output["wrestlers"].update(historical_db.get("wrestlers", {}))
                master_output["titles_metadata"].update(historical_db.get("titles_metadata", {}))
                master_output["promotion_logos"].update(historical_db.get("promotion_logos", {}))
            print(f"✅ Loaded {len(master_output['wrestlers'])} wrestlers and {len(master_output['titles_metadata'])} titles from past records.")
        except json.JSONDecodeError:
            print("⚠️ Warning: Existing DB file appears malformed or blank. Building database from scratch.")
        except Exception as read_err:
            print(f"⚠️ Warning reading database file: {read_err}")
            
    collected_promotion_ids = set()

    print("Connecting to live debugging Chrome instance on port 9222...")
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            page = context.new_page()
            
            for title_id in TITLE_IDS:
                url = f"https://www.cagematch.net/?id=5&nr={title_id}"
                print(f"\n📋 Fetching metadata parameters for Title ID {title_id}...")
                page.goto(url, wait_until="domcontentloaded")
                time.sleep(0.3)
                
                overview_soup = BeautifulSoup(page.content(), 'html.parser')
                history_map = fetch_title_history_names(overview_soup, title_id)
                promotion_map = fetch_promotion_history(overview_soup, title_id)
                
                # Overwrite or append title parameter branches safely
                master_output["titles_metadata"][title_id] = {
                    "name_history": history_map,
                    "promotion_history": promotion_map
                }
                
                for p_entry in promotion_map:
                    if p_entry["promotion_id"] != "Unknown":
                        collected_promotion_ids.add(p_entry["promotion_id"])
                
                lineage_url = f"https://www.cagematch.net/?id=5&nr={title_id}&page=2"
                print(f"🔗 Crawling lineage nodes for Title ID {title_id}...")
                page.goto(lineage_url, wait_until="domcontentloaded")
                time.sleep(0.3)
                
                lineage_soup = BeautifulSoup(page.content(), 'html.parser')
                table_rows = lineage_soup.find_all('tr', class_=['TableContents', 'TableContentsSelected']) or lineage_soup.find_all('tr')

                for row in table_rows:
                    columns = row.find_all('td')
                    if len(columns) < 3:
                        continue
                    
                    iso_date = None
                    worker_links = []
                    
                    for col in columns:
                        col_text = col.get_text(strip=True)
                        parsed_date = parse_cagematch_date(col_text)
                        if parsed_date:
                            iso_date = parsed_date
                            continue 
                        
                        links = col.find_all('a', href=True)
                        for link in links:
                            href = link['href']
                            if "id=2&" in href and "nr=" in href:
                                name_text = link.get_text(strip=True)
                                if name_text and "VACANT" not in name_text.upper():
                                    worker_links.append((href, name_text))
                    
                    if iso_date and worker_links:
                        for worker_link, worker_name in worker_links:
                            id_match = re.search(r'nr=(\d+)', worker_link)
                            if id_match:
                                worker_id = id_match.group(1)
                                
                                # If wrestler wasn't tracked historically, seed default state
                                if worker_id not in master_output["wrestlers"]:
                                    master_output["wrestlers"][worker_id] = {
                                        "name": worker_name,
                                        "aliases": [worker_name],
                                        "timeline": [],
                                        "aliases_scraped": False 
                                    }
                                
                                # Update base name to newest scraped title lineage name
                                master_output["wrestlers"][worker_id]["name"] = worker_name
                                
                                entry = {
                                    "title_id": title_id,
                                    "date": iso_date
                                }
                                
                                if not any(t["date"] == iso_date and t["title_id"] == title_id for t in master_output["wrestlers"][worker_id]["timeline"]):
                                    master_output["wrestlers"][worker_id]["timeline"].append(entry)

            print("\n🏭 Starting Promotion Logo History Scrape Phase...")
            for promo_id in collected_promotion_ids:
                logo_timeline = scrape_promotion_logos(page, promo_id)
                master_output["promotion_logos"][promo_id] = logo_timeline

            print("\n👤 Fetching alternative gimmicks & processing timelines...")
            for w_id, data in master_output["wrestlers"].items():
                cleaned_timeline = [item for item in data.get("timeline", []) if isinstance(item, dict)]
                cleaned_timeline.sort(key=lambda x: x["date"]) 
                master_output["wrestlers"][w_id]["timeline"] = cleaned_timeline

                if not data.get("aliases_scraped", False):
                    print(f"🔍 Fetching alternative gimmicks for: {data['name']}...")
                    url = f"https://www.cagematch.net/?id=2&nr={w_id}"
                    try:
                        page.goto(url, wait_until="domcontentloaded")
                        time.sleep(0.3)
                        
                        found_aliases = get_wrestler_aliases(page.content(), w_id)
                        # Keep whatever legacy aliases were present, merging with newly scraped aliases
                        existing_aliases = data.get("aliases", [])
                        all_names = list(set([data['name']] + existing_aliases + found_aliases))
                        master_output["wrestlers"][w_id]["aliases"] = [n for n in all_names if n]
                        master_output["wrestlers"][w_id]["aliases_scraped"] = True 
                        time.sleep(0.3)
                    except Exception as loop_err:
                        print(f"  ⚠️ Could not reach profile page for worker {w_id}: {loop_err}")
                
            page.close()

        except Exception as e:
            print(f"💥 Scraping loop broke: {e}")
        finally:
            print("\n💾 MERGING AND WRITING MASTER DATABASE JSON NOW...")
            try:
                # Atomically write to a temp file first to guarantee your records aren't broken on crashes
                TMP_FILE = DB_FILE + '.tmp'
                with open(TMP_FILE, 'w', encoding='utf-8') as f:
                    json.dump(master_output, f, indent=2, ensure_ascii=False)
                os.replace(TMP_FILE, DB_FILE)
                print(f"🎉 Complete! Structured database merged and saved successfully with tracking logs intact.")
            except Exception as save_err:
                print(f"🚨 Disk error during file replacement operations: {save_err}")

if __name__ == "__main__":
    secure_browser_scrape()