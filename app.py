import json
import random
import os
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "wrestlers_db.json")

def load_and_filter_database():
    """Loads the new 3-root schema and prepares the game collections."""
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
    else:
        raw_data = {"wrestlers": {}, "titles_metadata": {}, "promotion_logos": {}}

    wrestlers_source = raw_data.get("wrestlers", {})
    titles_metadata = raw_data.get("titles_metadata", {})
    promo_logos_source = raw_data.get("promotion_logos", {})

    filtered_db = {}
    alias_counts = {}

    # Gather valid game candidates (wrestlers with 2 or more career milestones)
    for worker_id, data in wrestlers_source.items():
        if len(data.get("timeline", [])) >= 2:
            filtered_db[worker_id] = data
            for alias in data.get("aliases", [data["name"]]):
                clean_alias = alias.strip()
                if clean_alias:
                    alias_counts[clean_alias] = alias_counts.get(clean_alias, 0) + 1

    # Map autocomplete drop-down entries dynamically
    autocomplete_items = []
    for worker_id, data in filtered_db.items():
        main_name = data["name"]
        for alias in data.get("aliases", [main_name]):
            clean_alias = alias.strip()
            if not clean_alias:
                continue
            if alias_counts[clean_alias] > 1 and clean_alias.lower() != main_name.lower():
                display_name = f"{clean_alias} -> {main_name}"
            else:
                display_name = clean_alias
            if display_name not in autocomplete_items:
                autocomplete_items.append(display_name)

    return filtered_db, titles_metadata, promo_logos_source, sorted(autocomplete_items)

# Initialize global app lookups
WRESTLER_DB, TITLES_METADATA, PROMOTION_LOGOS, AUTOCOMPLETE_LIST = load_and_filter_database()


def parse_date(date_str, fallback_date):
    """Safely parses standard or semi-standard date strings into datetime objects."""
    if not date_str:
        return fallback_date
    for fmt in ('%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%Y/%m/%d'):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    try:
        # Catch partial strings like just "YYYY" or "YYYY-MM"
        if len(date_str) == 4:
            return datetime.strptime(date_str, '%Y')
    except ValueError:
        pass
    return fallback_date


def resolve_title_name(title_id, win_date_str):
    """Looks up name history within titles_metadata for a title_id at a specific point in time."""
    meta = TITLES_METADATA.get(str(title_id), {})
    name_history = meta.get("name_history", [])
    
    if not name_history:
        return f"Title ID {title_id}"
        
    win_date = parse_date(win_date_str, datetime.min)
    
    for entry in name_history:
        start = parse_date(entry.get("start"), datetime.min)
        end = parse_date(entry.get("end"), datetime.max)
        if start <= win_date <= end:
            return entry.get("name")
            
    return name_history[0].get("name", f"Title ID {title_id}")


from datetime import datetime, timedelta

def resolve_active_promotions(title_id, win_date_str):
    """
    Resolves promotion ownership for a title on a given date.

    Features:
    - Handles overlapping promotion periods.
    - Handles missing end dates.
    - Handles small gaps in history.
    - Returns nearest valid promotion if date falls into a gap.
    """

    meta = TITLES_METADATA.get(str(title_id), {})
    promo_history = meta.get("promotion_history", [])

    if not promo_history:
        return []

    win_date = parse_date(win_date_str, datetime.min)

    matches = []

    for entry in promo_history:
        start = parse_date(entry.get("start"), datetime.min)
        end = parse_date(entry.get("end"), datetime.max)

        if start <= win_date <= end:
            pid = entry.get("promotion_id")

            if pid and pid != "Unknown":
                matches.append(pid)

    if matches:
        return list(dict.fromkeys(matches))

    # Fallback for gaps in data
    nearest_entry = None
    nearest_distance = None

    for entry in promo_history:
        start = parse_date(entry.get("start"), datetime.min)
        end = parse_date(entry.get("end"), datetime.max)

        if win_date < start:
            distance = (start - win_date).days
        elif win_date > end:
            distance = (win_date - end).days
        else:
            distance = 0

        if nearest_distance is None or distance < nearest_distance:
            nearest_distance = distance
            nearest_entry = entry

    if nearest_entry:
        pid = nearest_entry.get("promotion_id")

        if pid and pid != "Unknown":
            return [pid]

    return []


