import json
import time
import os
from pathlib import Path

import pandas as pd
import requests

# ==========================================
# CONFIGURATION
# ==========================================
API_KEY = os.environ.get("MODIO_API_KEY")
if not API_KEY:
    raise SystemExit("Set the MODIO_API_KEY environment variable (see .env.example)")
GAME_ID = 6715
BASE_URL = f"https://g-{GAME_ID}.modapi.io/v1"
HEADERS = {"X-Modio-Platform": "windows", "Accept-Language": "en", "Accept": "application/json"}

# Filenames
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "modio" / "csv_sweep"
DATA_DIR.mkdir(parents=True, exist_ok=True)

FILES = {
    "master": str(DATA_DIR / "bg3_master.csv"),
    "files": str(DATA_DIR / "bg3_files.csv"),
    "deps": str(DATA_DIR / "bg3_deps.csv"),
    "dets": str(DATA_DIR / "bg3_dets.csv"),
    "comments": str(DATA_DIR / "bg3_comments.csv"),
    "events": str(DATA_DIR / "bg3_events.csv"),
    "metas": str(DATA_DIR / "bg3_metas.csv"),
    "teams": str(DATA_DIR / "bg3_teams.csv")
}

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def safe_api_request(url, params={}):
    """Handles requests with robust error/rate-limit recovery."""
    while True:
        try:
            # Merging parameters safely
            final_params = {**(params or {}), "api_key": API_KEY}
            res = requests.get(url, headers=HEADERS, params=final_params, timeout=15)
            
            if res.status_code == 429:
                backoff = int(res.headers.get("Retry-After", 15))
                print(f"     [Rate Limit] Sleeping {backoff}s...")
                time.sleep(backoff if backoff > 0 else 15)
                continue
            
            if res.status_code in [403, 404]: return None
            res.raise_for_status()
            return res.json()
            
        except Exception as e:
            print(f"     [Connection Error] {e}. Retrying in 10s...")
            time.sleep(10)

def save_to_csv(data, filename):
    if not data: return
    df = pd.DataFrame(data)
    # Check if file exists to handle header writing correctly
    file_exists = os.path.exists(filename)
    df.to_csv(filename, mode='a', header=not file_exists, index=False)

# ==========================================
# MAIN EXECUTION
# ==========================================
def run_scraper():
    # Load existing IDs to enable resuming
    processed_ids = set()
    if os.path.exists(FILES["master"]):
        try:
            existing_df = pd.read_csv(FILES["master"])
            if 'id' in existing_df.columns:
                processed_ids = set(existing_df['id'].tolist())
        except Exception:
            pass
    
    print(f"Resuming: {len(processed_ids)} mods already processed.")

    offset = 0
    while True:
        payload = safe_api_request(f"{BASE_URL}/games/{GAME_ID}/mods", {"_limit": 100, "_offset": offset})
        if not payload or not payload.get("data"): break
        
        for mod in payload["data"]:
            m_id = mod['id']
            if m_id in processed_ids: continue
            
            print(f"Processing Mod ID: {m_id} - {mod.get('name', 'Unknown')}")
            
            # Map sub-resource URLs
            sub_urls = {
                "files": f"{BASE_URL}/games/{GAME_ID}/mods/{m_id}/files",
                "deps": f"{BASE_URL}/games/{GAME_ID}/mods/{m_id}/dependencies",
                "dets": f"{BASE_URL}/games/{GAME_ID}/mods/{m_id}/dependants",
                "comments": f"{BASE_URL}/games/{GAME_ID}/mods/{m_id}/comments",
                "events": f"{BASE_URL}/games/{GAME_ID}/mods/{m_id}/events",
                "metas": f"{BASE_URL}/games/{GAME_ID}/mods/{m_id}/metas",
                "teams": f"{BASE_URL}/games/{GAME_ID}/mods/{m_id}/team"
            }
            
            # Save master record
            save_to_csv([mod], FILES["master"])
            
            # Save sub-items
            for key, url in sub_urls.items():
                data = safe_api_request(url, params={})
                if data and 'data' in data:
                    for item in data['data']:
                        item['parent_mod_id'] = m_id
                    save_to_csv(data['data'], FILES[key])
            
            processed_ids.add(m_id)
            time.sleep(0.5) # Compliance pacing
            
        offset += 100
        print(f"Page finished. Offset: {offset}")

if __name__ == "__main__":
    run_scraper()
    print("Scraping complete!")