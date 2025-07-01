#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "llama-cpp-python",
#   "huggingface-hub",
#   "colorama",
# ]
# ///
"""
Simple test harness for structured LLM output extraction
Shows expected vs actual for every test case

Run with uv:
  # Make executable (first time only)
  chmod +x Single_LLM_Filename_Test_Harness.py
  
  # Test with default model (runs both scored + custom)
  ./Single_LLM_Filename_Test_Harness.py
  
  # Or run directly with uv
  uv run Single_LLM_Filename_Test_Harness.py
"""

import re
import json
from pathlib import Path
from llama_cpp import Llama
from huggingface_hub import hf_hub_download
from colorama import init, Fore, Style
from collections import Counter
import csv
import datetime

init(autoreset=True)

def classify_failure(err, field):
    import re

    got = err.get("got")
    exp = err.get("expected")
    raw = err.get("raw_output", "")

    got_str = str(got or "").lower()
    exp_str = str(exp or "").lower()

    # ── SEQUENCE ────────────────────────────────────────────────────────────────
    if field == "sequence":
        if exp and not got:
            return "dropped sequence"
        if not exp and isinstance(got, str) and got.isdigit() and len(got) != 4:
            return "picked street/day"
        if exp and isinstance(got, str) and len(got) == 4 and got != str(exp):
            return "picked year"
        if exp and isinstance(got, str) and len(got) != len(str(exp)):
            return "padding mismatch"
        return "other"

    # ── DATE ───────────────────────────────────────────────────────────────────
    if field == "date":
        e = err["expected"] or {}
        g = err["got"] or {}
        if e.get("day") and g.get("day") is None:
            return "dropped day"
        if e.get("month") and g.get("month") is None:
            return "dropped month"
        if e.get("month") and e.get("day") and g.get("day") == e.get("month") and g.get("month") == e.get("day"):
            return "swapped month/day"
        if raw and any(h in raw.lower() for h in ["christmas","bastille","new years"]):
            return "holiday parse"
        return "other"

    # ── EVENT ──────────────────────────────────────────────────────────────────
    if field == "event":
        if any(d in got_str for d in ["01-20","12-25","07-04","03-10","05-15"]):
            return "picked date"
        if got_str.isdigit():
            return "picked sequence"
        if got_str in ["summer","winter","spring","fall"]:
            return "picked season"
        # generic noun when none expected
        if not exp and any(n in got_str for n in ["birthday","picnic","dinner","anniversary","cake"]):
            return "picked generic noun"
        # stray month name as event
        if re.search(r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b", got_str):
            return "picked month name"
        # POI or city mis‐picked as event
        if exp is None and got_str in [str(err.get("poi") or "").lower(), str(err.get("city") or "").lower()]:
            return "picked location as event"
        if exp and exp_str not in got_str:
            return "dropped event"
        return "other"

    # ── NAMES ──────────────────────────────────────────────────────────────────
    if field == "names":
        if isinstance(got, list):
            return "returned list"
        if got_str.endswith((".",",")):
            return "punctuation left"
        if got_str and got_str != got_str.title():
            return "wrong casing"
        if exp and got_str == "":
            return "dropped name"
        return "other"

    # ── POI / CITY ─────────────────────────────────────────────────────────────
    if field in ("poi", "city"):
        if exp and exp_str not in got_str:
            return "partial match dropped token"
        if got and not exp:
            return "spurious"
        return "other"

    # ── STATE ──────────────────────────────────────────────────────────────────
    if field == "state":
        if got and len(got) > 2:
            return "used full name instead of code"
        if got_str in ["ny","ca","tx","fl","ma","az"] and got != got.upper():
            return "lowercase code"
        if exp_str == "ny" and not got:
            return "dropped NYC mapping"
        if got_str in ["qc","on","bc"] and not exp:
            return "spurious province code"
        if exp and got and got != exp:
            return "wrong code"
        return "other"

    # ── ADDRESS / COUNTRY ──────────────────────────────────────────────────────
    if field in ("address", "country"):
        if exp and not got:
            return "omitted"
        if got and not exp:
            return "spurious"
        return "other"

    # ── FALLBACK ───────────────────────────────────────────────────────────────
    if not got and exp:
        return "omitted"
    if got and not exp:
        return "spurious"
    return "other"

class StructuredExtractionTest:
    def __init__(self, cache_dir: Path = Path(".cache")):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(exist_ok=True)
        self.prompt_version = "v1.0"
        self.prompt_template = """
Analyze this photo filename to determine WHERE the photo was taken.

For each filename, think step by step:
1. What is likely the SUBJECT of the photo? (what's in it)
2. Is there a LOCATION NAME explicitly written in the filename?
3. Are there any clues about the type of location? (restaurant, park, home, tourist spot, etc.)
4. Is this a place you could find on a public map, or is it someone's personal property?

Output JSON with these fields:
{
  "location_confidence": "high/medium/low/none",
  "primary_search": "<best search query for Apple Maps>",
  "alternate_search": "<backup search if primary is wrong>",
  "location_type": "venue/landmark/city/address/unknown",
  "location_context": "<explanation of your reasoning>",
  
  "extracted": {
    "subject": "<what the photo is OF>",
    "where_taken": "<where you think it was taken>",
    "landmark_name": "<specific place name if mentioned>",
    "city": "<city if found - keep abbreviations like NYC, SF, LA as-is>",
    "state": "<2-letter code if US/Canada>",
    "country": "<country if not US>",
    "date_parts": {"year": null, "month": null, "day": null}
  },
  
  "search_strategy": "venue_first/city_first/landmark_only/need_more_info"
}

Rules:
- Set location_confidence="none" if location is: home, house, grandma's, grandpa's, or any personal/family place
- For search queries, remove activity/event words: "Beach Vacation Cancun" → "Cancun"
- Keep common city abbreviations unchanged: NYC stays NYC, SF stays SF, LA stays LA
- Month names: Jan→"01", Feb→"02", Mar→"03", Apr→"04", May→"05", Jun→"06", Jul→"07", Aug→"08", Sep→"09", Oct→"10", Nov→"11", Dec→"12"
- Extract ISO dates like 2023-05-15 as year:"2023", month:"05", day:"15"
- Extract partial dates like 2023-05 as year:"2023", month:"05", day:null
- For dates like "July 4th 2023", extract as year:"2023", month:"07", day:"04"
- Trailing 3-4 digits are sequence numbers unless part of a year
- Filename can have any extension (.heic, .jpg, .png, etc.)
- CRITICAL: Always add a comma after "date_parts": {...} since more fields follow it

Examples:
Filename: Medieval_Times_Orlando_FL_Nov_14_1996.heic
{
  "location_confidence": "high",
  "primary_search": "Medieval Times, Orlando FL",
  "alternate_search": "Orlando, FL",
  "location_type": "venue",
  "location_context": "Medieval Times is a restaurant chain, this photo was likely taken at the Orlando location",
  "extracted": {
    "subject": "visit to Medieval Times",
    "where_taken": "Medieval Times restaurant in Orlando",
    "landmark_name": "Medieval Times",
    "city": "Orlando",
    "state": "FL",
    "country": null,
    "date_parts": {"year": "1996", "month": "11", "day": "14"}
  },
  "search_strategy": "venue_first"
}

Filename: Family_Reunion_Grandmas_House_July_4th_2023.jpg
{
  "location_confidence": "none",
  "primary_search": null,
  "alternate_search": null,
  "location_type": "unknown",
  "location_context": "This is a family gathering at someone's personal residence, not a searchable public location",
  "extracted": {
    "subject": "family reunion",
    "where_taken": "grandma's house",
    "landmark_name": null,
    "city": null,
    "state": null,
    "country": null,
    "date_parts": {"year": "2023", "month": "07", "day": "04"}
  },
  "search_strategy": "need_more_info"
}

Filename: {filename}
"""
        
        self.test_cases = [
            (
                "Carleton_E_Watkins_Los_Angeles_CA_July_1876_2145.heic",
                {
                    "names": "Carleton E Watkins",
                    "poi": None,
                    "address": None,
                    "city": "Los Angeles",
                    "state": "CA",
                    "country": None,
                    "date": {"year": "1876", "month": "07", "day": None},
                    "sequence": "2145",
                }
            ),
            
            (
                "grand_canyon_tuweep_az_march_2024.heic",
                {
                    "names": None,
                    "poi": "Grand Canyon",
                    "address": None,
                    "city": "Tuweep",
                    "state": "AZ",
                    "country": None,
                    "date": {"year": "2024", "month": "03", "day": None},
                    "sequence": None,
                }
            ),
            
            (
                "Golden_Gate_Bridge_San_Francisco_CA_2024_2023.heic",
                {
                    "names": None,
                    "poi": "Golden Gate Bridge",
                    "address": None,
                    "city": "San Francisco",
                    "state": "CA",
                    "country": None,
                    "date": {"year": "2024", "month": None, "day": None},
                    "sequence": "2023",
                },
            ),
            
            (
                "eiffel_tower_paris_france_bastille_day_2023.heic",
                {
                    "names": None,
                    "poi": "Eiffel Tower",
                    "address": None,
                    "city": "Paris",
                    "state": None,
                    "country": "France",
                    "date": {"year": "2023", "month": "07", "day": "14"},
                    "sequence": None,
                    "event": "Bastille Day"
                },
            ),
            
            (
                "tokyo_tower_japan_2024.heic",
                {
                    "names": None,
                    "poi": "Tokyo Tower",
                    "address": None,
                    "city": "Tokyo",
                    "state": None,
                    "country": "Japan",
                    "date": {"year": "2024", "month": None, "day": None},
                    "sequence": None,
                },
            ),
            
            (
                "1600_Amphitheatre_Pkwy_Mountain_View_CA_2024.heic",
                {
                    "names": None,
                    "poi": None,
                    "address": "1600 Amphitheatre Pkwy",
                    "city": "Mountain View",
                    "state": "CA",
                    "country": None,
                    "date": {"year": "2024", "month": None, "day": None},
                    "sequence": None,
                },
            ),
            
            (
                "christmas_dinner_2023_grandmas_house_salem_ma_2553.heic",
                {
                    "names": None,
                    "poi": None,
                    "address": None,
                    "city": "Salem",
                    "state": "MA",
                    "country": None,
                    "date": {"year": "2023", "month": "12", "day": "25"},
                    "sequence": "2553",
                    "event": "Christmas Dinner"
                },

            ),
            
            (
                "arizona_road_trip_2024.heic",
                {
                    "names": None,
                    "poi": None,
                    "address": None,
                    "city": None,
                    "state": "AZ",
                    "country": None,
                    "date": {"year": "2024", "month": None, "day": None},
                    "sequence": None,
                },
            ),
            
            (
                "still_life_apples_2024.heic",
                {
                    "names": None,
                    "poi": None,
                    "address": None,
                    "city": None,
                    "state": None,
                    "country": None,
                    "date": {"year": "2024", "month": None, "day": None},
                    "sequence": None,
                },
            ),
            
            (
                "St_Louis_Arch_Missouri_July_4_2023_2023.heic",
                {
                    "names": None,
                    "poi": "St Louis Arch",
                    "address": None,
                    "city": "St Louis",
                    "state": "MO",
                    "country": None,
                    "date": {"year": "2023", "month": "07", "day": "04"},
                    "sequence": "2023",
                },
            ),
            
            (
                "Trip_2024_December_25_NYC.heic",
                {
                    "names": None,
                    "poi": None,
                    "address": None,
                    "city": "New York City",
                    "state": "NY",
                    "country": None,
                    "date": {"year": "2024", "month": "12", "day": "25"},
                    "sequence": None,
                },
            ),
            
            (
                "albert_running_abq_nm_Nov_2003_2013.heic",
                {
                    "names": None,
                    "poi": None,
                    "address": None,
                    "city": "Albuquerque",
                    "state": "NM",
                    "country": None,
                    "date": {"year": "2003", "month": "11", "day": None},
                    "sequence": "2013",
                },
            ),
            
            (
                "sarah_graduation_harvard_cambridge_ma_may_2022_0001.heic",
                {
                    "names": None,
                    "poi": "Harvard",
                    "address": None,
                    "city": "Cambridge",
                    "state": "MA",
                    "country": None,
                    "date": {"year": "2022", "month": "05", "day": None},
                    "sequence": "0001",
                    "event": "Sarah graduation"
                },
            ),
            
            (
                "versailles_palace_2004_0002.heic",
                {
                    "names": None,
                    "poi": "Versailles Palace",
                    "address": None,
                    "city": None,
                    "state": None,
                    "country": None,
                    "date": {"year": "2004", "month": None, "day": None},
                    "sequence": "0002",
                },
            ),
            
            (
                "mount_rushmore_july_1998.heic",
                {
                    "names": None,
                    "poi": "Mount Rushmore",
                    "address": None,
                    "city": None,
                    "state": None,
                    "country": None,
                    "date": {"year": "1998", "month": "07", "day": None},
                    "sequence": None,
                },
            ),
            
            (
                "white_house_christmas_tree_2019_4567.heic",
                {
                    "names": None,
                    "poi": "White House",
                    "address": None,
                    "city": None,
                    "state": None,
                    "country": None,
                    "date": {"year": "2019", "month": "12", "day": None},
                    "sequence": "4567",
                },
            ),
            
            (
                "123_Main_Street_Springfield_IL.heic",
                {
                    "names": None,
                    "poi": None,
                    "address": "123 Main Street",
                    "city": "Springfield",
                    "state": "IL",
                    "country": None,
                    "date": {"year": None, "month": None, "day": None},
                    "sequence": None,
                },
            ),
            
            (
                "456_Elm_Ave_Boulder_CO_IMG.heic",
                {
                    "names": None,
                    "poi": None,
                    "address": "456 Elm Ave",
                    "city": "Boulder",
                    "state": "CO",
                    "country": None,
                    "date": {"year": None, "month": None, "day": None},
                    "sequence": None,
                },
            ),
            
            (
                "Chickadee_and_Thistle_Fidelia_Bridges_Salem_MA_Jan_1875_0146.heic",
                {
                    "names": "Fidelia Bridges",
                    "poi": None,
                    "address": None,
                    "city": "Salem",
                    "state": "MA",
                    "country": None,
                    "date": {"year": "1875", "month": "01", "day": None},
                    "sequence": "0146",
                },
            ),
            
            (
                "Iceberg_Canyon_Colorado_River_CO_Looking_Above_June_1871_Timothy_H_O'Sullivan_0151.heic",
                {
                    "names": "Timothy H O'Sullivan",
                    "poi": "Iceberg Canyon",
                    "address": None,
                    "city": None,
                    "state": "CO",
                    "country": None,
                    "date": {"year": "1871", "month": "06", "day": None},
                    "sequence": "0151",
                },
            ),
            
            (
                "Côte_d'Azur_France_Summer_Holiday_2022.heic",
                {
                    "names": None,
                    "poi": None,
                    "address": None,
                    "city": "Côte d'Azur",
                    "state": None,
                    "country": "France",
                    "date": {"year": "2022", "month": None, "day": None},
                    "sequence": None,
                    "event": "Summer Holiday"
                },
            ),
            
            (
                "221B_Baker_Street_London_October_1_1888_Sherlock_0009.heic",
                {
                    "names": None,
                    "poi": None,
                    "address": "221B Baker Street",
                    "city": "London",
                    "state": None,
                    "country": None,
                    "date": {"year": "1888", "month": "10", "day": "01"},
                    "sequence": "0009",
                },
            ),
            
            (
                "SXSW_Outside_Austin_TX_March_10_2023.heic",
                {
                    "names": None,
                    "poi": None,
                    "address": None,
                    "city": "Austin",
                    "state": "TX",
                    "country": None,
                    "date": {"year": "2023", "month": "03", "day": "10"},
                    "sequence": None,
                    "event": "SXSW",
                },
            ),
            
            (
                "mom_dad_anniversary_dinner_olive_garden_des_moines_ia_feb_14_2020.heic",
                {
                    "names": None,
                    "poi": "Olive Garden",
                    "address": None,
                    "city": "Des Moines",
                    "state": "IA",
                    "country": None,
                    "date": {"year": "2020", "month": "02", "day": "14"},
                    "sequence": None,
                },
            ),
            
            (
                "birthday_cake_2023_05_15.heic",
                {
                    "names": None,
                    "poi": None,
                    "address": None,
                    "city": None,
                    "state": None,
                    "country": None,
                    "date": {"year": "2023", "month": "05", "day": "15"},
                    "sequence": None,
                },
            ),
            
            (
                "washington_monument_july_4_2019.heic",
                {
                    "names": None,
                    "poi": "Washington Monument",
                    "address": None,
                    "city": None,
                    "state": None,
                    "country": None,
                    "date": {"year": "2019", "month": "07", "day": "04"},
                    "sequence": None,
                },
            ),
            
            (
                "niagara_falls_canadian_side_august_2018_pano.heic",
                {
                    "names": None,
                    "poi": "Niagara Falls",
                    "address": None,
                    "city": None,
                    "state": None,
                    "country": "Canada",
                    "date": {"year": "2018", "month": "08", "day": None},
                    "sequence": None,
                },
            ),
            
            (
                "NYC_Central_Park_Picnic_September_21_2021_0099.heic",
                {
                    "names": None,
                    "poi": "Central Park",
                    "address": None,
                    "city": "New York City",
                    "state": "NY",
                    "country": None,
                    "date": {"year": "2021", "month": "09", "day": "21"},
                    "sequence": "0099",
                    "event": "Picnic"
                },
            ),
            
            (
                "1600_Pennsylvania_Ave_Washington_DC_Presidential_Inauguration_01-20-2021.heic",
                {
                    "names": None,
                    "poi": None,
                    "address": "1600 Pennsylvania Ave",
                    "city": "Washington",
                    "state": "DC",
                    "country": None,
                    "date": {"year": "2021", "month": "01", "day": "20"},
                    "sequence": None,
                    "event": "Presidential Inauguration"
                },
            ),
            
            (
                "Golden_Temple_Amritsar_India_November_15_2019_0123.heic",
                {
                    "names": None,
                    "poi": "Golden Temple",
                    "address": None,
                    "city": "Amritsar",
                    "state": None,
                    "country": "India",
                    "date": {"year": "2019", "month": "11", "day": "15"},
                    "sequence": "0123",
                },
            ),
            
            (
                "Louvre_Museum_Paris_FR_April_2010_0077.heic",
                {
                    "names": None,
                    "poi": "Louvre Museum",
                    "address": None,
                    "city": "Paris",
                    "state": None,
                    "country": "France",
                    "date": {"year": "2010", "month": "04", "day": None},
                    "sequence": "0077",
                },
            ),
            
            (
                "Stanley_Park_Vancouver_BC_Canada_Sep_2011.heic",
                {
                    "names": None,
                    "poi": "Stanley Park",
                    "address": None,
                    "city": "Vancouver",
                    "state": "BC",
                    "country": "Canada",
                    "date": {"year": "2011", "month": "09", "day": None},
                    "sequence": None,
                },
            ),
            
            (
                "Scheveningen_Beach_The_Hague_Netherlands_Summer2022.heic",
                {
                    "names": None,
                    "poi": "Scheveningen Beach",
                    "address": None,
                    "city": "The Hague",
                    "state": None,
                    "country": "Netherlands",
                    "date": {"year": "2022", "month": None, "day": None},
                    "sequence": None,
                    "event": "Summer"
                },
            )
        ]
        
        self.llm = None
    
    def load_model(self):
        """Load Mistral-7B-v0.3 model"""
        print(f"{Fore.YELLOW}Loading Mistral-7B-v0.3...{Style.RESET_ALL}")
        
        model_path = hf_hub_download(
            repo_id="bartowski/Mistral-7B-Instruct-v0.3-GGUF",
            filename="Mistral-7B-Instruct-v0.3-Q4_K_M.gguf",
            cache_dir=self.cache_dir
        )
        
        self.llm = Llama(
            model_path=model_path,
            n_ctx=2048,
            n_gpu_layers=-1,
            verbose=False,
            n_threads=8
        )
        
        print(f"{Fore.GREEN}✓ Model loaded{Style.RESET_ALL}\n")
    
    def create_prompt(self, filename: str) -> str:
        """Create structured extraction prompt"""
        return self.prompt_template.replace("{filename}", filename)
    
    def write_summary_csv(self, overall_pct, field_correct, field_total):
        csv_path = Path("run_metrics.csv")
        header = ["run_id", "timestamp", "prompt_version", "prompt", "overall_accuracy"] \
               + [f"{f}_pct" for f in field_correct]
        if not csv_path.exists():
            with open(csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(header)
        prompt_text = self.prompt_template.replace("\n", "\\n")
        row = [
            len(open(csv_path).readlines()) if csv_path.exists() else 1,
            datetime.datetime.now().isoformat(),
            self.prompt_version,
            prompt_text,
            f"{overall_pct:.2f}"
        ] + [f"{(field_correct[f]/field_total[f]*100):.2f}" for f in field_correct]
        with open(csv_path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(row)

    def run_test(self):
        """Run the test and display results"""
        self.load_model()

        print(f"{Fore.CYAN}=== STRUCTURED EXTRACTION TEST ==={Style.RESET_ALL}")
        print(f"Testing {len(self.test_cases)} filenames\n")
        print("=" * 80)

        # define the 9 fields we check
        fields = ["names","poi","address","city","state","country","date","sequence","event"]

        # overall counters
        overall_correct = 0
        overall_total   = 0

        # per-field counters
        field_correct = {f: 0 for f in fields}
        field_total   = {f: 0 for f in fields}

        # collect failures per field
        failures = {f: [] for f in fields}

        for i, (filename, expected) in enumerate(self.test_cases, 1):
            print(f"\n{Fore.CYAN}[{i}/{len(self.test_cases)}] {filename}{Style.RESET_ALL}")

            # Create prompt
            prompt = self.create_prompt(filename)

            # Run LLM
            response = self.llm(
                prompt,
                max_tokens=400,
                temperature=0.1,
                stop=["Filename:"],
                echo=False
            )
            raw_output = response['choices'][0]['text'].strip()

            try:
                # Clean up code fences
                if raw_output.startswith("```"):
                    lines = raw_output.split('\n')
                    raw_output = '\n'.join(lines[1:-1])
                
                # Clean up "Output:" prefix from Mistral
                if raw_output.startswith("Output:"):
                    raw_output = raw_output[7:].strip()

                parsed_output = json.loads(raw_output)

                def show(x):
                    return x if x is not None else "null"

                # file‐level counters
                file_correct = 0
                file_total   = len(fields)

                # Compare
                for field in fields:
                    expected_val = expected.get(field)
                    got_val      = parsed_output.get(field)

                    # increment per‐field total
                    field_total[field] += 1
                    overall_total     += 1

                    # display
                    if isinstance(expected_val, dict):
                        exp_str = f"{show(expected_val['year'])}-{show(expected_val['month'])}-{show(expected_val['day'])}"
                    else:
                        exp_str = show(expected_val)
                    if isinstance(got_val, dict):
                        got_str = f"{show(got_val['year'])}-{show(got_val['month'])}-{show(got_val['day'])}"
                    else:
                        got_str = show(got_val)

                    print(f"  {field:15} Expected: {exp_str}")
                    print(f"  {' ':15} Got:      {got_str}\n")

                    # tally correctness or record failure
                    if got_val == expected_val:
                        file_correct        += 1
                        overall_correct     += 1
                        field_correct[field] += 1
                    else:
                        failures[field].append({
                            "filename":   filename,
                            "expected":   expected_val,
                            "got":        got_val,
                            "raw_output": raw_output
                        })

                # file accuracy
                pct = file_correct / file_total * 100
                col = Fore.GREEN if pct >= 90 else Fore.YELLOW
                print(f"{col}File accuracy: {pct:.1f}% ({file_correct}/{file_total}){Style.RESET_ALL}")

            except json.JSONDecodeError as e:
                print(f"  {Fore.RED}JSON PARSE ERROR:{Style.RESET_ALL} {e}")
                print(f"  Raw output: {raw_output[:100]}...")

            print("-" * 80)

        # overall accuracy
        overall_pct = overall_correct / overall_total * 100 if overall_total else 0
        print(f"\n{Fore.CYAN}=== SUMMARY ==={Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}Overall accuracy: {overall_pct:.1f}% ({overall_correct}/{overall_total}){Style.RESET_ALL}")

        # per-field accuracy
        print(f"\n{Fore.CYAN}=== PER-FIELD ACCURACY ==={Style.RESET_ALL}")
        for f in fields:
            pct = field_correct[f] / field_total[f] * 100 if field_total[f] else 0
            col = Fore.GREEN if pct >= 90 else Fore.YELLOW
            print(f"{col}{f:15}: {pct:.1f}% ({field_correct[f]}/{field_total[f]}){Style.RESET_ALL}")

        # log metrics to CSV
        self.write_summary_csv(overall_pct, field_correct, field_total)

        # per-failure taxonomy
        print(f"\n{Fore.CYAN}=== FAILURE TAXONOMY ==={Style.RESET_ALL}")
        for field, errs in failures.items():
            if not errs:
                continue
            cats = Counter(classify_failure(err, field) for err in errs)
            print(f"\n{field}:")
            for cat, count in cats.items():
                print(f"  - {cat}: {count}")

        # per-field failures
        print(f"\n{Fore.CYAN}=== PER-FIELD FAILURES ==={Style.RESET_ALL}")
        for f in fields:
            if failures[f]:
                print(f"\n[{f}]")
                for err in failures[f]:
                    print(f"  • filename:   {err['filename']}")
                    print(f"    expected:   {err['expected']}")
                    print(f"    got:        {err['got']}")
                    print(f"    raw_json:   {err['raw_output']!r}\n")

def main():
    test = StructuredExtractionTest()
    test.run_test()

if __name__ == "__main__":
    main()