def get_active_logos_for_reign(promotion_ids, win_date_str):
    """Resolves local corporate gif badges safely based on active promotions and datetime bounds."""
    logo_filenames = []
    if not promotion_ids or not win_date_str:
        return logo_filenames
        
    win_date = parse_date(win_date_str, datetime.now())
        
    for p_id in promotion_ids:
        p_id_str = str(p_id)
        if p_id_str in PROMOTION_LOGOS:
            matched_any_logo = False
            
            # Loop 1: Find strict matching date entry
            for logo_entry in PROMOTION_LOGOS[p_id_str]:
                start = parse_date(logo_entry.get("date_start"), datetime.min)
                end = parse_date(logo_entry.get("date_end"), datetime.max)
                
                if start <= win_date <= end:
                    url = logo_entry.get("logo_url", "")
                    if url:
                        filename = url.split('/')[-1]
                        local_path = os.path.join('static', 'logos', filename)
                        if os.path.exists(local_path) and filename not in logo_filenames:
                            logo_filenames.append(filename)
                            matched_any_logo = True
            
            # Loop 2 Fallback: If chronological gaps hide the logo, pull the nearest available default logo
            if not matched_any_logo and PROMOTION_LOGOS[p_id_str]:
                fallback_entry = PROMOTION_LOGOS[p_id_str][0]
                url = fallback_entry.get("logo_url", "")
                if url:
                    filename = url.split('/')[-1]
                    local_path = os.path.join('static', 'logos', filename)
                    if os.path.exists(local_path) and filename not in logo_filenames:
                        logo_filenames.append(filename)
                        
    return logo_filenames


def compress_timeline(raw_timeline):
    """Assembles structural configurations on-the-fly and groups sequential matching titles."""
    compressed = []
    
    for item in raw_timeline:
        if not isinstance(item, dict):
            continue
            
        title_id = str(item.get("title_id", ""))
        win_date = item.get("date", "")
        
        if not title_id or not win_date:
            continue
            
        filename = f"title_{title_id}.png"
        
        title_display_name = resolve_title_name(title_id, win_date)
        promotions = resolve_active_promotions(title_id, win_date)
        
        if compressed and compressed[-1]["title_id"] == title_id:
            compressed[-1]["count"] += 1
        else:
            has_image = os.path.exists(os.path.join('static', filename))
            promo_logo_filenames = get_active_logos_for_reign(promotions, win_date)
            
            compressed.append({
                "title_id": title_id,
                "filename": filename, 
                "title_name": title_display_name,
                "has_image": has_image, 
                "promo_logo_urls": promo_logo_filenames, 
                "count": 1
            })
            
    return compressed


@app.route('/')
def home():
    if not WRESTLER_DB:
        return "<h1>Error: Empty Database! Run scraper first.</h1>"

    random_id = random.choice(list(WRESTLER_DB.keys()))
    wrestler = WRESTLER_DB[random_id]
    
    clean_timeline = [item for item in wrestler["timeline"] if isinstance(item, dict) and "date" in item]
    clean_timeline.sort(key=lambda x: x["date"])
    processed_timeline = compress_timeline(clean_timeline)
    
    row_size = 4
    timeline_rows = [processed_timeline[i:i + row_size] for i in range(0, len(processed_timeline), row_size)]
    
    return render_template_string(HTML_TEMPLATE, timeline_rows=timeline_rows, wrestler_id=random_id, dropdown_list=AUTOCOMPLETE_LIST)


@app.route('/guess', methods=['POST'])
def check_guess():
    data = request.json
    user_guess = data.get('guess', '').strip().lower()
    wrestler_id = data.get('id')
    
    wrestler_entry = WRESTLER_DB.get(wrestler_id, {})
    main_name = wrestler_entry.get('name', '')
    
    valid_targets = []
    for alias in wrestler_entry.get("aliases", [main_name]):
        valid_targets.append(alias.lower())
        valid_targets.append(f"{alias.lower()} -> {main_name.lower()}")

    if user_guess in valid_targets:
        return jsonify({"correct": True, "message": f"Correct! It's {main_name}!"})
    return jsonify({"correct": False, "reveal": main_name})


HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>REINDL - Title History Game</title>
    <style>
        body { 
            background-color: #000000; 
            color: #000000; 
            font-family: Verdana, Arial, Helvetica, sans-serif; 
            font-size: 13px;
            margin: 0;
            padding: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        .page-wrapper {
            width: 100%;
            max-width: 1200px;
            background-color: #000000;
            box-sizing: border-box;
        }

        .top-bar {
            background-color: #1a1a1a;
            color: #cccccc;
            font-size: 11px;
            text-align: right;
            padding: 5px 15px;
        }

        .site-banner {
            background-color: #022360;
            border-top: 2px solid #0c439c;
            border-bottom: 2px solid #010e26;
            height: 105px;
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
        }
        
        .logo-placeholder {
            color: #ffffff;
            font-family: 'Arial Black', Impact, sans-serif;
            font-size: 38px;
            letter-spacing: 4px;
            font-weight: 900;
            text-transform: uppercase;
        }
        .logo-sub {
            font-family: Arial, Helvetica, sans-serif;
            font-size: 11px;
            color: #cccccc;
            letter-spacing: 1px;
            text-align: center;
            margin-top: -5px;
            text-transform: uppercase;
        }

        .breadcrumb-container {
            background-color: #ffffff;
            padding: 12px 15px 8px 15px;
            border-bottom: 1px solid #dddddd;
        }
        .breadcrumb-box {
            border: 1px solid #cccccc;
            padding: 6px 15px;
            background-color: #ffffff;
            font-size: 11px;
            color: #666666;
            max-width: 950px;
            margin: 0 auto;
        }
        .breadcrumb-box span { color: #03328a; font-weight: bold; }

        .main-content-body {
            background-color: #ffffff;
            min-height: 600px;
            padding: 30px 20px;
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        .content-width-restrictor {
            width: 100%;
            max-width: 950px;
        }

        .title-heading {
            font-family: Arial, Helvetica, sans-serif;
            font-size: 22px;
            font-weight: bold;
            color: #000000;
            margin: 0 0 25px 0;
        }

        .section-sub-bar {
            color: #cc9900;
            font-size: 12px;
            font-weight: bold;
            border-bottom: 1px solid #cc9900;
            padding-bottom: 4px;
            margin-bottom: 15px;
            text-transform: uppercase;
        }

        .timeline-container { 
            display: flex;
            flex-direction: column;
            gap: 30px;
            background-color: #f5f5f5;
            border: 1px solid #cccccc;
            padding: 40px;
            box-sizing: border-box;
            margin-bottom: 30px;
            width: 100%;
        }

        .timeline-row {
            display: grid;
            grid-template-columns: repeat(4, 185px);
            column-gap: 45px;
            width: 100%;
            justify-content: start;
        }

        .timeline-node {
            position: relative;
            display: flex;
            align-items: center;
            width: 185px;
            min-height: 100px;
        }
        
        .belt-card { 
            position: relative; 
            width: 185px; 
            min-height: 100px; 
            display: flex; 
            flex-direction: column; 
            justify-content: center; 
            align-items: center;
            border: 1px solid #aaaaaa;
            background-color: #ffffff;
            box-sizing: border-box;
            padding-top: 20px; 
        }
        
        .stacked-belt-img { 
            max-width: 90%; 
            max-height: 70px; 
            object-fit: contain; 
            margin: auto;
        }
        
        .fallback-text-card { 
            width: 100%; 
            font-size: 11px; 
            font-weight: bold; 
            padding: 8px; 
            color: #03328a; 
            box-sizing: border-box;
            text-align: center;
            margin: auto;
        }
        
        .badge-wrapper {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%; 
            display: flex;
            flex-direction: row;
            flex-wrap: wrap; 
            align-items: stretch;
            z-index: 1000;
        }

        .reign-badge { 
            background-color: #03328a; 
            color: #ffffff; 
            font-weight: bold; 
            font-size: 10px; 
            padding: 2px 6px; 
            border-right: 1px solid #aaaaaa;
            border-bottom: 1px solid #aaaaaa;
            display: flex;
            align-items: center;
        }
        
        .promo-badge-img {
            height: 17px;
            width: auto;
            max-width: 45px; 
            object-fit: contain;
            border-right: 1px solid #aaaaaa;
            border-bottom: 1px solid #aaaaaa;
            background-color: #ffffff;
            display: block;
        }
        
        .flow-arrow-horizontal { 
            position: absolute;
            right: -45px;
            color: #03328a; 
            font-size: 20px; 
            font-weight: bold;
            user-select: none;
            width: 45px;
            text-align: center;
            z-index: 2000;
        }

        .game-status-bar {
            width: 100%;
            padding: 12px 15px;
            box-sizing: border-box;
            border: 1px solid #cccccc;
            background-color: #f9f9f9;
            font-weight: bold;
            font-size: 13px;
            margin-bottom: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .status-neutral { border-left: 5px solid #03328a; color: #03328a; }
        .status-wrong { border-left: 5px solid #cc0000; color: #cc0000; background-color: #fff0f0; }
        .status-correct { border-left: 5px solid #008800; color: #008800; background-color: #f0fff0; }
        
        .action-link {
            font-size: 11px;
            text-transform: uppercase;
            color: #ffffff;
            background-color: #03328a;
            padding: 4px 10px;
            text-decoration: none;
            cursor: pointer;
            margin-left: 10px;
        }
        .action-link:hover { background-color: #0c439c; }
        
        .input-section { 
            display: flex; 
            gap: 10px; 
            width: 100%; 
            background-color: #f5f5f5;
            border: 1px solid #cccccc;
            padding: 15px;
            box-sizing: border-box;
        }
        
        .autocomplete-wrapper { 
            position: relative; 
            flex-grow: 1; 
        }
        
        input { 
            width: 100%; 
            padding: 10px; 
            font-size: 13px; 
            font-family: Verdana, sans-serif;
            border: 1px solid #cccccc; 
            background-color: #FFFFFF; 
            color: #000000; 
            outline: none; 
            box-sizing: border-box; 
        }
        input:focus { border-color: #03328a; }
        input:disabled { background-color: #eeeeee; color: #666666; cursor: not-allowed; }
        
        .dropdown-box { 
            position: absolute; 
            top: 100%; 
            left: 0; 
            width: 100%; 
            background-color: #FFFFFF; 
            border: 1px solid #cccccc; 
            border-top: none;
            max-height: 220px; 
            overflow-y: auto; 
            z-index: 9999; 
            display: none;
            box-sizing: border-box;
            box-shadow: 0px 4px 8px rgba(0,0,0,0.15);
        }
        
        .dropdown-item { 
            padding: 10px 12px; 
            cursor: pointer; 
            font-size: 12px; 
            color: #000000;
            border-bottom: 1px solid #eeeeee;
            text-align: left;
        }
        .dropdown-item:hover { 
            background-color: #03328a; 
            color: #ffffff; 
        }
        
        button { 
            padding: 10px 24px; 
            background-color: #03328a; 
            border: 1px solid #01163d;
            font-family: Arial, sans-serif;
            font-size: 13px;
            font-weight: bold; 
            cursor: pointer; 
            color: #ffffff; 
            text-transform: uppercase;
            flex-shrink: 0;
        }
        button:hover { background-color: #0c439c; }
        button:disabled { background-color: #cccccc; border-color: #aaaaaa; cursor: not-allowed; }
    </style>
</head>
<body>

<div class="page-wrapper">
    <div class="top-bar">
        Public Edition | Active Timeline Puzzle Mod
    </div>

    <div class="site-banner">
        <div>
            <div class="logo-placeholder">REINDL</div>
            <div class="logo-sub">The Internet Wrestling Database</div>
        </div>
    </div>

    <div class="breadcrumb-container">
        <div class="breadcrumb-box">
            REINDL &raquo; Titles Database &raquo; <span>Guess The Worker Timeline Puzzle</span>
        </div>
    </div>

    <div class="main-content-body">
        <div class="content-width-restrictor">
            
            <div class="title-heading">Title History Timeline Verification</div>
            
            <div class="section-sub-bar">Active Puzzle Parameters</div>

            <div class="timeline-container">
                {% for row in timeline_rows %}
                    {% set row_loop = loop %}
                    <div class="timeline-row">
                        {% for item in row %}
                            <div class="timeline-node">
                                <div class="belt-card">
                                    
                                    <!-- Badges Section Container -->
                                    <div class="badge-wrapper">
                                        {% if item.promo_logo_urls %}
                                            {% for gif_filename in item.promo_logo_urls %}
                                                <img src="/static/logos/{{ gif_filename }}" class="promo-badge-img">
                                            {% endfor %}
                                        {% endif %}
                                        {% if item.count > 1 %}
                                            <div class="reign-badge">{{ item.count }}x</div>
                                        {% endif %}
                                    </div>

                                    {% if item.has_image %}
                                        <img src="/static/{{ item.filename }}" class="stacked-belt-img">
                                    {% else %}
                                        <div class="fallback-text-card">{{ item.title_name }}</div>
                                    {% endif %}
                                </div>

                                {% if not (row_loop.last and loop.last) %}
                                    <div class="flow-arrow-horizontal">➔</div>
                                {% endif %}
                            </div>
                        {% endfor %}
                    </div>
                {% endfor %}
            </div>

            <div class="section-sub-bar">Submit Identity Guess</div>

            <div id="statusBar" class="game-status-bar status-neutral">
                <span id="statusText">Identify the worker based on the championship history sequence above.</span>
                <span id="statusCounter">Guesses Left: 5</span>
            </div>

            <div class="input-section">
                <div class="autocomplete-wrapper">
                    <input type="text" id="guessInput" placeholder="Search the database for worker identity..." autocomplete="off" oninput="filterDropdown()">
                    <div id="dropdown" class="dropdown-box"></div>
                </div>
                <button id="submitBtn" onclick="submitGuess()">Search</button>
            </div>

        </div>
    </div>
</div>

<script>
    const allWrestlers = {{ dropdown_list | tojson }};
    let remainingGuesses = 5;
    let gameOver = false;

    function filterDropdown() {
        if (gameOver) return;
        const input = document.getElementById('guessInput').value.toLowerCase();
        const dropdown = document.getElementById('dropdown');
        dropdown.innerHTML = '';
        
        if (!input) {
            dropdown.style.display = 'none';
            return;
        }

        const matches = allWrestlers.filter(name => name.toLowerCase().includes(input)).slice(0, 8);
        
        if (matches.length > 0) {
            dropdown.style.display = 'block';
            matches.forEach(name => {
                const item = document.createElement('div');
                item.className = 'dropdown-item';
                item.innerText = name;
                item.onclick = () => {
                    document.getElementById('guessInput').value = name;
                    dropdown.style.display = 'none';
                };
                dropdown.appendChild(item);
            });
        } else {
            dropdown.style.display = 'none';
        }
    }

    document.addEventListener('click', (e) => {
        if (!e.target.closest('.autocomplete-wrapper')) {
            document.getElementById('dropdown').style.display = 'none';
        }
    });

    function submitGuess() {
        if (gameOver) return;
        
        const val = document.getElementById('guessInput').value.trim ? document.getElementById('guessInput').value.trim() : document.getElementById('guessInput').value;
        if (!val) return;

        const statusBar = document.getElementById('statusBar');
        const statusText = document.getElementById('statusText');
        const statusCounter = document.getElementById('statusCounter');
        const guessInput = document.getElementById('guessInput');
        const submitBtn = document.getElementById('submitBtn');

        fetch('/guess', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ guess: val, id: "{{ wrestler_id }}" })
        })
        .then(res => res.json())
        .then(data => {
            if (data.correct) {
                gameOver = true;
                statusBar.className = "game-status-bar status-correct";
                statusText.innerHTML = `${data.message} <a class="action-link" href="/">Next Puzzle</a>`;
                statusCounter.innerText = "Winner!";
                guessInput.disabled = true;
                submitBtn.disabled = true;
                document.getElementById('dropdown').style.display = 'none';
            } else {
                remainingGuesses--;
                if (remainingGuesses <= 0) {
                    gameOver = true;
                    statusBar.className = "game-status-bar status-wrong";
                    statusText.innerHTML = `Out of guesses! The correct answer was <strong>${data.reveal}</strong>. <a class="action-link" href="/">Try Another</a>`;
                    statusCounter.innerText = "Game Over";
                    guessInput.disabled = true;
                    submitBtn.disabled = true;
                    document.getElementById('dropdown').style.display = 'none';
                } else {
                    statusBar.className = "game-status-bar status-wrong";
                    statusText.innerText = "Incorrect choice. Check the sequence timeline and try again!";
                    statusCounter.innerText = `Guesses Left: ${remainingGuesses}`;
                }
            }
        });
    }
</script>
</body>
</html>
"""

if __name__ == "__main__":
    try:
        app.run(debug=True)
    except Exception as e:
        import traceback

        print("\n=== CRASH ===\n")
        traceback.print_exc()

        input("\nPress Enter to close...")