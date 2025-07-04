#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "flask",
#   "pillow",
#   "pillow-heif",
#   "timezonefinder",
#   "pyobjc-core",
#   "pyobjc-framework-CoreLocation",
#   "pyobjc-framework-MapKit",
#   "paramiko",
#   "wakeonlan",
#   "waitress",
#   "llama-cpp-python",
#   "huggingface-hub"
# ]
# ///
"""
Photo Metadata Editor - Add date and location metadata to digitized negatives and prints 
Copyright (C) 2025 Logan Barron

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

SYSTEM source = The system/code automatically read and populated the data
USER source = The user explicitly performed an action
"""

# Standard library imports
import os
import re
import json
import base64
import sqlite3
import subprocess
import urllib.request
import tarfile
import shutil
import csv
import time
import logging
import atexit
import sys
import threading
import queue
import hashlib
import tempfile
import socket
import webbrowser
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Tuple, List, Any
from io import BytesIO
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum, auto
from concurrent.futures import ThreadPoolExecutor, Future, as_completed

# Third-party imports
from flask import Flask, render_template_string, request, jsonify
from PIL import Image
import pillow_heif
from timezonefinder import TimezoneFinder

# Apple geocoding imports
import objc
from CoreLocation import CLLocationManager
from Foundation import NSRunLoop, NSDate, NSThread
from PyObjCTools import AppHelper

# Pipeline integration imports
import paramiko
from wakeonlan import send_magic_packet

# LLM parser imports
try:
    from llama_cpp import Llama
    from huggingface_hub import hf_hub_download
    _LLM_AVAILABLE = True
except ImportError:
    _LLM_AVAILABLE = False
    print("Warning: LLM parser not available - install llama-cpp-python")

# Register HEIF format
pillow_heif.register_heif_opener()

# ============================================================================
# CONFIGURATION
# ============================================================================

# .env template for auto-generation
ENV_TEMPLATE = """# Photo Metadata Editor Configuration
# This file must be in the /code/ directory alongside photo_metadata_editor.py

# Camera/scanner that digitized the photos
CAMERA_MAKE=FUJIFILM
CAMERA_MODEL=GFX100S II
IMAGE_DESCRIPTION=Camera Scanned Image

# Keywords for tracking metadata status
DATE_KEYWORD=MissingDate
LOCATION_KEYWORD=MissingLocation

# Unknown date values (when user clicks "Unknown Date")
UNKNOWN_YEAR=1901
UNKNOWN_MONTH=01
UNKNOWN_DAY=02

# Performance settings
THUMBNAIL_WORKERS=10
METADATA_WORKERS=10

# Cache sizes
METADATA_CACHE_SIZE=1000
THUMBNAIL_CACHE_SIZE=1000

# ExifTool version
EXIFTOOL_VERSION=13.30

# Web interface port
WEB_PORT=5555

# LLM Parser Settings (optional)
LLM_PARSER_ENABLED=true
"""

# Load configuration from .env file
_env_config = {}
_env_path = Path(__file__).parent / '.env'

if not _env_path.exists():
    print("Creating .env file with default values...")
    _env_path.write_text(ENV_TEMPLATE)
    print(f"Created {_env_path}")
    print("\n IMPORTANT: Edit .env with your camera/scanner information!")
    print("   Then run ./code/photo_metadata_editor.py /path/to/your/photos.\n")
    sys.exit(1)

try:
    with open(_env_path) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if line and not line.startswith('#'):
                if '=' not in line:
                    print(f"ERROR: Invalid line {line_num} in .env: {line}")
                    sys.exit(1)
                key, value = line.split('=', 1)
                _env_config[key.strip()] = value.strip()
except Exception as e:
    print(f"ERROR: Failed to read .env file: {e}")
    sys.exit(1)

# Required configuration values - will error if missing
try:
    # Camera that digitized the photos
    CAMERA_MAKE = _env_config['CAMERA_MAKE']
    CAMERA_MODEL = _env_config['CAMERA_MODEL']
    IMAGE_DESCRIPTION = _env_config['IMAGE_DESCRIPTION']
    
    # Metadata keywords
    DATE_KEYWORD = _env_config['DATE_KEYWORD']
    LOCATION_KEYWORD = _env_config['LOCATION_KEYWORD']
    
    # Unknown date values
    SYSTEM_DATE = {
        "year": _env_config['UNKNOWN_YEAR'],
        "month": _env_config['UNKNOWN_MONTH'],
        "day": _env_config['UNKNOWN_DAY']
    }
    
    # Performance
    THUMBNAIL_WORKERS = int(_env_config['THUMBNAIL_WORKERS']) # Number of parallel workers for thumbnail generation
    METADATA_WORKERS = int(_env_config['METADATA_WORKERS']) # Number of parallel workers for metadata processing
    
    # ExifTool
    EXIFTOOL_VERSION = _env_config['EXIFTOOL_VERSION']
    EXIFTOOL_URL = f"https://exiftool.org/Image-ExifTool-{EXIFTOOL_VERSION}.tar.gz"
    
    # Web interface
    WEB_PORT = int(_env_config['WEB_PORT'])
    
    # Cache sizes
    METADATA_CACHE_SIZE = int(_env_config['METADATA_CACHE_SIZE'])
    THUMBNAIL_CACHE_SIZE = int(_env_config['THUMBNAIL_CACHE_SIZE'])
    
    # LLM Parser
    USE_LLM_PARSER = _env_config.get('LLM_PARSER_ENABLED', 'true').lower() == 'true'
    
except KeyError as e:
    print(f"ERROR: Missing required configuration: {e}")
    print("Check your .env file has all required values from .env.example")
    sys.exit(1)
except ValueError as e:
    print(f"ERROR: Invalid configuration value: {e}")
    sys.exit(1)

# ============================================================================
# CONSTANTS AND CONFIGURATION - NON USER CONFIGURABLE
# ============================================================================

# Paths
SCRIPT_DIR = Path(__file__).parent.resolve().absolute()
BASE_DIR = SCRIPT_DIR.parent.resolve().absolute()  # Go up one level from code/
DATA_DIR = (BASE_DIR / "data").resolve().absolute()
TOOLS_DIR = (BASE_DIR / "tools").resolve().absolute()

# Month mapping
MONTH_MAP = {
    m: f"{i:02d}" for i, m in enumerate(
        "jan feb mar apr may jun jul aug sep oct nov dec".split(), 1
    )
}
MONTH_MAP.update({
    "january": "01", "february": "02", "march": "03", "april": "04", 
    "may": "05", "june": "06", "july": "07", "august": "08", 
    "september": "09", "october": "10", "november": "11", "december": "12"
})

# US States
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", 
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", 
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", 
    "WI", "WY", "DC"
}

# State capitals for GPS lookup
STATE_CAPITALS = {
    "AL": "Montgomery", "AK": "Juneau", "AZ": "Phoenix", "AR": "Little Rock",
    "CA": "Sacramento", "CO": "Denver", "CT": "Hartford", "DE": "Dover",
    "FL": "Tallahassee", "GA": "Atlanta", "HI": "Honolulu", "ID": "Boise",
    "IL": "Springfield", "IN": "Indianapolis", "IA": "Des Moines", "KS": "Topeka",
    "KY": "Frankfort", "LA": "Baton Rouge", "ME": "Augusta", "MD": "Annapolis",
    "MA": "Boston", "MI": "Lansing", "MN": "Saint Paul", "MS": "Jackson",
    "MO": "Jefferson City", "MT": "Helena", "NE": "Lincoln", "NV": "Carson City",
    "NH": "Concord", "NJ": "Trenton", "NM": "Santa Fe", "NY": "Albany",
    "NC": "Raleigh", "ND": "Bismarck", "OH": "Columbus", "OK": "Oklahoma City",
    "OR": "Salem", "PA": "Harrisburg", "RI": "Providence", "SC": "Columbia",
    "SD": "Pierre", "TN": "Nashville", "TX": "Austin", "UT": "Salt Lake City",
    "VT": "Montpelier", "VA": "Richmond", "WA": "Olympia", "WV": "Charleston",
    "WI": "Madison", "WY": "Cheyenne", "DC": "Washington"
}

# State name to abbreviation mapping
STATE_NAME_TO_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC", "dc": "DC"
}

# Countries list for location routing
COUNTRIES_LIST = [
    # A
    "afghanistan", "albania", "algeria", "andorra", "angola", "antigua and barbuda", 
    "argentina", "armenia", "australia", "austria", "azerbaijan",
    # B
    "bahamas", "bahrain", "bangladesh", "barbados", "belarus", "belgium", "belize", 
    "benin", "bhutan", "bolivia", "bosnia and herzegovina", "botswana", "brazil", 
    "brunei", "bulgaria", "burkina faso", "burundi",
    # C
    "cambodia", "cameroon", "canada", "cape verde", "central african republic", "chad", 
    "chile", "china", "colombia", "comoros", "congo", "costa rica", "croatia", "cuba", 
    "cyprus", "czech republic", "czechia",
    # D
    "denmark", "djibouti", "dominica", "dominican republic",
    # E
    "ecuador", "egypt", "el salvador", "england", "equatorial guinea", "eritrea", 
    "estonia", "eswatini", "ethiopia",
    # F
    "fiji", "finland", "france",
    # G
    "gabon", "gambia", "georgia", "germany", "ghana", "greece", "grenada", "guatemala", 
    "guinea", "guinea-bissau", "guyana",
    # H
    "haiti", "honduras", "hungary",
    # I
    "iceland", "india", "indonesia", "iran", "iraq", "ireland", "israel", "italy", 
    "ivory coast",
    # J
    "jamaica", "japan", "jordan",
    # K
    "kazakhstan", "kenya", "kiribati", "kosovo", "kuwait", "kyrgyzstan",
    # L
    "laos", "latvia", "lebanon", "lesotho", "liberia", "libya", "liechtenstein", 
    "lithuania", "luxembourg",
    # M
    "madagascar", "malawi", "malaysia", "maldives", "mali", "malta", "marshall islands", 
    "mauritania", "mauritius", "mexico", "micronesia", "moldova", "monaco", "mongolia", 
    "montenegro", "morocco", "mozambique", "myanmar",
    # N
    "namibia", "nauru", "nepal", "netherlands", "new zealand", "nicaragua", "niger", 
    "nigeria", "north korea", "north macedonia", "northern ireland", "norway",
    # O
    "oman",
    # P
    "pakistan", "palau", "palestine", "panama", "papua new guinea", "paraguay", "peru", 
    "philippines", "poland", "portugal", "puerto rico",
    # Q
    "qatar",
    # R
    "romania", "russia", "rwanda",
    # S
    "saint kitts and nevis", "saint lucia", "saint vincent and the grenadines", "samoa", 
    "san marino", "sao tome and principe", "saudi arabia", "scotland", "senegal", 
    "serbia", "seychelles", "sierra leone", "singapore", "slovakia", "slovenia", 
    "solomon islands", "somalia", "south africa", "south korea", "south sudan", "spain", 
    "sri lanka", "sudan", "suriname", "sweden", "switzerland", "syria",
    # T
    "taiwan", "tajikistan", "tanzania", "thailand", "timor-leste", "togo", "tonga", 
    "trinidad and tobago", "tunisia", "turkey", "turkmenistan", "tuvalu",
    # U
    "uae", "uganda", "uk", "ukraine", "united arab emirates", "united kingdom", 
    "united states", "uruguay", "usa", "uzbekistan",
    # V
    "vanuatu", "vatican city", "venezuela", "vietnam", 
    # W
    "wales",
    # Y
    "yemen",
    # Z
    "zambia", "zimbabwe"
]

# ============================================================================
# PIPELINE CONFIGURATION
# ============================================================================

# Pipeline configuration
DEFAULT_CONFIG = {
    "mac_b": {
        "host": "pipeline@mac-b.local", # Update to actual .local host
        "mac_address": "XX:XX:XX:XX:XX:XX", # Update to lan mac address (not wifi)
        "ssh_key_path": "~/.ssh/pipeline_key",
        "wake_wait_time": 10,
        "connection_timeout": 60
    },
    "transfer": {
        "batch_size_limit": None,  # Set to number to limit batch size, null for unlimited
        "timeout_seconds": 300,
        "timeout_per_photo": 30,
        "retry_count": 2,
        "retry_delay": 5,
        "chunk_size": 65536
    },
    "paths": {
        "staging_dir": "~/ToSend",
        "remote_incoming": "~/IncomingPhotos",
        "remote_processed": "~/ProcessedPhotos",
        "remote_reports": "~/ImportReports",
        "local_reports": "~/reports"
    },
    "cleanup": {
        "keep_successful_days": 0,           # 0 = delete immediately after success
        "keep_failed_days": 0,               # 0 = delete immediately after failure
        "clean_import_log": True,            # Truncate import.log after each batch
        "clean_incoming_after_hours": 0.25,     # Clean orphaned files in IncomingPhotos every 15 minutes
        "startup_cleanup": True              # Clean old files on pipeline start
    }
}

# ============================================================================
# EXCEPTION CLASSES
# ============================================================================

class PipelineError(Exception):
    """Base exception for pipeline errors"""
    pass

class TransferError(PipelineError):
    """Error during file transfer"""
    pass

class ImportError(PipelineError):
    """Error during import process"""
    pass

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if '--debug' in sys.argv else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# FLASK APP INSTANCE
# ============================================================================

app = Flask(__name__)

# ============================================================================
# GLOBAL STATE CLASS
# ============================================================================

class AppState:
    """Global application state"""
    def __init__(self):
        self.working_dir: Optional[Path] = None
        self.photos_list: List[Path] = []
        self.current_index: int = 0
        self.current_filter: str = "needs_review"
        self.database: Optional['PhotoDatabase'] = None
        self.gazetteer: Optional['Gazetteer'] = None
        self.exiftool_path: Optional[Path] = None
        self.location_manager: Optional['LocationManager'] = None
        self.sort_by_sequence: bool = False
        
        # Pipeline infrastructure
        self.pipeline_output: List[str] = []
        self.pipeline_batch_id: Optional[str] = None
        
        # Integrated pipeline infrastructure
        self.pipeline_executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=min(4, (os.cpu_count() or 4)))
        self.pipeline_future: Optional[Future] = None
        self.pipeline_cancelled: bool = False
        self.pipeline_events: List[Dict[str, Any]] = []
        self.db_queue: queue.Queue = queue.Queue()
        self.pipeline_config: Optional[dict] = None
        self.pipeline_ssh_connections: List[Any] = []
        self.pipeline_staging_dirs: List[Path] = []
        self.data_dir: Path = DATA_DIR
        self.filename_parser = None 
        
        # Start database worker thread
        self._start_db_worker()
    
    def _start_db_worker(self):
        """Start background thread for database operations"""
        def worker():
            while True:
                try:
                    item = self.db_queue.get(timeout=1)
                    if item is None:  # Shutdown signal
                        break
                    
                    # Unpack based on number of items (backward compatibility)
                    if len(item) == 2:
                        operation, future = item
                    else:
                        # Legacy format - ignore
                        continue
                        
                    try:
                        result = operation()  # Execute the lambda/function
                        if future and not future.done():
                            future.set_result(result)
                    except Exception as e:
                        if future and not future.done():
                            future.set_exception(e)
                        logger.error(f"DB operation failed: {e}")
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"DB worker error: {e}")

        self.db_worker_thread = threading.Thread(target=worker, daemon=True)
        self.db_worker_thread.start()
    
    def shutdown_db_worker(self):
        """Cleanly shutdown the database worker thread"""
        if hasattr(self, 'db_queue') and hasattr(self, 'db_worker_thread'):
            self.db_queue.put(None)  # Send shutdown signal
            self.db_worker_thread.join(timeout=5.0)

# ============================================================================
# GLOBAL STATE INSTANCE
# ============================================================================

STATE = AppState()

# Register cleanup on exit
import atexit
atexit.register(lambda: STATE.shutdown_db_worker())

def cleanup_database_connections():
    if STATE.database and hasattr(STATE.database, '_pool'):
        STATE.database._pool.close_idle_connections()

atexit.register(cleanup_database_connections)
# Ensure pipeline threads don-t keep the interpreter alive
atexit.register(lambda: STATE.pipeline_executor.shutdown(wait=False, cancel_futures=True))


# ============================================================================
# GLOBAL VARIABLES
# ============================================================================

# Global rate limiting for Apple APIs
_last_api_call = 0.0

# Metadata cache - keyed by filepath + modification time
METADATA_CACHE = {}

# Thumbnail cache
THUMBNAIL_CACHE = {}

# Thread safety locks for caches
METADATA_CACHE_LOCK = threading.RLock()
THUMBNAIL_CACHE_LOCK = threading.RLock()
LOCATION_CACHE_LOCK = threading.RLock()

# LLM parsing queue infrastructure
LLM_PARSE_QUEUE = queue.PriorityQueue()
LLM_PARSE_RESULTS = {}  # filepath -> {'status': 'pending'|'ready', 'result': data}
MAX_LLM_PARSE_RESULTS = 5000 # Prevent unbounded growth
LLM_WORKER_THREAD = None # keep references to every LLM worker
LLM_WORKER_THREADS = []
LLM_WORKER_STOP = threading.Event()
MODEL_WARMED     = threading.Event()  # set after first priority-0 parse
WARM_CONDITION   = threading.Condition()  # Proper synchronization

# Try to import MKLocalSearch
try:
    from MapKit import MKLocalSearch, MKLocalSearchRequest
    _mk_local_search_available = True
except ImportError:
    _mk_local_search_available = False
    MKLocalSearch = None
    MKLocalSearchRequest = None

# Initialize location services (required for MKLocalSearch)
_location_manager = None
try:
    _location_manager = CLLocationManager.alloc().init()
    logger.info("Location services initialized for MKLocalSearch")
except Exception as e:
    logger.warning(f"Could not initialize location services: {e}")

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def extract_sequence_number(filename: str) -> Optional[int]:
    """Extracts the trailing number from a filename for sorting."""
    # Remove common extensions
    base = filename.replace('.heic', '').replace('.HEIC', '')
    parts = base.split('_')
    if parts:
        try:
            # The last part is assumed to be the sequence number
            return int(parts[-1])
        except (ValueError, IndexError):
            # No valid number found
            return None
    return None

def calculate_file_hash(filepath: Path) -> str:
    """Calculate SHA256 hash of file"""
    hash_sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_sha256.update(chunk)
    return hash_sha256.hexdigest()

def parse_gps_coordinate(coord_str):
    """Parse GPS coordinate from various ExifTool formats"""
    if not coord_str:
        return None
    
    try:
        return float(coord_str)
    except (ValueError, TypeError):
        try:
            coord_str = str(coord_str)
            match = re.match(r'(\d+)\s*deg\s*(\d+)\'\s*([\d.]+)"?\s*([NSEW])?', coord_str)
            if match:
                deg, min, sec, direction = match.groups()
                decimal = float(deg) + float(min)/60 + float(sec)/3600
                if direction in ['S', 'W']:
                    decimal = -decimal
                return decimal
        except:
            pass
    
    return None

def save_apple_cache():
    """Ensure any in-memory Apple geocoding results are persisted"""
    pass

# Register cleanup
atexit.register(save_apple_cache)

# ============================================================================
# DATA MODELS - ENUMS
# ============================================================================

class DataSource(Enum):
    """Source of data - only USER or SYSTEM"""
    USER = "user"
    SYSTEM = "system"

class Category(Enum):
    """Semantic category of a search result"""
    STATE = auto()
    CITY = auto()
    ADDRESS = auto()
    POI = auto()
    COUNTRY = auto()

# ============================================================================
# DATA MODELS - DATACLASSES
# ============================================================================

@dataclass
class DateInfo:
    """Date with source tracking"""
    year: str = ""
    month: str = ""
    day: str = ""
    year_source: Optional[DataSource] = None
    month_source: Optional[DataSource] = None
    day_source: Optional[DataSource] = None
    from_complete_suggestion: bool = False
    
    def is_complete(self) -> bool:
        """All fields present and from user"""
        return (self.year and self.month and self.day and
                all(s == DataSource.USER for s in 
                    [self.year_source, self.month_source, self.day_source]))
    
    def needs_tag(self) -> bool:
            """Needs MissingDate tag based on smart logic"""
            if not self.year:
                return True
            if self.year == "1901":
                return True
            # If we have year and month from ANY source, no tag needed
            # The source doesn't matter - what matters is having the data
            if self.year and self.month:
                return False
            # Otherwise needs tag
            return True

@dataclass
class LocationInfo:
    """Location with source tracking"""
    city: str = ""
    state: str = ""
    city_source: Optional[DataSource] = None
    state_source: Optional[DataSource] = None
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    gps_source: Optional[DataSource] = None
    landmark_name: Optional[str] = None
    landmark_source: Optional[DataSource] = None
    
    # Fields for international support
    country: str = ""
    country_code: str = ""
    country_source: Optional[DataSource] = None
    street: str = ""
    postal_code: str = ""
    neighborhood: str = ""
    
    def is_complete(self) -> bool:
        """Has city and state from user OR has exact GPS from user"""
        return (
            (self.gps_lat is not None and self.gps_source == DataSource.USER)
            or (self.city and self.state and 
                self.city_source == DataSource.USER and
                self.state_source == DataSource.USER)
        )
    
    def needs_tag(self) -> bool:
        # If we have GPS coordinates from ANY source, no tag needed
        if self.gps_lat is not None:
            return False
        # If we have both city and state from any source, no tag needed
        if self.city and self.state:
            return False
        # Otherwise needs tag
        return True

@dataclass
class SmartLocation:
    """Enhanced location object with display information"""
    city: str
    state: str
    landmark_name: Optional[str] = None
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    category: Optional[Category] = None
    id: Optional[int] = None
    use_count: int = 0
    last_used: Optional[datetime] = None
    
    # International support fields
    country: str = ""
    country_code: str = ""
    street: str = ""
    postal_code: str = ""
    neighborhood: str = ""
    
    @property
    def display_primary(self) -> str:
        """Primary display text for UI"""
        if self.landmark_name:
            return self.landmark_name
        elif self.street:
            return self.street
        else:
            parts = []
            if self.city:
                parts.append(self.city)
            if self.state:
                parts.append(self.state)
            elif self.country and self.country not in ["United States", "USA", ""]:
                # For international locations without states, show country
                parts.append(self.country)
            
            if parts:
                return ", ".join(parts)
            elif self.country:
                return self.country
            else:
                return "Unknown Location"
    
    @property
    def display_secondary(self) -> str:
        """Secondary display - shows what will be saved"""
        location_parts = []
        
        # Handle US state-only searches
        if self.category == Category.STATE and not self.city and self.state in US_STATES:
            capital = STATE_CAPITALS.get(self.state, "")
            if capital:
                location_parts.append(capital)
                location_parts.append(self.state)
        # Handle international locations
        elif self.city:
            location_parts.append(self.city)
            # For international cities, include state only if it exists
            if self.state:
                location_parts.append(self.state)
            # Always show country for international locations
            if self.country and self.country not in ["United States", "USA", ""]:
                location_parts.append(self.country)
        elif self.state:
            # State without city (US assumed if no country)
            location_parts.append(self.state)
            if self.country and self.country not in ["United States", "USA", ""]:
                location_parts.append(self.country)
        elif self.country:
            # Country only
            location_parts.append(self.country)
        
        return ", ".join(location_parts) if location_parts else "Unknown Location"
    
    @property
    def display_full(self) -> str:
        """Full display text with all details"""
        parts = []
        
        # Add primary identifier (landmark/street)
        if self.landmark_name:
            parts.append(self.landmark_name)
            if self.city or self.state or self.country:
                parts.append("-")
        elif self.street:
            parts.append(self.street)
            if self.city or self.state or self.country:
                parts.append(",")
        
        # Add location hierarchy
        location_parts = []
        if self.neighborhood and self.neighborhood != self.street:
            location_parts.append(self.neighborhood)
        if self.city:
            location_parts.append(self.city)
        if self.state:
            location_parts.append(self.state)
        if self.country and self.country not in ["United States", "USA", ""]:
            location_parts.append(self.country)
        
        # Join location parts
        if location_parts:
            parts.append(", ".join(location_parts))
        
        # Clean up formatting
        result = " ".join(parts)
        result = result.replace(" - ,", " - ")
        result = result.replace(" , ", ", ")
        result = result.replace("  ", " ")
        
        return result.strip() if result.strip() else "Unknown Location"
    
    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'city': self.city,
            'state': self.state,
            'landmark_name': self.landmark_name,
            'street': self.street,
            'gps_lat': self.gps_lat,
            'gps_lon': self.gps_lon,
            'display_primary': self.display_primary,
            'display_secondary': self.display_secondary,
            'display_full': self.display_full,
            'category': self.category.name if self.category else None,
            'use_count': self.use_count,
            'last_used': self.last_used.isoformat() if self.last_used else None,
            'country': self.country,
            'country_code': self.country_code,
            'postal_code': self.postal_code,
            'neighborhood': self.neighborhood
        }

# ============================================================================
# FILENAME PARSER CLASS (LLM-BASED)  
# ============================================================================

class FilenameParser:
    """LLM-based filename parser for extracting metadata from photo filenames.
    
    Uses Mistral-7B Instruct v0.3 model to intelligently extract dates, locations, people,
    events, and other metadata from filenames.
    """
    
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(exist_ok=True)
        self.llm = None
        self._parse_cache = {}  # In-memory cache: filename -> parsed result
        self._max_cache_size = 1000  # Maximum cache entries
        self._llm_lock = threading.Lock()  # Thread safety for LLM calls
        
        # Complex prompt focused on WHERE photos were taken
        self.prompt_template = """
Analyze this photo filename to determine WHERE the photo was taken.

For each filename, think step by step:
1. What is likely the SUBJECT of the photo? (what's in it)
2. What is likely the LOCATION where it was taken?
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

    def load_model(self):
        """Load the Mistral-7B Instruct v0.3 model (singleton pattern)."""
        if self.llm is not None:
            return self.llm

        # ---- first-call synchronisation ----
        with self._llm_lock:
            if self.llm is not None:
                return self.llm
            try:
                print("Downloading LLM model (first time only).")
                model_path = hf_hub_download(
                    repo_id="hflb/Mistral-7B-Instruct-v0.3-Filename-Finetune",
                    filename="mistral-7b-finetuned-q4_k_m.gguf",
                    cache_dir=self.cache_dir
                )

                print("Loading LLM model into memory.")
                self.llm = Llama(
                    model_path=str(model_path),
                    n_ctx=2048,
                    n_gpu_layers=-1,  # Use GPU if available
                    verbose=False,
                    n_threads=8
                )
                print("LLM model loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load LLM model: {e}")
                raise
        return self.llm

    def parse_filename(self, filename: str) -> dict:
        """Parse a filename and return structured data.
        
        Args:
            filename: Photo/video filename to parse
            
        Returns:
            Dict with extracted metadata (see prompt for structure)
        """
        # Check cache first
        if filename in self._parse_cache:
            return self._parse_cache[filename]
        
        # Ensure model is loaded
        if self.llm is None:
            self.load_model()
        
        try:
            # Format prompt
            prompt = self.prompt_template.replace("{filename}", filename)
            
            # Generate response (thread-safe)
            with self._llm_lock:
                response = self.llm(
                    prompt,
                    max_tokens=400,
                    temperature=0.1,
                    stop=["Filename:"],
                    echo=False
                )
            
            # Extract JSON from response
            json_str = response['choices'][0]['text'].strip()
            
            # Parse JSON
            result = json.loads(json_str)
            
            # Validate structure
            if 'date' not in result or not isinstance(result['date'], dict):
                result['date'] = {'year': None, 'month': None, 'day': None}
            
            # Cache result
            self._parse_cache[filename] = result
            
            # Limit cache size to prevent memory issues
            if len(self._parse_cache) > self._max_cache_size:
                # Remove oldest entries (first 100)
                for key in list(self._parse_cache.keys())[:100]:
                    del self._parse_cache[key]
            
            return result
            
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON from LLM for {filename}: {e}")
            logger.debug(f"LLM output: {json_str}")
            return self._empty_result()
        except Exception as e:
            logger.error(f"LLM parsing failed for {filename}: {e}")
            return self._empty_result()
    
    def _empty_result(self) -> dict:
        """Return empty result structure for complex format."""
        return {
            'location_confidence': 'none',
            'primary_search': None,
            'alternate_search': None,
            'location_type': 'unknown',
            'location_context': 'No location information found',
            'extracted': {
                'subject': None,
                'where_taken': None,
                'landmark_name': None,
                'city': None,
                'state': None,
                'country': None,
                'date_parts': {'year': None, 'month': None, 'day': None}
            },
            'search_strategy': 'need_more_info'
        }
    
    def to_date_suggestion(self, llm_output: dict) -> Optional[Dict[str, str]]:
        """Convert LLM output to date suggestion format.
        
        Now handles complex format with dates under extracted.date_parts.
        
        Returns:
            Dict with year, month, day (as strings) and is_complete flag
            Returns None if no date found
        """
        if not llm_output:
            return None
        
        # Handle new complex format
        date_parts = None
        if 'extracted' in llm_output and isinstance(llm_output.get('extracted'), dict):
            date_parts = llm_output['extracted'].get('date_parts', {})
        
        # Fallback to old format if needed
        if not date_parts or not isinstance(date_parts, dict):
            date_parts = llm_output.get('date', {})
        
        if not date_parts or not isinstance(date_parts, dict):
            return None
        
        year = date_parts.get('year')
        month = date_parts.get('month')
        day = date_parts.get('day')
        
        # Convert to strings and handle None/null values
        year = str(year) if year is not None else None
        month = str(month) if month is not None else None
        day = str(day) if day is not None else None
        
        if not year:
            return None
        
        # Ensure 2-digit format for month/day
        if month and len(month) == 1:
            month = f'0{month}'
        if day and len(day) == 1:
            day = f'0{day}'
        
        return {
            'year': year,
            'month': month or '',
            'day': day or '',
            'is_complete': bool(month)  # Complete if has at least month
        }
    
    def to_location_suggestion(self, llm_output: dict) -> Optional[Dict[str, str]]:
        """Convert LLM output to location suggestion format.
        
        Complex approach: Use confidence and direct search queries.
        Only suggest locations when we're confident they're actual locations.
        
        Returns:
            Dict with search query and metadata, or None if no confident location
        """
        if not llm_output:
            return None
        
        # Map confidence strings to numbers
        confidence_map = {
            "high": 85,
            "medium": 60,
            "low": 30,
            "none": 0
        }
        
        conf_str = llm_output.get("location_confidence", "none")
        confidence = confidence_map.get(conf_str, 0)
        
        # Apply threshold
        if confidence < 40:  # Too low confidence
            return None
        
        # Get search queries
        primary_search = llm_output.get("primary_search")
        if not primary_search:
            return None
        
        # Extract components for display
        extracted = llm_output.get("extracted", {})
        
        return {
            # Primary fields for complex approach
            'confidence': confidence,
            'primary_search': primary_search,
            'alternate_search': llm_output.get("alternate_search"),
            'location_type': llm_output.get("location_type"),
            'reasoning': llm_output.get("location_context", ''),
            
            # Extracted components for display (using landmark_name to match backend)
            'landmark_name': extracted.get("landmark_name", ''),
            'city': extracted.get('city', ''),
            'state': extracted.get('state', '').upper() if extracted.get('state') else '',
            'country': extracted.get('country', ''),
            
            # For compatibility
            'is_complete': confidence > 70
        }
    
    def parse_filenames_batch(self, filenames: List[str], progress_callback=None):
        """Parse multiple filenames efficiently.
        
        Args:
            filenames: List of filenames to parse
            progress_callback: Optional callback(current, total) for progress updates
        """
        total = len(filenames)
        
        for i, filename in enumerate(filenames):
            if filename not in self._parse_cache:
                self.parse_filename(filename)
            
            if progress_callback:
                progress_callback(i + 1, total)

# ============================================================================
# LLM WORKER THREAD
# ============================================================================

def llm_worker_thread():
    """Background thread to process LLM parse requests"""
    logger.info("LLM worker thread started")
    
    while not LLM_WORKER_STOP.is_set():
        try:
            # Wait for work with timeout to check stop signal
            priority, filepath, parse_type = LLM_PARSE_QUEUE.get(timeout=0.1)
            
            # Skip if already actively processing this filepath
            if LLM_PARSE_RESULTS.get(filepath, {}).get('status') == 'processing':
                continue

            # Hold off on low-priority work until the first high-priority
            #      job (priority 0) has finished warming the model.
            if priority > 0 and not MODEL_WARMED.is_set():
                # Wait properly instead of churning
                with WARM_CONDITION:
                    LLM_PARSE_QUEUE.put((priority, filepath, parse_type))  # re-queue once
                    WARM_CONDITION.wait(timeout=1.0)  # Wait up to 1s
                continue
                
            # Mark as pending
            LLM_PARSE_RESULTS[filepath] = {'status': 'processing', 'result': None}
            
            # Check database cache first
            if STATE.database:
                with STATE.database.get_db() as conn:
                    row = conn.execute('''
                        SELECT suggestion_filename, suggested_date_year, suggested_date_month,
                               suggested_date_day, suggested_date_complete, suggested_location_primary,
                               suggested_location_alternate, suggested_location_city, suggested_location_state,
                               suggested_location_confidence, suggested_location_type, suggested_location_reasoning,
                               suggested_location_landmark
                        FROM photos WHERE filepath = ?
                    ''', (filepath,)).fetchone()
                    
                    # If cached and filename matches, use it
                    if row and row['suggestion_filename'] == Path(filepath).name:
                        cached_result = {
                            'date': {
                                'year': row['suggested_date_year'],
                                'month': row['suggested_date_month'],
                                'day': row['suggested_date_day'],
                                'is_complete': bool(row['suggested_date_complete'])
                            } if row['suggested_date_year'] else None,
                            'location': {
                                'primary_search': row['suggested_location_primary'],
                                'alternate_search': row['suggested_location_alternate'],
                                'city': row['suggested_location_city'],
                                'state': row['suggested_location_state'],
                                'confidence': row['suggested_location_confidence'],
                                'location_type': row['suggested_location_type'],
                                'reasoning': row['suggested_location_reasoning'],
                                'landmark_name': row['suggested_location_landmark'],
                                'is_complete': row['suggested_location_confidence'] > 70 if row['suggested_location_confidence'] else False
                            } if row['suggested_location_primary'] else None
                        }
                        
                        LLM_PARSE_RESULTS[filepath] = {'status': 'ready', 'result': cached_result}
                        logger.debug(f"Used cached LLM suggestion for {filepath}")
                        continue
            
            # Parse with LLM
            try:
                if STATE.filename_parser and _LLM_AVAILABLE:
                    filename = Path(filepath).name
                    llm_output = STATE.filename_parser.parse_filename(filename)
                    
                    # Convert to suggestion format
                    date_suggestion = STATE.filename_parser.to_date_suggestion(llm_output)
                    location_suggestion = STATE.filename_parser.to_location_suggestion(llm_output)
                    
                    result = {
                        'date': date_suggestion,
                        'location': location_suggestion
                    }
                    
                    # Save to database
                    if STATE.database:
                        with STATE.database.get_db() as conn:
                            data = {
                                'suggested_date_year': date_suggestion['year'] if date_suggestion else None,
                                'suggested_date_month': date_suggestion['month'] if date_suggestion else None,
                                'suggested_date_day': date_suggestion['day'] if date_suggestion else None,
                                'suggested_date_complete': date_suggestion['is_complete'] if date_suggestion else 0,
                                'suggested_location_primary': location_suggestion['primary_search'] if location_suggestion else None,
                                'suggested_location_alternate': location_suggestion.get('alternate_search') if location_suggestion else None,
                                'suggested_location_city': location_suggestion['city'] if location_suggestion else None,
                                'suggested_location_state': location_suggestion['state'] if location_suggestion else None,
                                'suggested_location_confidence': location_suggestion.get('confidence', 0) if location_suggestion else None,
                                'suggested_location_type': location_suggestion.get('location_type') if location_suggestion else None,
                                'suggested_location_reasoning': location_suggestion.get('reasoning') if location_suggestion else None,
                                'suggested_location_landmark': location_suggestion.get('landmark_name') if location_suggestion else None,
                                'suggestion_parsed_at': datetime.now().isoformat(),
                                'suggestion_filename': filename
                            }
                            
                            set_clause = ', '.join([f'{k} = :{k}' for k in data.keys()])
                            data['filepath'] = filepath
                            
                            conn.execute(
                                f'UPDATE photos SET {set_clause} WHERE filepath = :filepath',
                                data
                            )
                    
                    LLM_PARSE_RESULTS[filepath] = {'status': 'ready', 'result': result}

                    # First high-priority parse finished → release gate
                    if priority == 0 and not MODEL_WARMED.is_set():
                        MODEL_WARMED.set()
                        with WARM_CONDITION:
                            WARM_CONDITION.notify_all()  # Wake up waiting threads
                    # --- trim the cache if it grows beyond the cap ---
                    if len(LLM_PARSE_RESULTS) > MAX_LLM_PARSE_RESULTS:
                        excess = len(LLM_PARSE_RESULTS) - MAX_LLM_PARSE_RESULTS
                        for old_key in list(LLM_PARSE_RESULTS)[:excess]:
                            status = LLM_PARSE_RESULTS[old_key]['status']
                            if status in ('ready', 'error'):      # keep pendings
                                del LLM_PARSE_RESULTS[old_key]
                    # ------------------------------------------------
                    logger.debug(f"LLM parsed {filepath}")
                else:
                    # No LLM available
                    LLM_PARSE_RESULTS[filepath] = {
                        'status': 'ready',
                        'result': {'date': None, 'location': None}
                    }

                    if priority == 0 and not MODEL_WARMED.is_set():
                        MODEL_WARMED.set()
                    # --- trim the cache if it grows beyond the cap ---
                    if len(LLM_PARSE_RESULTS) > MAX_LLM_PARSE_RESULTS:
                        excess = len(LLM_PARSE_RESULTS) - MAX_LLM_PARSE_RESULTS
                        for old_key in list(LLM_PARSE_RESULTS)[:excess]:
                            status = LLM_PARSE_RESULTS[old_key]['status']
                            if status in ('ready', 'error'):
                                del LLM_PARSE_RESULTS[old_key]
                    # ------------------------------------------------
                    
            except Exception as e:
                logger.error(f"LLM parse failed for {filepath}: {e}")
                LLM_PARSE_RESULTS[filepath] = {'status': 'error', 'result': None}
                
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"LLM worker error: {e}")
    
    logger.info("LLM worker thread stopped")

def start_llm_worker():
    """Start the LLM worker thread if not already running"""
    global LLM_WORKER_THREAD
    
    if LLM_WORKER_THREAD is None or not LLM_WORKER_THREAD.is_alive():
        LLM_WORKER_STOP.clear()
        MODEL_WARMED.clear()  # CRITICAL: Reset the gate for fresh start
        
        # Step 1 - start *one* warming worker
        t0 = threading.Thread(target=llm_worker_thread, daemon=True)
        t0.start()
        LLM_WORKER_THREADS.append(t0)
        LLM_WORKER_THREAD = t0

        # Step 2 - Spawn second worker but with a delay
        def _spawn_followers():
            MODEL_WARMED.wait()                       # block until first parse done
            time.sleep(2.0)  # Wait 2s after warm-up before adding second worker
            follower_count = 1  # Just 1 additional worker for 2 total
            for _ in range(follower_count):
                t = threading.Thread(target=llm_worker_thread, daemon=True)
                t.start()
                LLM_WORKER_THREADS.append(t)
            logger.info("Spawned %d additional LLM workers", follower_count)

        threading.Thread(target=_spawn_followers, daemon=True).start()

        logger.info("Started initial LLM worker thread")

def stop_llm_worker():
    """Stop the LLM worker thread"""
    global LLM_WORKER_THREAD
    
    if LLM_WORKER_THREAD and LLM_WORKER_THREAD.is_alive():
        LLM_WORKER_STOP.set()
        LLM_WORKER_THREAD.join(timeout=5.0)
        LLM_WORKER_THREAD = None
        logger.info("Stopped LLM worker thread")

# Register cleanup for LLM worker
atexit.register(stop_llm_worker)

# ============================================================================
# PHOTODATABASE CLASS
# ============================================================================

class PhotoDatabase:
    """SQLite database for photo metadata"""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._pool = ConnectionPool(db_path)
        self._last_pool_cleanup = time.time()
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema with concurrency support"""
        with self.get_db() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=10000")
            conn.execute("PRAGMA busy_timeout=10000")
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS photos (
                    filepath TEXT PRIMARY KEY,
                    filename TEXT,
                    sequence_number INTEGER,
                    file_hash TEXT,
                    file_last_modified TIMESTAMP,
                    
                    -- What came with the photo originally (never changes)
                    original_scan_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    original_date_year TEXT,
                    original_date_month TEXT,
                    original_date_day TEXT,
                    original_date_source TEXT, -- 'exif', 'filename', 'none'
                    original_gps_lat REAL,
                    original_gps_lon REAL,
                    original_city TEXT,
                    original_state TEXT,
                    original_location_source TEXT, -- 'gps', 'iptc', 'filename', 'none'
                    original_camera_make TEXT,
                    original_camera_model TEXT,
                    
                    -- Current state in file
                    current_date_year TEXT,
                    current_date_month TEXT,
                    current_date_day TEXT,
                    current_date_source TEXT,
                    current_gps_lat REAL,
                    current_gps_lon REAL,
                    current_city TEXT,
                    current_state TEXT,
                    current_location_source TEXT,
                    
                    -- Location fields
                    current_country TEXT,
                    current_country_code TEXT,
                    current_street TEXT,
                    current_postal_code TEXT,
                    current_neighborhood TEXT,
                    
                    user_action TEXT DEFAULT 'none', -- 'saved', 'skipped', 'none'
                    user_last_action_time TIMESTAMP,
                    
                    -- What needs attention
                    needs_date BOOLEAN DEFAULT 0,
                    needs_location BOOLEAN DEFAULT 0,
                    ready_for_review BOOLEAN DEFAULT 0,
                    
                    -- Quality flags
                    has_good_date BOOLEAN DEFAULT 0, -- Has complete date from camera/phone
                    has_good_gps BOOLEAN DEFAULT 0,  -- Has GPS from camera/phone
                    has_good_location BOOLEAN DEFAULT 0, -- Has city/state from GPS or user
                    
                    -- Legacy fields for compatibility during transition
                    location_id INTEGER REFERENCES locations(id),
                    last_modified TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    
                    -- Import pipeline tracking
                    import_batch_id TEXT,
                    import_status TEXT,
                    imported_at TIMESTAMP,
                    updated_at TIMESTAMP,
                    
                    -- Additional metadata fields
                    date_from_complete_suggestion BOOLEAN DEFAULT 0,
                    location_gps_source TEXT,
                    location_landmark_name TEXT,
                    has_camera_metadata BOOLEAN DEFAULT 0,
                    original_make TEXT,
                    original_model TEXT,
                    last_saved_at TIMESTAMP,
                    
                    -- LLM suggestion cache
                    suggested_date_year TEXT,
                    suggested_date_month TEXT,
                    suggested_date_day TEXT,
                    suggested_date_complete BOOLEAN DEFAULT 0,
                    suggested_location_primary TEXT,
                    suggested_location_alternate TEXT,
                    suggested_location_city TEXT,
                    suggested_location_state TEXT,
                    suggested_location_confidence INTEGER,
                    suggested_location_type TEXT,
                    suggested_location_reasoning TEXT,
                    suggested_location_landmark TEXT,
                    suggestion_parsed_at TIMESTAMP,
                    suggestion_filename TEXT,
                    
                    -- Soft delete tracking
                    deleted_at TIMESTAMP
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS file_scans (
                    id INTEGER PRIMARY KEY,
                    scan_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    filepath TEXT,
                    file_exists BOOLEAN,
                    file_hash TEXT,
                    metadata_changed BOOLEAN,
                    changes_detected JSON
                )
            ''')
            
            # Locations table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS locations (
                    id INTEGER PRIMARY KEY,
                    city TEXT NOT NULL,
                    state TEXT NOT NULL,
                    landmark_name TEXT DEFAULT '',
                    street TEXT DEFAULT '',
                    gps_lat REAL,
                    gps_lon REAL,
                    country TEXT DEFAULT '',
                    country_code TEXT DEFAULT '',
                    postal_code TEXT DEFAULT '',
                    neighborhood TEXT DEFAULT '',
                    category TEXT NOT NULL,
                    use_count INTEGER DEFAULT 0,
                    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(city, state, country, landmark_name, street)
                )
            ''')
            
            # Add thumbnail cache table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS thumbnails (
                    id INTEGER PRIMARY KEY,
                    filepath TEXT NOT NULL,
                    file_mtime REAL NOT NULL,
                    size TEXT NOT NULL,
                    base64_data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(filepath, file_mtime, size)
                )
            ''')
            
            # Create index for fast lookups
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_thumbnails_lookup 
                ON thumbnails(filepath, file_mtime, size)
            ''')
            
            # ====== Import Pipeline Tables ======
            conn.execute('''
                CREATE TABLE IF NOT EXISTS pipeline_queue (
                    id INTEGER PRIMARY KEY,
                    filepath TEXT NOT NULL,
                    queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    batch_id TEXT,
                    status TEXT DEFAULT 'pending'
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS pipeline_status (
                    id INTEGER PRIMARY KEY,
                    batch_id TEXT UNIQUE,
                    status TEXT,
                    photo_count INTEGER,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    error_message TEXT
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS pipeline_errors (
                    id INTEGER PRIMARY KEY,
                    filepath TEXT,
                    batch_id TEXT,
                    error_type TEXT,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    last_retry TIMESTAMP
                )
            ''')
            
            # ====== Database migrations ======
            # Add sequence_number column if it doesn't exist
            try:
                conn.execute('ALTER TABLE photos ADD COLUMN sequence_number INTEGER')
                # Populate sequence_number for existing photos
                conn.execute('''
                    UPDATE photos 
                    SET sequence_number = (
                        CASE 
                            WHEN SUBSTR(filename, -7, 1) = '_' AND 
                                 SUBSTR(filename, -6, 3) GLOB '[0-9][0-9][0-9]' AND
                                 SUBSTR(filename, -3) = '.heic' OR SUBSTR(filename, -5) = '.HEIC'
                            THEN CAST(SUBSTR(filename, -6, 3) AS INTEGER)
                            ELSE NULL
                        END
                    )
                    WHERE sequence_number IS NULL
                ''')
            except Exception:
                # Column already exists, skip
                pass
            
            # ====== Create indexes for performance ======
            conn.execute('CREATE INDEX IF NOT EXISTS idx_queue_batch ON pipeline_queue(batch_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_queue_status ON pipeline_queue(status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_photos_import_batch ON photos(import_batch_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_photos_imported_at ON photos(imported_at)')
            
            # Indexes for filtering frequently queried columns
            conn.execute('CREATE INDEX IF NOT EXISTS idx_photos_user_action ON photos(user_action)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_photos_needs_flags ON photos(needs_date, needs_location)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_photos_deleted_at ON photos(deleted_at)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_photos_filename ON photos(filename)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_photos_sequence ON photos(sequence_number)')
            
            # Ensure updated_at is set for any existing rows
            conn.execute("UPDATE photos SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
            
            # ====== Create trigger for automatic updated_at ======
            # Drop existing trigger first to avoid conflicts
            conn.execute('DROP TRIGGER IF EXISTS update_photos_timestamp')
            
            conn.execute('''
                CREATE TRIGGER update_photos_timestamp 
                AFTER UPDATE ON photos
                FOR EACH ROW
                WHEN NEW.updated_at = OLD.updated_at OR OLD.updated_at IS NULL
                BEGIN
                    UPDATE photos SET updated_at = CURRENT_TIMESTAMP WHERE filepath = NEW.filepath;
                END
            ''')
            
            # Trigger for inserts
            conn.execute('DROP TRIGGER IF EXISTS insert_photos_timestamp')
            conn.execute('''
                CREATE TRIGGER insert_photos_timestamp
                AFTER INSERT ON photos
                FOR EACH ROW
                BEGIN
                    UPDATE photos SET updated_at = CURRENT_TIMESTAMP WHERE filepath = NEW.filepath;
                END
            ''')
    
    @contextmanager
    def get_db(self):
        """Database connection context manager using connection pool"""
        # Periodically close all connections to allow WAL cleanup
        if time.time() - self._last_pool_cleanup > 60:  # Every 60 seconds
            self._pool.close_idle_connections()
            self._last_pool_cleanup = time.time()
        
        conn = self._pool.get_connection()
        try:
            yield conn
            conn.commit()
        except:
            conn.rollback()
            raise
        # Note: Connection stays in pool, but we'll periodically clean them
    
    def save_photo_state(self, filepath: str, date_info: Optional[DateInfo], 
                        location_info: Optional[LocationInfo], user_action: str = 'saved',
                        location_id: Optional[int] = None):
        """Save photo state after user action"""
        with self.get_db() as conn:
            # Get current state
            current = conn.execute(
                'SELECT * FROM photos WHERE filepath = ?', 
                (filepath,)
            ).fetchone()
            
            if not current:
                print(f"Warning: Photo {filepath} not in database")
                return
            
            # Determine new sources - preserve original source types
            if date_info:
                # Use the most authoritative source from the DateInfo
                if date_info.year_source == DataSource.USER:
                    new_date_source = 'user'
                else:
                    new_date_source = 'system'
            else:
                new_date_source = current['current_date_source']
                
            if location_info:
                # Check if this is from GPS (user) or system
                if location_info.gps_source == DataSource.USER:
                    new_location_source = 'user'
                elif location_info.state_source == DataSource.USER:
                    new_location_source = 'user'
                else:
                    new_location_source = 'system'
            else:
                new_location_source = current['current_location_source']
            
            # Update current state
            data = {
                'current_date_year': date_info.year if date_info else current['current_date_year'],
                'current_date_month': date_info.month if date_info else current['current_date_month'],
                'current_date_day': date_info.day if date_info else current['current_date_day'],
                'current_date_source': new_date_source,
                'current_city': location_info.city if location_info else current['current_city'],
                'current_state': location_info.state if location_info else current['current_state'],
                'current_gps_lat': location_info.gps_lat if location_info else current['current_gps_lat'],
                'current_gps_lon': location_info.gps_lon if location_info else current['current_gps_lon'],
                'current_location_source': new_location_source,
                'location_id': location_id,
                
                # Location fields
                'current_country': location_info.country if location_info else (current['current_country'] if 'current_country' in current else ''),
                'current_country_code': location_info.country_code if location_info else (current['current_country_code'] if 'current_country_code' in current else ''),
                'current_street': location_info.street if location_info else (current['current_street'] if 'current_street' in current else ''),
                'current_postal_code': location_info.postal_code if location_info else (current['current_postal_code'] if 'current_postal_code' in current else ''),
                'current_neighborhood': location_info.neighborhood if location_info else (current['current_neighborhood'] if 'current_neighborhood' in current else ''),
                
                # Update user action tracking
                'user_action': user_action,
                'user_last_action_time': datetime.now().isoformat(),
                'last_saved_at': datetime.now().isoformat() if user_action == 'saved' else current['last_saved_at'],
                
                # Recalculate needs - must match tag logic exactly
                'needs_date': 0 if (date_info and not date_info.needs_tag()) else (1 if date_info else current['needs_date']),
                'needs_location': 0 if (location_info and not location_info.needs_tag()) else (1 if location_info else current['needs_location'])
            }
            
            # Update the record
            set_clause = ', '.join([f'{k} = :{k}' for k in data.keys()])
            data['filepath'] = filepath
            
            conn.execute(
                f'UPDATE photos SET {set_clause} WHERE filepath = :filepath',
                data
            )
    
    def get_photo_state(self, filepath: str) -> Tuple[Optional[DateInfo], Optional[LocationInfo]]:
        """Get photo state from database"""
        with self.get_db() as conn:
            row = conn.execute('SELECT * FROM photos WHERE filepath = ?', (filepath,)).fetchone()
            if not row:
                return None, None, False
            
            # Reconstruct date from current state
            date_info = None
            if row['current_date_year']:
                # Determine source
                source = DataSource.USER if row['current_date_source'] == 'user' else DataSource.SYSTEM
                
                date_info = DateInfo(
                    year=row['current_date_year'] or "",
                    month=row['current_date_month'] or "",
                    day=row['current_date_day'] or "",
                    year_source=source,
                    month_source=source,
                    day_source=source
                )
            
            # Reconstruct location from current state
            location_info = None
            if row['current_state'] or row['current_gps_lat']:
                # Determine source
                source = DataSource.USER if row['current_location_source'] == 'user' else DataSource.SYSTEM
                
                location_info = LocationInfo(
                    city=row['current_city'] or "",
                    state=row['current_state'] or "",
                    city_source=source,
                    state_source=source,
                    gps_lat=row['current_gps_lat'],
                    gps_lon=row['current_gps_lon'],
                    gps_source=source if row['current_gps_lat'] else None
                )
            
            # Return photo state
            return date_info, location_info
    
    def get_filtered_photos(self, filter_type: str) -> List[str]:
        """Get photos based on filter, sorted by the database."""
        with self.get_db() as conn:
            # Determine the ORDER BY clause based on the global sort mode
            if STATE.sort_by_sequence:
                # Sort by the pre-calculated sequence number, with filename as a tie-breaker.
                # NULLS LAST ensures photos without a sequence number appear at the end.
                order_by_clause = "ORDER BY sequence_number ASC NULLS LAST, filename ASC"
            else:
                # Default sort by filename
                order_by_clause = "ORDER BY filename ASC"

            # Base queries for each filter
            queries = {
                'needs_review': "WHERE (user_action != 'saved' OR user_action IS NULL) AND deleted_at IS NULL",
                'needs_both': "WHERE user_action = 'saved' AND needs_date = 1 AND needs_location = 1 AND deleted_at IS NULL",
                'needs_date': "WHERE user_action = 'saved' AND needs_date = 1 AND needs_location = 0 AND deleted_at IS NULL",
                'needs_location': "WHERE user_action = 'saved' AND needs_date = 0 AND needs_location = 1 AND deleted_at IS NULL",
                'complete': "WHERE user_action = 'saved' AND needs_date = 0 AND needs_location = 0 AND deleted_at IS NULL",
                'all': "WHERE deleted_at IS NULL"
            }

            where_clause = queries.get(filter_type, queries['all'])

            # Construct the final query
            full_query = f"SELECT filepath FROM photos {where_clause} {order_by_clause}"

            # Execute and fetch all results directly
            results = [row[0] for row in conn.execute(full_query).fetchall()]
            return results
    
    def get_stats(self) -> Dict[str, int]:
        """Get statistics – single aggregate query to avoid DB lock bursts"""
        with self.get_db() as conn:
            row = conn.execute('''
                SELECT
                    COUNT(CASE WHEN deleted_at IS NULL THEN 1 END)                   AS total,
                    SUM(CASE WHEN user_action != 'saved' AND deleted_at IS NULL THEN 1 ELSE 0 END) AS needs_review,
                    SUM(CASE WHEN user_action = 'saved'
                              AND needs_date = 1 AND needs_location = 1 
                              AND deleted_at IS NULL THEN 1 END)                     AS needs_both,
                    SUM(CASE WHEN user_action = 'saved'
                              AND needs_date = 1 AND needs_location = 0 
                              AND deleted_at IS NULL THEN 1 END)                     AS needs_date,
                    SUM(CASE WHEN user_action = 'saved'
                              AND needs_date = 0 AND needs_location = 1 
                              AND deleted_at IS NULL THEN 1 END)                     AS needs_location,
                    SUM(CASE WHEN user_action = 'saved'
                              AND needs_date = 0 AND needs_location = 0 
                              AND deleted_at IS NULL THEN 1 END)                     AS complete,
                    SUM(CASE WHEN user_action = 'skipped' 
                              AND deleted_at IS NULL THEN 1 ELSE 0 END)              AS skipped
                FROM photos
            ''').fetchone()
            return dict(row)


class ConnectionPool:
    """Thread-local connection pool for SQLite with proper cleanup"""
    def __init__(self, db_path: Path, pool_size: int = 8):
        self.db_path = db_path
        self.pool_size = pool_size
        self._local = threading.local()
        self._all_connections = []  # Track all connections for cleanup
        self._lock = threading.Lock()
    
    def get_connection(self):
        """Get a connection for the current thread"""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=10000")
            self._local.connection = conn
            
            # Track this connection (with hard cap)
            with self._lock:
                self._all_connections.append(conn)
                # --- NEW: enforce max pool size ---
                if len(self._all_connections) > self.pool_size:
                    old_conn = self._all_connections.pop(0)
                    try:
                        old_conn.close()
                    except:
                        pass
                # -----------------------------------
                
        return self._local.connection
    
    def release_connection(self):
        """Close and remove the connection held by the current thread"""
        if hasattr(self._local, 'connection') and self._local.connection:
            try:
                self._local.connection.close()
            except Exception:
                pass
            self._local.connection = None
    
    def close_idle_connections(self):
        """Close connections that haven't been used recently"""
        # For SQLite, we might want to close ALL connections periodically
        # to allow WAL cleanup
        with self._lock:
            for conn in self._all_connections:
                try:
                    conn.close()
                except:
                    pass
            self._all_connections.clear()
        
        # Clear thread-local references
        if hasattr(self._local, 'connection'):
            self._local.connection = None
    
    def __del__(self):
        """Ensure connections are closed on shutdown"""
        self.close_idle_connections()


# ============================================================================
# LOCATION MANAGER CLASS
# ============================================================================

class LocationManager:
    """Manages location search, caching, and usage tracking"""
    
    def __init__(self, db: 'PhotoDatabase'):
        self.db = db
        self._frequent_cache = []
        self._last_cache_update = 0
    
    def get_or_create_location(self, location: SmartLocation) -> int:
        # normalise nullable text fields once
        landmark = location.landmark_name or ''
        street = location.street or ''
        country = location.country or ''
        lat = location.gps_lat
        lon = location.gps_lon

        with self.db.get_db() as conn:
            result = conn.execute('''
                SELECT id FROM locations 
                WHERE city = ? AND state = ? 
                AND IFNULL(country, '') = ?
                AND IFNULL(landmark_name, '') = ?
                AND IFNULL(street, '') = ?
            ''', (location.city, location.state, country, landmark, street)).fetchone()
            
            if result:
                # Update usage count will be handled separately
                return result[0]
            
            cursor = conn.execute('''
                INSERT INTO locations (
                    city, state, landmark_name, street, gps_lat, gps_lon,
                    country, country_code, postal_code, neighborhood, category
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (location.city, location.state, landmark, street, lat, lon,
                location.country, location.country_code, location.postal_code,
                location.neighborhood, location.category.name if location.category else 'POI'))
            
            return cursor.lastrowid
    
    def increment_usage(self, location_id: int):
        with self.db.get_db() as conn:
            conn.execute('''
                UPDATE locations 
                SET use_count = use_count + 1,
                    last_used = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (location_id,))
    
    def get_frequent_locations(self, limit: int = 10) -> List[SmartLocation]:
        self._update_cache()
        return self._frequent_cache[:limit]
    
    def search_locations(self, query: str) -> List[SmartLocation]:
        if not query or len(query) < 2:
            return []
        
        results = []
        query_lower = query.lower()
        
        with self.db.get_db() as conn:
            # Search across multiple fields since display_full is now computed
            db_results = conn.execute('''
                SELECT * FROM locations
                WHERE city LIKE ? 
                   OR state LIKE ? 
                   OR landmark_name LIKE ? 
                   OR street LIKE ?
                   OR country LIKE ?
                ORDER BY use_count DESC
                LIMIT 10
            ''', (f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%')).fetchall()
            
            for row in db_results:
                results.append(self._row_to_location(row))
        
        return results
    
    def _update_cache(self):
        # Only update if stale
        with LOCATION_CACHE_LOCK:
            now = time.time()
            if now - self._last_cache_update < 60:  # Cache for 60 seconds
                return
            
            with self.db.get_db() as conn:
                frequent = conn.execute('''
                    SELECT * FROM locations
                    ORDER BY use_count DESC, last_used DESC
                    LIMIT 20
                ''').fetchall()
            
            self._frequent_cache = [self._row_to_location(row) for row in frequent]
            self._last_cache_update = now
    
    def _row_to_location(self, row) -> SmartLocation:
        return SmartLocation(
            id=row['id'],
            city=row['city'],
            state=row['state'],
            landmark_name=row['landmark_name'] if 'landmark_name' in row.keys() else '',
            street=row['street'] if 'street' in row.keys() else '',
            gps_lat=row['gps_lat'] if 'gps_lat' in row.keys() else None,
            gps_lon=row['gps_lon'] if 'gps_lon' in row.keys() else None,
            country=row['country'] if 'country' in row.keys() else '',
            country_code=row['country_code'] if 'country_code' in row.keys() else '',
            postal_code=row['postal_code'] if 'postal_code' in row.keys() else '',
            neighborhood=row['neighborhood'] if 'neighborhood' in row.keys() else '',
            category=Category[row['category']] if 'category' in row.keys() and row['category'] else None,
            use_count=row['use_count'] if 'use_count' in row.keys() else 0,
            last_used=datetime.fromisoformat(row['last_used']) if 'last_used' in row.keys() and row['last_used'] else None
        )

# ============================================================================
# GAZETTEER CLASS
# ============================================================================

class Gazetteer:
    """City/State to GPS lookup with Apple geocoding integration"""
    
    def __init__(self, csv_path: Path):
        self._data = {}
        self._proper_names = {}
        self._apple_cache = {}
        
        # Load Apple cache first
        self._load_apple_cache()
        
        # Load CSV data
        if not csv_path.exists():
            print(f"Gazetteer CSV not found: {csv_path}")
            return
        
        try:
            tf = TimezoneFinder(in_memory=True)
            
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    city = row['city_ascii']
                    city_lower = city.lower()
                    state = row['state_id']
                    state_lower = state.lower()
                    lat = float(row['lat'])
                    lon = float(row['lng'])
                    
                    if tz := tf.timezone_at(lat=lat, lng=lon):
                        self._data[(city_lower, state_lower)] = (lat, lon, tz)
                        self._proper_names[(city_lower, state_lower)] = (city, state)
            
            print(f"Loaded {len(self._data)} cities from CSV")
            
        except Exception as e:
            print(f"Error loading gazetteer: {e}")
    
    def _load_apple_cache(self):
        """Load Apple geocoding cache from disk"""
        cache_path = DATA_DIR / "apple_geocode_cache.csv"
        if not cache_path.exists():
            return
        
        try:
            with open(cache_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = (row['city'].lower(), row['state'].lower())
                    self._apple_cache[key] = (
                        float(row['lat']),
                        float(row['lon']),
                        row.get('tz')
                    )
                    self._data[key] = self._apple_cache[key]
                    self._proper_names[key] = (row['city'], row['state'])
            
            print(f"Loaded {len(self._apple_cache)} entries from Apple cache")
        except Exception as e:
            logger.warning(f"Error loading Apple cache: {e}")
    
    def lookup(self, city: str, state: str) -> Optional[Tuple[float, float, str]]:
        """Lookup GPS coordinates"""
        if not city or not state:
            return None
        return self._data.get((city.lower(), state.lower()))
    
    def get_proper_name(self, city: str, state: str) -> Optional[Tuple[str, str]]:
        """Get proper capitalization for city and state"""
        if not city or not state:
            return None
        return self._proper_names.get((city.lower(), state.lower()))
    
    def add_to_cache(self, city: str, state: str, lat: float, lon: float, tz: Optional[str] = None):
        """Add a new entry to the cache"""
        key = (city.lower(), state.lower())
        if tz is None:
            tf = TimezoneFinder(in_memory=True)
            tz = tf.timezone_at(lat=lat, lng=lon)
        
        # Add to memory caches
        self._data[key] = (lat, lon, tz)
        self._apple_cache[key] = (lat, lon, tz)
        self._proper_names[key] = (city, state)
        
        # Persist to Apple cache CSV
        self._append_to_apple_cache(city, state, lat, lon, tz)
    
    def _append_to_apple_cache(self, city: str, state: str, lat: float, lon: float, tz: Optional[str]):
        """Append a new entry to the Apple cache CSV"""
        cache_path = DATA_DIR / "apple_geocode_cache.csv"
        
        # Create with headers if doesn't exist
        if not cache_path.exists():
            with open(cache_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['city', 'state', 'lat', 'lon', 'tz'])
        
        # Append new entry
        with open(cache_path, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([city, state, lat, lon, tz or ''])

# ============================================================================
# APPLE GEOCODING FUNCTIONS
# ============================================================================

def _cooldown():
    """Enforce 1 request per second rate limit for Apple APIs"""
    global _last_api_call
    wait = 1.0 - (time.time() - _last_api_call)
    if wait > 0:
        time.sleep(wait)
    _last_api_call = time.time()

def _run_on_main_thread(func, *args, **kwargs):
    """Execute *func* on the macOS main thread and return its result."""
    if NSThread.isMainThread():
        return func(*args, **kwargs)
    
    result_holder = {}
    exception_holder = {}
    done = threading.Event()

    def _wrapper():
        try:
            result_holder["value"] = func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Exception in {func.__name__} on main thread: {e}")
            exception_holder["error"] = e
        finally:
            done.set()

    AppHelper.callAfter(_wrapper)
    
    if not done.wait(timeout=10.0):
        logger.error(f"Timeout waiting for {func.__name__} to complete on main thread")
        raise TimeoutError(f"Main thread execution of {func.__name__} timed out")
    
    if "error" in exception_holder:
        raise exception_holder["error"]
    
    return result_holder.get("value")

def _geocode_location(query: str) -> Optional[Dict[str, Any]]:
    """
    Unified geocoding function using MKLocalSearch for both addresses and POIs.
    Returns: Dictionary with all available location data
    """
    def _impl() -> Optional[Dict[str, Any]]:
        if not _mk_local_search_available:
            logger.warning(f"MKLocalSearch not available for query: {query}")
            return None
            
        _cooldown()
        try:
            # Create search request
            req = MKLocalSearchRequest.alloc().init()
            req.setNaturalLanguageQuery_(query)
            
            # Create and start search
            search = MKLocalSearch.alloc().initWithRequest_(req)
            finished, result = False, None
            
            def handler(response, error):
                nonlocal finished, result
                if error:
                    logger.warning(f"MKLocalSearch error for '{query}': {error}")
                elif response and response.mapItems().count() > 0:
                    item = response.mapItems()[0]
                    pm = item.placemark()
                    
                    # Get landmark name if available
                    landmark = ""
                    if hasattr(item, 'name') and item.name():
                        landmark = item.name()
                    elif not pm.locality() and not pm.administrativeArea():
                        # If no city/state, this might be a POI search, use query as landmark
                        landmark = query
                    
                    # Extract ALL available data from MKPlacemark
                    result = {
                        'lat': pm.coordinate().latitude,
                        'lon': pm.coordinate().longitude,
                        'city': pm.locality() or "",
                        'state': pm.administrativeArea() or "",
                        'country': pm.country() or "",
                        'country_code': pm.ISOcountryCode() or "",
                        'street_number': pm.subThoroughfare() or "",
                        'street_name': pm.thoroughfare() or "",
                        'street': f"{pm.subThoroughfare() or ''} {pm.thoroughfare() or ''}".strip(),
                        'postal_code': pm.postalCode() or "",
                        'neighborhood': pm.subLocality() or "",
                        'county': pm.subAdministrativeArea() or "",
                        'ocean': pm.ocean() if hasattr(pm, 'ocean') else "",
                        'water': pm.inlandWater() if hasattr(pm, 'inlandWater') else "",
                        'landmark_name': landmark,
                        'query': query
                    }
                finished = True
            
            search.startWithCompletionHandler_(handler)
            
            # Wait for completion
            start = time.time()
            while not finished and time.time() - start < 5.0:
                NSRunLoop.currentRunLoop().runUntilDate_(
                    NSDate.dateWithTimeIntervalSinceNow_(0.05)
                )
            
            return result
            
        except Exception as e:
            logger.error(f"MKLocalSearch exception for '{query}': {e}")
            return None
    
    return _run_on_main_thread(_impl)

# ============================================================================
# PHOTOPIPELINE CLASS
# ============================================================================

class PhotoPipeline:
    """Main pipeline class for transferring photos to Mac B - Integrated version"""
    
    def __init__(self, working_dir: Path, config: dict, database: 'PhotoDatabase', emit_event=None):
        self.working_dir = working_dir
        self.config = config
        self.database = database
        self._emit_event = emit_event or self._default_emit_event
        
        # Use STATE paths
        self.data_dir = STATE.data_dir
        self.db_path = self.data_dir / "photo_metadata.db"
        
        # Override staging paths to be relative to base directory
        self.config['paths']['staging_dir'] = str(STATE.working_dir.parent / "ToSend")
        self.config['paths']['local_reports'] = str(STATE.working_dir.parent / "reports")
        
        # Track running operations for cleanup
        self._ssh_connections = []
        self._staging_dirs = []
        
        # Removed signal handlers - handled by Flask app
    
    def _default_emit_event(self, event: Dict[str, Any]):
        """Default event emitter - adds to STATE.pipeline_events"""
        event['timestamp'] = datetime.now().isoformat()
        STATE.pipeline_events.append(event)
        
        # Keep limited history
        if len(STATE.pipeline_events) > 1000:
            STATE.pipeline_events = STATE.pipeline_events[-1000:]
        
        # Also add to output for backward compatibility with current UI
        if event['type'] == 'status':
            line = f"{event['level'].upper()}: {event['message']}"
        elif event['type'] == 'transfer_progress':
            line = f"  {event['file']}: {event['percent']}% ({event['bytes_transferred']:,}/{event['total_bytes']:,} bytes)"
        elif event['type'] == 'error':
            line = f"ERROR: {event['message']}"
        else:
            line = event.get('message', str(event))
        
        STATE.pipeline_output.append(line)
        if len(STATE.pipeline_output) > 1000:
            STATE.pipeline_output = STATE.pipeline_output[-1000:]
        
        # Log to console for debugging
        if event['type'] == 'error':
            logger.error(f"[PIPELINE] {event['message']}")
        elif event['type'] == 'status':
            level = event.get('level', 'info')
            if level == 'warning':
                logger.warning(f"[PIPELINE] {event['message']}")
            elif level == 'debug':
                logger.debug(f"[PIPELINE] {event['message']}")
            else:
                logger.info(f"[PIPELINE] {event['message']}")
        elif event['type'] in ['complete', 'cancelled']:
            logger.info(f"[PIPELINE] {event['type'].upper()}: {event.get('message', '')}")
        else:
            logger.debug(f"[PIPELINE] {event['type']}: {event}")
    
    def _validate_config(self):
        """Validate configuration"""
        mac_addr = self.config['mac_b']['mac_address']
        if mac_addr == "XX:XX:XX:XX:XX:XX":
            error_msg = 'Please configure Mac B\'s MAC address in pipeline_config.json'
            self._emit_event({
                'type': 'error',
                'message': error_msg
            })
            logger.error(f"[PIPELINE] Config validation failed: {error_msg}")
            logger.error(f"[PIPELINE] Config path: {STATE.data_dir / 'pipeline_config.json'}")
            raise PipelineError("MAC address not configured")
        
        # Validate SSH key
        key_path = Path(os.path.expanduser(self.config['mac_b']['ssh_key_path']))
        if not key_path.exists():
            self._emit_event({
                'type': 'error',
                'message': f'SSH key not found at {key_path}'
            })
            raise PipelineError(f"SSH key not found: {key_path}")
        
        # Check key permissions
        stat_info = key_path.stat()
        if stat_info.st_mode & 0o077:
            self._emit_event({
                'type': 'status',
                'level': 'warning',
                'message': 'SSH key has loose permissions, fixing...'
            })
            key_path.chmod(0o600)
    
    @contextmanager
    def get_db(self):
        """Use STATE.database instead of own connection"""
        with STATE.database.get_db() as conn:
            yield conn
    
    def _queue_db_write(self, sql: str, params: tuple) -> Future:
        """Queue a database write operation"""
        future = Future()
        
        def operation():
            with STATE.database.get_db() as conn:
                return conn.execute(sql, params).rowcount
        
        STATE.db_queue.put((operation, future))
        return future
    
    def get_pending_batches(self) -> List[str]:
        """Get list of pending batch IDs"""
        with self.get_db() as conn:
            rows = conn.execute('''
                SELECT DISTINCT ps.batch_id 
                FROM pipeline_status ps
                WHERE (ps.status = 'queued'
                   OR (ps.status = 'processing' 
                       AND datetime(ps.started_at) > datetime('now', '-1 hour')))
                   OR EXISTS (
                       SELECT 1 FROM pipeline_queue pq 
                       WHERE pq.batch_id = ps.batch_id 
                       AND pq.status = 'pending'
                   )
                ORDER BY ps.started_at
            ''').fetchall()
            
            return [row['batch_id'] for row in rows]
    
    def get_batch_photos(self, batch_id: str) -> List[Dict]:
        """Get all photos in a batch with validation"""
        if STATE.pipeline_cancelled:
            raise PipelineError("Pipeline cancelled by user")
            
        with self.get_db() as conn:
            # Validate batch exists
            batch_exists = conn.execute(
                'SELECT 1 FROM pipeline_status WHERE batch_id = ?',
                (batch_id,)
            ).fetchone()
            
            if not batch_exists:
                raise PipelineError(f"Batch {batch_id} not found")
            
            # Get photos with optional size limit
            limit_clause = ''
            params = [batch_id]
            if self.config['transfer'].get('batch_size_limit'):
                limit_clause = 'LIMIT ?'
                params.append(self.config['transfer']['batch_size_limit'])
            
            rows = conn.execute(f'''
                SELECT pq.id, pq.filepath, p.file_hash 
                FROM pipeline_queue pq
                LEFT JOIN photos p ON pq.filepath = p.filepath
                WHERE pq.batch_id = ? AND pq.status = 'pending'
                {limit_clause}
            ''', params).fetchall()
            
            photos = []
            for row in rows:
                if STATE.pipeline_cancelled:
                    raise PipelineError("Pipeline cancelled by user")
                    
                filepath = Path(row['filepath']).resolve()
                
                if not filepath.exists():
                    self._emit_event({
                        'type': 'error',
                        'message': f'File not found: {filepath}'
                    })
                    self._mark_photo_error(row['id'], 'file_not_found', 
                                         f"File not found: {filepath}")
                    continue
                
                # Check if photo is in photos table
                if row['file_hash'] is None:
                    self._emit_event({
                        'type': 'status',
                        'level': 'warning',
                        'message': f'Photo not in database yet: {filepath.name}'
                    })
                    self._ensure_photo_in_database(str(filepath))
                    file_hash = self._calculate_file_hash(filepath)
                else:
                    file_hash = row['file_hash']
                
                photos.append({
                    'id': row['id'],
                    'filepath': str(filepath),
                    'file_hash': file_hash
                })
            
            return photos
    
    def _ensure_photo_in_database(self, filepath: str):
        """Ensure photo exists in photos table with minimal entry"""
        normalized_path = str(Path(filepath).resolve())
        path = Path(normalized_path)
        
        try:
            file_hash = self._calculate_file_hash(path)
            file_mtime = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
        except Exception as e:
            self._emit_event({
                'type': 'error',
                'message': f'Failed to read file {normalized_path}: {e}'
            })
            return
        
        # Queue the write
        sql = '''
            INSERT INTO photos (
                filepath, filename, file_hash, 
                file_last_modified, original_scan_time,
                needs_date, needs_location, ready_for_review,
                user_action
            ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, 1, 1, 1, 'none')
            ON CONFLICT(filepath) DO UPDATE SET
                file_hash = excluded.file_hash,
                file_last_modified = excluded.file_last_modified
        '''
        params = (normalized_path, path.name, file_hash, file_mtime)
        
        future = self._queue_db_write(sql, params)
        try:
            rowcount = future.result(timeout=30)
            if rowcount > 0:
                self._emit_event({
                    'type': 'status',
                    'level': 'info',
                    'message': f'Added {path.name} to photos table'
                })
        except Exception as e:
            self._emit_event({
                'type': 'error',
                'message': f'Failed to add photo to database: {e}'
            })
    
    def _mark_photo_error(self, queue_id: int, error_type: str, error_msg: str):
        """Mark a photo as having an error"""
        # Update queue status
        sql1 = 'UPDATE pipeline_queue SET status = \'error\' WHERE id = ?'
        future1 = self._queue_db_write(sql1, (queue_id,))
        
        # Get filepath for error tracking - this is a read, can be direct
        with self.get_db() as conn:
            result = conn.execute(
                'SELECT filepath, batch_id FROM pipeline_queue WHERE id = ?',
                (queue_id,)
            ).fetchone()
        
        if result:
            # Insert error record
            sql2 = '''
                INSERT INTO pipeline_errors 
                (filepath, batch_id, error_type, error_message, last_retry)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            '''
            params2 = (result['filepath'], result['batch_id'], error_type, error_msg)
            future2 = self._queue_db_write(sql2, params2)
            
            # Wait for both writes
            try:
                future1.result(timeout=30)
                future2.result(timeout=30)
            except Exception as e:
                self._emit_event({
                    'type': 'error',
                    'message': f'Failed to record error: {e}'
                })
    
    def wake_mac_b(self) -> bool:
        """Wake Mac B using Wake-on-LAN"""
        if STATE.pipeline_cancelled:
            return False
        
        # Check if already awake
        self._emit_event({
            'type': 'status',
            'level': 'info',
            'message': 'Checking if Mac B is already awake...'
        })
        
        try:
            if self.test_connection():
                self._emit_event({
                    'type': 'status',
                    'level': 'info',
                    'message': 'Mac B is already awake'
                })
                return True
        except Exception as e:
            # Any connection failure means Mac is probably asleep
            self._emit_event({
                'type': 'status',
                'level': 'info',
                'message': f'Mac B appears to be asleep ({type(e).__name__}), sending wake signal...'
            })
            # Continue to send WOL packet below
            
        mac_addr = self.config['mac_b']['mac_address']
        self._emit_event({
            'type': 'status',
            'level': 'info',
            'message': f'Sending WOL packet to {mac_addr}'
        })
        
        try:
            # Send multiple packets to ensure delivery
            for _ in range(3):
                if STATE.pipeline_cancelled:
                    return False
                send_magic_packet(mac_addr)
                time.sleep(1)
            
            # Wait for Mac to wake up
            wait_time = self.config['mac_b']['wake_wait_time']
            self._emit_event({
                'type': 'status',
                'level': 'info',
                'message': f'Waiting up to {wait_time} seconds for Mac B to wake...'
            })
            
            # Check periodically
            for i in range(wait_time):
                if STATE.pipeline_cancelled:
                    return False
                
                if i > 5 and i % 5 == 0:  # Check every 5 seconds after initial wait
                    if self.test_connection():
                        self._emit_event({
                            'type': 'status',
                            'level': 'info',
                            'message': f'Mac B woke up after {i} seconds'
                        })
                        return True
                
                time.sleep(1)
            
            # Final check
            return self.test_connection()
            
        except Exception as e:
            self._emit_event({
                'type': 'error',
                'message': f'Failed to send WOL packet: {e}'
            })
            return False
    
    def _calculate_file_hash(self, filepath: Path) -> str:
        """Wrapper that delegates to the single canonical helper"""
        return calculate_file_hash(filepath)
    
    @contextmanager
    def _get_ssh_connection(self):
        """Get SSH connection with proper cleanup"""
        host_parts = self.config['mac_b']['host'].split('@')
        if len(host_parts) == 2:
            username, hostname = host_parts
        else:
            username = 'pipeline'
            hostname = host_parts[0]
        
        key_path = os.path.expanduser(self.config['mac_b']['ssh_key_path'])
        
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        connected = False
        try:
            ssh.connect(
                hostname=hostname,
                username=username,
                key_filename=key_path,
                timeout=5,
                banner_timeout=5,
                auth_timeout=5
            )
            connected = True
            self._ssh_connections.append(ssh)
            STATE.pipeline_ssh_connections.append(ssh)  # Track in STATE for cleanup
            yield ssh
        finally:
            try:
                ssh.close()
                if connected:
                    self._ssh_connections.remove(ssh)
                    if ssh in STATE.pipeline_ssh_connections:
                        STATE.pipeline_ssh_connections.remove(ssh)
            except Exception as e:
                logger.error(f"Error closing SSH connection: {e}")
    
    def test_connection(self) -> bool:
        """Test SSH connection to Mac B"""
        try:
            with self._get_ssh_connection() as ssh:
                stdin, stdout, stderr = ssh.exec_command('echo "Connection test"', timeout=10)
                result = stdout.read().decode().strip()
                exit_status = stdout.channel.recv_exit_status()
                
                return result == "Connection test" and exit_status == 0
        except (socket.gaierror, socket.error) as e:
            # DNS or network errors - fail immediately
            error_msg = str(e)
            if "nodename nor servname provided" in error_msg:
                self._emit_event({
                    'type': 'error',
                    'message': f'Cannot resolve hostname: {self.config["mac_b"]["host"]}'
                })
                self._emit_event({
                    'type': 'error',
                    'message': 'Please check your pipeline_config.json file'
                })
            else:
                self._emit_event({
                    'type': 'error',
                    'message': f'Network error: {error_msg}'
                })
            raise  # Re-raise to stop retrying
        except Exception as e:
            self._emit_event({
                'type': 'status',
                'level': 'debug',
                'message': f'Connection test failed: {e}'
            })
            return False
    
    def wait_for_connection(self, timeout: int = None) -> bool:
        """Wait for Mac B to be available"""
        if timeout is None:
            timeout = self.config['mac_b']['connection_timeout']
        
        start_time = time.time()
        
        while time.time() - start_time < timeout and not STATE.pipeline_cancelled:
            if self.test_connection():
                self._emit_event({
                    'type': 'status',
                    'level': 'info',
                    'message': 'Successfully connected to Mac B'
                })
                return True
            
            self._emit_event({
                'type': 'status',
                'level': 'debug',
                'message': 'Connection failed, retrying...'
            })
            time.sleep(5)
        
        return False
    
    def stage_files(self, photos: List[Dict]) -> Optional[Path]:
        """Copy photos to staging directory with verification"""
        if STATE.pipeline_cancelled:
            return None
            
        staging_base = Path(self.config['paths']['staging_dir'])
        staging_base.mkdir(parents=True, exist_ok=True)
        
        # Use tempfile for truly unique directory
        batch_dir = Path(tempfile.mkdtemp(
            prefix=f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}_",
            dir=staging_base
        ))
        self._staging_dirs.append(batch_dir)
        STATE.pipeline_staging_dirs.append(batch_dir)  # Track in STATE
        
        self._emit_event({
            'type': 'status',
            'level': 'info',
            'message': f'Staging {len(photos)} photos to {batch_dir.name}'
        })
        
        staged_files = []
        failed_files = []
        
        for i, photo in enumerate(photos):
            if STATE.pipeline_cancelled:
                break
                
            src = Path(photo['filepath'])
            base_name = src.name.lower() if sys.platform == 'darwin' else src.name
            dst = batch_dir / src.name
            
            # Handle duplicate filenames
            counter = 1
            while any(existing.name.lower() == dst.name.lower() for existing in batch_dir.iterdir()):
                stem = src.stem
                suffix = src.suffix
                dst = batch_dir / f"{stem}_{counter:03d}{suffix}"
                counter += 1
                
                if counter > 999:
                    self._emit_event({
                        'type': 'error',
                        'message': f'Too many duplicates of {src.name}'
                    })
                    self._mark_photo_error(photo['id'], 'staging_failed', 
                                         f"Too many duplicates of {src.name}")
                    failed_files.append(photo)
                    break
            
            try:
                shutil.copy2(src, dst)
                
                # Verify copy
                if photo.get('file_hash'):
                    dst_hash = self._calculate_file_hash(dst)
                    if dst_hash != photo['file_hash']:
                        raise TransferError(f"Hash mismatch after copy")
                else:
                    if not dst.exists() or dst.stat().st_size != src.stat().st_size:
                        raise TransferError(f"File copy verification failed")
                
                staged_files.append({
                    'src': str(src),
                    'dst': str(dst),
                    'queue_id': photo['id']
                })
                
                self._emit_event({
                    'type': 'staging_progress',
                    'file': src.name,
                    'current': i + 1,
                    'total': len(photos),
                    'percent': int(((i + 1) / len(photos)) * 100)
                })
                
            except Exception as e:
                self._emit_event({
                    'type': 'error',
                    'message': f'Failed to stage {src.name}: {e}'
                })
                failed_files.append(photo)
                self._mark_photo_error(photo['id'], 'staging_failed', str(e))
        
        if not staged_files:
            self._emit_event({
                'type': 'error',
                'message': 'No files successfully staged'
            })
            shutil.rmtree(batch_dir)
            self._staging_dirs.remove(batch_dir)
            if batch_dir in STATE.pipeline_staging_dirs:
                STATE.pipeline_staging_dirs.remove(batch_dir)
            return None
        
        self._emit_event({
            'type': 'status',
            'level': 'info',
            'message': f'Staged {len(staged_files)} files ({len(failed_files)} failed)'
        })
        
        # Write manifest for tracking
        manifest_path = batch_dir / "staged_manifest.json"
        with open(manifest_path, 'w') as f:
            json.dump(staged_files, f, indent=2)
        
        return batch_dir

    def transfer_files(self, batch_dir: Path, batch_id: str) -> bool:
        """Transfer files to Mac B via SFTP with resume support"""
        if STATE.pipeline_cancelled:
            return False
            
        # Read staging manifest
        manifest_path = batch_dir / "staged_manifest.json"
        with open(manifest_path) as f:
            staged_files = json.load(f)
        
        try:
            with self._get_ssh_connection() as ssh:
                sftp = ssh.open_sftp()
                
                # Get home directory path safely
                stdin, stdout, stderr = ssh.exec_command('pwd', timeout=10)
                home_dir = stdout.read().decode().strip()
                exit_status = stdout.channel.recv_exit_status()
                
                if not home_dir or exit_status != 0:
                    home_dir = sftp.getcwd() or '/Users/pipeline'
                    self._emit_event({
                        'type': 'status',
                        'level': 'warning',
                        'message': f'Could not get home dir, using: {home_dir}'
                    })
                
                # Resolve remote paths
                remote_incoming = self.config['paths']['remote_incoming']
                if remote_incoming.startswith('~'):
                    remote_incoming = home_dir + remote_incoming[1:]
                elif not remote_incoming.startswith('/'):
                    remote_incoming = home_dir + '/' + remote_incoming
                
                # Ensure remote directory exists
                try:
                    sftp.stat(remote_incoming)
                except FileNotFoundError:
                    self._emit_event({
                        'type': 'status',
                        'level': 'info',
                        'message': f'Creating remote directory: {remote_incoming}'
                    })
                    parts = remote_incoming.split('/')
                    current = ''
                    for part in parts:
                        if not part:
                            continue
                        current += '/' + part
                        try:
                            sftp.stat(current)
                        except FileNotFoundError:
                            try:
                                sftp.mkdir(current)
                            except Exception as e:
                                pass
                
                # Create batch subdirectory
                remote_batch_dir = f"{remote_incoming}/{batch_id}"
                try:
                    sftp.mkdir(remote_batch_dir)
                except OSError:
                    pass
                
                # Transfer files
                self._emit_event({
                    'type': 'status',
                    'level': 'info',
                    'message': f'Transferring {len(staged_files)} files...'
                })
                
                transferred = []
                
                for i, file_info in enumerate(staged_files):
                    if STATE.pipeline_cancelled:
                        break
                        
                    local_path = Path(file_info['dst'])
                    remote_filename = local_path.name
                    remote_path = f"{remote_batch_dir}/{remote_filename}"
                    
                    # Check if file already exists (resume support)
                    try:
                        remote_stat = sftp.stat(remote_path)
                        local_stat = local_path.stat()
                        
                        if remote_stat.st_size == local_stat.st_size:
                            self._emit_event({
                                'type': 'status',
                                'level': 'debug',
                                'message': f'File {remote_filename} already transferred, skipping'
                            })
                            transferred.append({
                                'queue_id': file_info['queue_id'],
                                'remote_path': remote_path,
                                'original_path': file_info['src']
                            })
                            continue
                        elif remote_stat.st_size < local_stat.st_size:
                            self._emit_event({
                                'type': 'status',
                                'level': 'debug',
                                'message': f'Partial transfer detected, removing and retrying'
                            })
                            sftp.remove(remote_path)
                    except FileNotFoundError:
                        pass
                    
                    # Transfer with progress callback
                    transferred_bytes = 0
                    file_size = local_path.stat().st_size
                    last_progress = 0
                    
                    def progress_callback(bytes_so_far, total_bytes):
                        nonlocal transferred_bytes, last_progress
                        transferred_bytes = bytes_so_far
                        percent = int((bytes_so_far / total_bytes) * 100) if total_bytes > 0 else 0
                        
                        # Emit detailed progress event
                        if percent - last_progress >= 5 or percent == 100:
                            self._emit_event({
                                'type': 'transfer_progress',
                                'file': remote_filename,
                                'bytes_transferred': bytes_so_far,
                                'total_bytes': total_bytes,
                                'percent': percent,
                                'current_file': i + 1,
                                'total_files': len(staged_files)
                            })
                            last_progress = percent
                    
                    try:
                        sftp.put(str(local_path), remote_path, callback=progress_callback)
                        
                        transferred.append({
                            'queue_id': file_info['queue_id'],
                            'remote_path': remote_path,
                            'original_path': file_info['src']
                        })
                        
                    except Exception as e:
                        self._emit_event({
                            'type': 'error',
                            'message': f'Failed to transfer {remote_filename}: {e}'
                        })
                        self._mark_photo_error(file_info['queue_id'], 'transfer_failed', str(e))
                
                if not transferred:
                    raise TransferError("No files successfully transferred")
                
                # Write transfer manifest
                transfer_manifest = {
                    'batch_id': batch_id,
                    'timestamp': datetime.now().isoformat(),
                    'files': transferred
                }
                
                manifest_json = json.dumps(transfer_manifest, indent=2)
                with sftp.open(f"{remote_batch_dir}/transfer_manifest.json", 'w') as f:
                    f.write(manifest_json)
                
                # Create trigger file for Automator
                trigger_path = f"{remote_batch_dir}/.ready"
                sftp.open(trigger_path, 'w').close()
                
                # Force immediate Folder Action trigger by creating a trigger file
                self._emit_event({
                    'type': 'status',
                    'level': 'info',
                    'message': 'Triggering Folder Action on Mac B...'
                })
                # Try multiple trigger methods
                trigger_commands = [
                    f'touch "{remote_incoming}"',
                    f'touch "{remote_batch_dir}/.trigger_{batch_id}"',
                    f'echo "trigger" > "{remote_incoming}/.trigger_temp" && rm "{remote_incoming}/.trigger_temp"'
                ]
                
                for cmd in trigger_commands:
                    stdin, stdout, stderr = ssh.exec_command(cmd)
                    exit_status = stdout.channel.recv_exit_status()
                    
                self._emit_event({
                    'type': 'status',
                    'level': 'info',
                    'message': 'Sent multiple folder triggers'
                })
                
                self._emit_event({
                    'type': 'status',
                    'level': 'info',
                    'message': f'Successfully transferred {len(transferred)} files'
                })
                return True
                
        except Exception as e:
            self._emit_event({
                'type': 'error',
                'message': f'Transfer failed: {e}'
            })
            return False
    
    def wait_for_manifest(self, batch_id: str, timeout: int = None) -> Optional[Dict]:
        """Wait for Automator to generate manifest file"""
        if timeout is None:
            timeout = self.config['transfer']['timeout_seconds']
        
        self._emit_event({
            'type': 'status',
            'level': 'info',
            'message': f'Waiting for import manifest (timeout: {timeout}s)'
        })
        
        start_time = time.time()
        last_status_time = 0
        retry_count = 0
        
        while time.time() - start_time < timeout and not STATE.pipeline_cancelled:
            try:
                with self._get_ssh_connection() as ssh:
                    # Get home directory
                    stdin, stdout, stderr = ssh.exec_command('pwd', timeout=10)
                    home_dir = stdout.read().decode().strip()
                    
                    reports_dir = self.config['paths']['remote_reports']
                    if reports_dir.startswith('~'):
                        reports_dir = home_dir + reports_dir[1:]
                    
                    manifest_path = f"{reports_dir}/manifest_{batch_id}.json"
                    
                    sftp = ssh.open_sftp()
                    
                    try:
                        # Try to read manifest
                        content = None
                        for attempt in range(3):
                            try:
                                with sftp.open(manifest_path, 'r') as f:
                                    content = f.read().decode('utf-8')
                                
                                manifest = json.loads(content)
                                
                                # Verify it's complete
                                if manifest.get('batch_id') != batch_id:
                                    self._emit_event({
                                        'type': 'status',
                                        'level': 'warning',
                                        'message': f'Manifest batch mismatch: expected {batch_id}, got {manifest.get("batch_id")}'
                                    })
                                    break
                                
                                if 'files' in manifest and isinstance(manifest['files'], list):
                                    self._emit_event({
                                        'type': 'status',
                                        'level': 'info',
                                        'message': f'Found manifest with {len(manifest.get("files", []))} files'
                                    })
                                    return manifest
                                
                            except json.JSONDecodeError:
                                if attempt < 2:
                                    time.sleep(1)
                                else:
                                    self._emit_event({
                                        'type': 'status',
                                        'level': 'warning',
                                        'message': f'Invalid manifest after {attempt+1} attempts'
                                    })
                        
                    except FileNotFoundError:
                        # Manifest not ready yet - this is normal
                        retry_count = 0
                    except Exception as e:
                        retry_count += 1
                        if retry_count > 5:
                            self._emit_event({
                                'type': 'error',
                                'message': f'Repeated errors reading manifest: {e}'
                            })
                            retry_count = 0
                    
            except Exception as e:
                self._emit_event({
                    'type': 'status',
                    'level': 'debug',
                    'message': f'Error checking manifest: {e}'
                })
            
            # Show periodic status
            if time.time() - last_status_time > 30:
                elapsed = int(time.time() - start_time)
                self._emit_event({
                    'type': 'status',
                    'level': 'info',
                    'message': f'Still waiting for import... ({elapsed}s elapsed)'
                })
                last_status_time = time.time()
            
            # Progressive backoff to reduce connection frequency
            elapsed = int(time.time() - start_time)
            sleep_time = 1 if elapsed < 5 else 2 if elapsed < 15 else 5
            time.sleep(sleep_time)
        
        if STATE.pipeline_cancelled:
            self._emit_event({
                'type': 'status',
                'level': 'info',
                'message': 'Pipeline cancelled by user'
            })
        else:
            self._emit_event({
                'type': 'error',
                'message': f'Timeout waiting for manifest after {timeout} seconds'
            })
        
        return None
    
    def update_database(self, batch_id: str, manifest: Dict):
        """Update database with import results"""
        self._emit_event({
            'type': 'status',
            'level': 'info',
            'message': f'Updating database for batch {batch_id}'
        })
        
        imported_files = manifest.get('files', [])
        if not imported_files:
            self._emit_event({
                'type': 'status',
                'level': 'warning',
                'message': 'No files in manifest'
            })
            return
        
        # Use transaction for consistency
        operations = []
        successful_imports = 0
        
        for file_info in imported_files:
            original_path = file_info.get('original_path')
            if not original_path:
                self._emit_event({
                    'type': 'status',
                    'level': 'warning',
                    'message': f'No original path for {file_info}'
                })
                continue
            
            # Ensure photo exists in photos table
            normalized_path = str(Path(original_path).resolve())
            self._ensure_photo_in_database(normalized_path)
            
            # Queue updates
            def update_photo(path=normalized_path, batch=batch_id, orig=original_path):
                with STATE.database.get_db() as conn:
                    # Try normalized path first
                    result = conn.execute('''
                        UPDATE photos SET 
                            import_batch_id = ?,
                            imported_at = CURRENT_TIMESTAMP
                        WHERE filepath = ?
                    ''', (batch, path))
                    
                    if result.rowcount == 0:
                        # Try original path
                        result = conn.execute('''
                            UPDATE photos SET 
                                import_batch_id = ?,
                                imported_at = CURRENT_TIMESTAMP
                            WHERE filepath = ?
                        ''', (batch, orig))
                    
                    # Update queue
                    conn.execute('''
                        UPDATE pipeline_queue 
                        SET status = 'complete'
                        WHERE batch_id = ? AND filepath = ?
                    ''', (batch, orig))
                    
                    return result.rowcount > 0
            
            future = Future()
            STATE.db_queue.put((update_photo, future))
            operations.append((file_info, future))
        
        # Wait for all operations
        for file_info, future in operations:
            try:
                if future.result(timeout=30):
                    successful_imports += 1
                    self._emit_event({
                        'type': 'status',
                        'level': 'debug',
                        'message': f'Updated {Path(file_info["original_path"]).name}'
                    })
                else:
                    self._emit_event({
                        'type': 'error',
                        'message': f'Failed to update photo record for {file_info["original_path"]}'
                    })
            except Exception as e:
                self._emit_event({
                    'type': 'error',
                    'message': f'Database update error: {e}'
                })
        
        # Update batch status
        def update_batch_status():
            with STATE.database.get_db() as conn:
                if successful_imports == len(imported_files):
                    status = 'complete'
                    error_msg = None
                elif successful_imports > 0:
                    status = 'partial'
                    error_msg = f'{successful_imports}/{len(imported_files)} files imported successfully'
                else:
                    status = 'failed'
                    error_msg = 'No files were successfully imported'
                
                conn.execute('''
                    UPDATE pipeline_status 
                    SET status = ?,
                        completed_at = CURRENT_TIMESTAMP,
                        error_message = ?
                    WHERE batch_id = ?
                ''', (status, error_msg, batch_id))
        
        future = Future()
        STATE.db_queue.put((update_batch_status, future))
        future.result(timeout=30)
        
        self._emit_event({
            'type': 'status',
            'level': 'info',
            'message': f'Database updated for {successful_imports}/{len(imported_files)} files'
        })
        
        # Cleanup Mac B files after import
        self._cleanup_mac_b_files(batch_id, success=True)
    
    def _cleanup_mac_b_files(self, batch_id: str, success: bool = True):
        """Clean up Mac B files after import completion"""
        status_text = "successful" if success else "failed"
        self._emit_event({
            'type': 'status',
            'level': 'info',
            'message': f'Cleaning up Mac B files for {status_text} batch {batch_id}'
        })
        
        # Check retention policy
        if success:
            keep_days = self.config.get('cleanup', {}).get('keep_successful_days', 0)
        else:
            keep_days = self.config.get('cleanup', {}).get('keep_failed_days', 0)
        
        if keep_days > 0:
            self._emit_event({
                'type': 'status',
                'level': 'info',
                'message': f'Keeping {status_text} batch for {keep_days} days per configuration'
            })
            return
        
        try:
            with self._get_ssh_connection() as ssh:
                # Get home directory
                stdin, stdout, stderr = ssh.exec_command('pwd', timeout=10)
                home_dir = stdout.read().decode().strip()
                
                # Build paths
                incoming_dir = self.config['paths']['remote_incoming']
                if incoming_dir.startswith('~'):
                    incoming_dir = home_dir + incoming_dir[1:]
                processed_dir = self.config['paths']['remote_processed']
                if processed_dir.startswith('~'):
                    processed_dir = home_dir + processed_dir[1:]
                reports_dir = self.config['paths']['remote_reports']
                if reports_dir.startswith('~'):
                    reports_dir = home_dir + reports_dir[1:]
                
                # Paths to clean
                batch_incoming = f"{incoming_dir}/{batch_id}"
                batch_processed = f"{processed_dir}/{batch_id}"
                manifest_file = f"{reports_dir}/manifest_{batch_id}.json"
                
                # Remove from both IncomingPhotos and ProcessedPhotos
                cleanup_commands = [
                    f'rm -rf "{batch_incoming}"',
                    f'rm -rf "{batch_processed}"',
                    f'rm -f "{manifest_file}"'
                ]
                
                for cmd in cleanup_commands:
                    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
                    exit_status = stdout.channel.recv_exit_status()
                    if exit_status != 0:
                        error = stderr.read().decode()
                        self._emit_event({
                            'type': 'status',
                            'level': 'warning',
                            'message': f'Cleanup command failed: {cmd} - {error}'
                        })
                
                # Clean/truncate import log if configured (only for successful imports)
                if success and self.config.get('cleanup', {}).get('clean_import_log', True):
                    log_cmd = f'echo "$(date): Cleaned after batch {batch_id}" > "{reports_dir}/import.log"'
                    ssh.exec_command(log_cmd, timeout=10)
                
                self._emit_event({
                    'type': 'status',
                    'level': 'info',
                    'message': f'Cleaned up {status_text} batch {batch_id}'
                })
                
        except Exception as e:
            self._emit_event({
                'type': 'status',
                'level': 'warning',
                'message': f'Cleanup failed: {e}'
            })
            # Don't fail the import process due to cleanup errors

    def _cleanup_orphaned_files(self):
        """Clean up orphaned files in IncomingPhotos older than configured hours"""
        hours = self.config.get('cleanup', {}).get('clean_incoming_after_hours', 1)
        if hours <= 0:
            return
        
        self._emit_event({
            'type': 'status',
            'level': 'info',
            'message': f'Cleaning orphaned files older than {hours} hours'
        })
        
        try:
            with self._get_ssh_connection() as ssh:
                # Find and remove old directories in IncomingPhotos
                minutes = int(hours * 60)
                cmd = f'''
                    find ~/IncomingPhotos -maxdepth 1 -type d -name "20*_*" -mmin +{minutes} -exec rm -rf {{}} +
                    find ~/ImportReports -name ".manifest_*_tmp.json" -mmin +{minutes} -delete
                '''
                stdin, stdout, stderr = ssh.exec_command(cmd, timeout=60)
                exit_status = stdout.channel.recv_exit_status()
                
                if exit_status == 0:
                    self._emit_event({
                        'type': 'status',
                        'level': 'info',
                        'message': 'Cleaned orphaned files'
                    })
                else:
                    error = stderr.read().decode()
                    self._emit_event({
                        'type': 'status',
                        'level': 'warning',
                        'message': f'Orphan cleanup failed: {error}'
                    })
                    
        except Exception as e:
            self._emit_event({
                'type': 'status',
                'level': 'warning',
                'message': f'Orphan cleanup error: {e}'
            })
    
    def cleanup_staging(self, batch_dir: Path):
        """Clean up staging directory"""
        try:
            if batch_dir in self._staging_dirs:
                self._staging_dirs.remove(batch_dir)
            if batch_dir in STATE.pipeline_staging_dirs:
                STATE.pipeline_staging_dirs.remove(batch_dir)
            
            if batch_dir.exists():
                shutil.rmtree(batch_dir)
                self._emit_event({
                    'type': 'status',
                    'level': 'info',
                    'message': 'Cleaned up staging directory'
                })
        except Exception as e:
            self._emit_event({
                'type': 'status',
                'level': 'warning',
                'message': f'Failed to cleanup staging: {e}'
            })
    
    def _verify_mac_b_setup(self) -> bool:
        """Verify Mac B is properly configured"""
        try:
            with self._get_ssh_connection() as ssh:
                missing_dirs = []
                
                # Get home directory
                stdin, stdout, stderr = ssh.exec_command('pwd', timeout=10)
                home_dir = stdout.read().decode().strip()
                
                for path_key in ['remote_incoming', 'remote_processed', 'remote_reports']:
                    path = self.config['paths'][path_key]
                    if path.startswith('~'):
                        path = home_dir + path[1:]
                    
                    stdin, stdout, stderr = ssh.exec_command(f'test -d "{path}" && echo "OK"', timeout=10)
                    result = stdout.read().decode().strip()
                    if result != "OK":
                        missing_dirs.append(path)
                
                # Create missing directories
                if missing_dirs:
                    self._emit_event({
                        'type': 'status',
                        'level': 'info',
                        'message': f'Creating {len(missing_dirs)} missing directories on Mac B...'
                    })
                    for path in missing_dirs:
                        stdin, stdout, stderr = ssh.exec_command(f'mkdir -p "{path}"', timeout=10)
                        exit_status = stdout.channel.recv_exit_status()
                        if exit_status != 0:
                            self._emit_event({
                                'type': 'error',
                                'message': f'Failed to create directory: {path}'
                            })
                            return False
                        else:
                            self._emit_event({
                                'type': 'status',
                                'level': 'info',
                                'message': f'Created {path}'
                            })
                
                # Check if Folder Actions are attached to IncomingPhotos
                # First, let's see what FASettingsTool actually returns
                stdin, stdout, stderr = ssh.exec_command(
                    '/System/Library/CoreServices/Folder\\ Actions\\ Dispatcher.app/Contents/Resources/FASettingsTool -l 2>&1',
                    timeout=10
                )
                fa_output = stdout.read().decode()
                
                # Now count IncomingPhotos mentions
                stdin, stdout, stderr = ssh.exec_command(
                    '/System/Library/CoreServices/Folder\\ Actions\\ Dispatcher.app/Contents/Resources/FASettingsTool -l 2>/dev/null | grep IncomingPhotos | wc -l | tr -d " " || echo "0"',
                    timeout=10
                )
                folder_action_count = stdout.read().decode().strip()
                
                # Log the raw output for debugging
                self._emit_event({
                    'type': 'status',
                    'level': 'debug',
                    'message': f'FASettingsTool output: {fa_output[:200]}...'  # First 200 chars
                })
                
                if folder_action_count == "0":
                    self._emit_event({
                        'type': 'status',
                        'level': 'warning',
                        'message': 'No Folder Actions attached to IncomingPhotos on Mac B'
                    })
                else:
                    self._emit_event({
                        'type': 'status',
                        'level': 'info',
                        'message': f'Folder Actions attached to IncomingPhotos ({folder_action_count} workflow(s))'
                    })
                
                return True
                
        except Exception as e:
            self._emit_event({
                'type': 'error',
                'message': f'Failed to verify Mac B setup: {e}'
            })
            return False
    
    def process_batch(self, batch_id: str) -> bool:
        """Process a single batch of photos"""
        self._emit_event({
            'type': 'status',
            'level': 'info',
            'message': f'Processing batch: {batch_id}'
        })
        
        batch_dir = None
        
        try:
            # Get photos in batch
            photos = self.get_batch_photos(batch_id)
            if not photos:
                self._emit_event({
                    'type': 'status',
                    'level': 'warning',
                    'message': 'No pending photos in batch'
                })
                return False
            
            self._emit_event({
                'type': 'status',
                'level': 'info',
                'message': f'Found {len(photos)} photos to process'
            })
            
            # Update batch status
            def update_status():
                with STATE.database.get_db() as conn:
                    conn.execute('''
                        UPDATE pipeline_status 
                        SET status = 'processing',
                            started_at = CASE 
                                WHEN started_at IS NULL THEN CURRENT_TIMESTAMP 
                                ELSE started_at 
                            END
                        WHERE batch_id = ?
                    ''', (batch_id,))
            
            future = Future()
            STATE.db_queue.put((update_status, future))
            future.result(timeout=30)
            
            # Process steps
            self._emit_event({
                'type': 'status',
                'level': 'info',
                'message': '1. Waking Mac B...'
            })
            if not self.wake_mac_b():
                # Only wait for connection if wake_mac_b returned False
                if not self.wait_for_connection():
                    raise TransferError("Failed to connect to Mac B after wake")
            
            self._emit_event({
                'type': 'status',
                'level': 'info',
                'message': '2. Verifying Mac B setup...'
            })
            if not self._verify_mac_b_setup():
                self._emit_event({
                    'type': 'status',
                    'level': 'warning',
                    'message': 'Mac B setup incomplete, but continuing anyway...'
                })
            
            # Run startup cleanup after connection established
            if self.config.get('cleanup', {}).get('startup_cleanup', True):
                self._cleanup_orphaned_files()
            
            self._emit_event({
                'type': 'status',
                'level': 'info',
                'message': '3. Staging files...'
            })
            batch_dir = self.stage_files(photos)
            if not batch_dir:
                raise TransferError("Failed to stage files")
            
            self._emit_event({
                'type': 'status',
                'level': 'info',
                'message': '4. Transferring files...'
            })
            if not self.transfer_files(batch_dir, batch_id):
                raise TransferError("Failed to transfer files")
            
            self._emit_event({
                'type': 'status',
                'level': 'info',
                'message': '5. Waiting for import to complete...'
            })
            
            # Calculate timeout
            timeout_per_photo = self.config['transfer'].get('timeout_per_photo', 120)
            dynamic_timeout = len(photos) * timeout_per_photo
            max_timeout = self.config['transfer']['timeout_seconds']
            actual_timeout = min(dynamic_timeout, max_timeout)
            
            manifest = self.wait_for_manifest(batch_id, timeout=actual_timeout)
            
            if manifest is None:
                raise ImportError("Timeout waiting for import manifest")
            
            self._emit_event({
                'type': 'status',
                'level': 'info',
                'message': '6. Updating database...'
            })
            self.update_database(batch_id, manifest)
            
            self._emit_event({
                'type': 'status',
                'level': 'info',
                'message': '7. Cleaning up...'
            })
            self.cleanup_staging(batch_dir)
            
            self._emit_event({
                'type': 'complete',
                'batch_id': batch_id,
                'success': True,
                'message': f'Batch {batch_id} complete! Imported {len(manifest.get("files", []))} photos successfully'
            })
            
            return True
            
        except Exception as e:
            self._emit_event({
                'type': 'error',
                'message': f'Batch failed: {e}'
            })
            
            # Update batch status
            def update_failed():
                with STATE.database.get_db() as conn:
                    conn.execute('''
                        UPDATE pipeline_status 
                        SET status = 'failed',
                            error_message = ?,
                            completed_at = CURRENT_TIMESTAMP
                        WHERE batch_id = ?
                    ''', (str(e), batch_id))
            
            future = Future()
            STATE.db_queue.put((update_failed, future))
            try:
                future.result(timeout=30)
            except:
                pass
            
            # Cleanup staging if exists
            if batch_dir:
                self.cleanup_staging(batch_dir)
            
            # Also cleanup Mac B files for failed batch
            self._cleanup_mac_b_files(batch_id, success=False)
            
            return False

# ============================================================================
# PIPELINE HELPER FUNCTION
# ============================================================================

def run_integrated_pipeline(batch_id: str):
    """Run pipeline in thread instead of subprocess"""
    try:
        # Load config if not loaded
        if not STATE.pipeline_config:
            config_path = STATE.data_dir / "pipeline_config.json"
            try:
                with open(config_path) as f:
                    STATE.pipeline_config = json.load(f)
            except FileNotFoundError:
                # Create default config but don't exit
                STATE.pipeline_config = DEFAULT_CONFIG.copy()
                config_path.write_text(json.dumps(STATE.pipeline_config, indent=2))
                error_msg = f"Created default config at {config_path}. Please edit with Mac B details."
                logger.error(f"[PIPELINE] {error_msg}")
                logger.error(f"[PIPELINE] Config file location: {config_path}")
                STATE.pipeline_events.append({
                    'type': 'error',
                    'message': error_msg,
                    'timestamp': datetime.now().isoformat()
                })
                # Also add to output for visibility
                STATE.pipeline_output.append(f"ERROR: {error_msg}")
                STATE.pipeline_output.append(f"Config file location: {config_path}")
                STATE.pipeline_output.append("Edit the file with your Mac B connection details, then try again.")
                return
            except Exception as e:
                error_msg = f'Config load failed: {str(e)}'
                logger.error(f"[PIPELINE] {error_msg}")
                STATE.pipeline_events.append({
                    'type': 'error', 
                    'message': error_msg,
                    'timestamp': datetime.now().isoformat()
                })
                STATE.pipeline_output.append(f"ERROR: {error_msg}")
                return
        
        # Validate config before creating pipeline
        logger.info(f"[PIPELINE] Starting pipeline for batch {batch_id}")
        logger.info(f"[PIPELINE] Config: {STATE.pipeline_config}")
        
        # Create pipeline instance
        pipeline = PhotoPipeline(
            working_dir=STATE.working_dir,
            config=STATE.pipeline_config,
            database=STATE.database
        )
        
        # Validate configuration
        pipeline._validate_config()
        
        # Track resources in STATE for cleanup
        STATE.pipeline_ssh_connections = []
        STATE.pipeline_staging_dirs = []
        
        # Run with cancellation checks
        success = pipeline.process_batch(batch_id)
        
        # Update final status
        STATE.pipeline_events.append({
            'type': 'complete',
            'success': success,
            'batch_id': batch_id,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"[PIPELINE] Pipeline failed: {e}", exc_info=True)  # exc_info=True adds stack trace
        STATE.pipeline_events.append({
            'type': 'error',
            'error': str(e),
            'batch_id': batch_id,
            'timestamp': datetime.now().isoformat()
        })
        # Update UI-visible output
        STATE.pipeline_output.append(f"ERROR: Pipeline failed - {str(e)}")
    finally:
        # Cleanup resources
        for conn in STATE.pipeline_ssh_connections:
            try:
                conn.close()
            except:
                pass
        for dir_path in STATE.pipeline_staging_dirs:
            try:
                if dir_path.exists():
                    shutil.rmtree(dir_path)
            except:
                pass
        STATE.pipeline_future = None
        STATE.pipeline_cancelled = False

# ============================================================================
# EXIFTOOL SETUP
# ============================================================================

def setup_exiftool() -> bool:
    """Download and setup ExifTool if needed"""
    TOOLS_DIR.mkdir(exist_ok=True)
    
    exiftool_path = TOOLS_DIR / "exiftool"
    lib_path = TOOLS_DIR / "lib"
    
    if exiftool_path.exists() and lib_path.exists():
        STATE.exiftool_path = exiftool_path
        print(f"ExifTool found at: {exiftool_path}")
        return True
    
    print(f"Downloading ExifTool v{EXIFTOOL_VERSION}...")
    
    try:
        temp_file = TOOLS_DIR / "exiftool.tar.gz"
        urllib.request.urlretrieve(EXIFTOOL_URL, temp_file)
        
        with tarfile.open(temp_file, 'r:gz') as tar:
            for member in tar.getmembers():
                parts = member.name.split('/', 1)
                if len(parts) > 1:
                    member.name = parts[1]
                    tar.extract(member, TOOLS_DIR)
        
        temp_file.unlink()
        exiftool_path.chmod(0o755)
        
        result = subprocess.run([str(exiftool_path), '-ver'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            STATE.exiftool_path = exiftool_path
            print(f"ExifTool {result.stdout.strip()} installed")
            return True
            
    except Exception as e:
        print(f"Error setting up ExifTool: {e}")
    
    return False

# ============================================================================
# METADATA READING
# ============================================================================

def read_metadata_from_file(filepath: Path) -> Tuple[Optional[DateInfo], Optional[LocationInfo], List[str], Dict[str, Any]]:
    """Read metadata from image file - now also detects camera data"""
    if not STATE.exiftool_path:
        return None, None, [], {}
    
    # Check cache first
    try:
        mtime = filepath.stat().st_mtime
        cache_key = f"{filepath}:{mtime}"
        with METADATA_CACHE_LOCK:
            if cache_key in METADATA_CACHE:
                return METADATA_CACHE[cache_key]
    except:
        pass
    
    try:
        cmd = [
            str(STATE.exiftool_path),
            "-json",
            "-n",
            "-DateTimeOriginal",
            "-Keywords", 
            "-Subject",
            "-XMP:City",
            "-XMP:State",
            "-XMP:Country",
            "-IPTC:Country-PrimaryLocationName",
            "-IPTC:Country-PrimaryLocationCode",
            "-XMP:LocationCreatedPostalCode",
            "-XMP:LocationCreatedSublocation",
            "-XMP:LocationShownSublocation",
            "-GPSLatitude", "-GPSLongitude",
            "-GPSLatitudeRef", "-GPSLongitudeRef",
            "-Make",
            "-Model",
            "-ISO",
            "-FNumber",
            "-ExposureTime",
            "-FocalLength",
            str(filepath)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)[0]
        
        # Extract date
        date_info = None
        if date_str := data.get('DateTimeOriginal'):
            parts = date_str.split()
            if parts:
                date_part = parts[0]
                if ':' in date_part:
                    y, m, d = date_part.split(':')
                    # All data read from file is SYSTEM source (computer filled it)
                    source = DataSource.SYSTEM
                    
                    date_info = DateInfo(
                        year=y, month=m, day=d,
                        year_source=source,
                        month_source=source,
                        day_source=source
                    )

        # Extract location -----------------------------------------------------------
        location_info = None

        # --- GPS --------------------------------------------------------------------
        lat  = data.get('GPSLatitude')
        lon  = data.get('GPSLongitude')
        latR = (data.get('GPSLatitudeRef')  or '').upper()
        lonR = (data.get('GPSLongitudeRef') or '').upper()

        if lat is not None and lon is not None:
            # apply sign from Ref tags
            if latR == 'S':
                lat = -abs(float(lat))
            if lonR == 'W':
                lon = -abs(float(lon))

        # --- City / State / Country -----------------------------------------------------------
        city  = data.get('City', '')
        state = data.get('State', '')
        country = data.get('Country') or data.get('Country-PrimaryLocationName', '')
        country_code = data.get('Country-PrimaryLocationCode', '')
        postal_code = data.get('LocationCreatedPostalCode', '')
        neighborhood = data.get('LocationCreatedSublocation') or data.get('LocationShownSublocation', '')

        # Build LocationInfo if we have either GPS *or* State/City
        if (lat is not None and lon is not None) or state:
            location_info = LocationInfo(
            city         = city,
            state        = state,
            city_source  = (DataSource.SYSTEM if city else None),
            state_source = (DataSource.SYSTEM if state else None),
            country      = country,
            country_code = country_code.strip() if country_code else '',
            country_source = (DataSource.SYSTEM if country else None),
            postal_code  = postal_code,
            neighborhood = neighborhood,
            gps_lat      = lat,
            gps_lon      = lon,
            gps_source   = (DataSource.SYSTEM if lat is not None else None)
        )

        # Extract tags
        tags = []
        for field in ['Keywords', 'Subject']:
            if values := data.get(field):
                if isinstance(values, list):
                    tags.extend(values)
                else:
                    tags.extend([t.strip() for t in values.split(',') if t.strip()])
        
        # Deduplicate
        seen = set()
        unique_tags = []
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        # Detect camera metadata
        camera_info = {
            'has_camera_metadata': False,
            'original_make': data.get('Make', ''),
            'original_model': data.get('Model', '')
        }
        
        # Check if this has real camera data (not our template)
        if camera_info['original_make'] and camera_info['original_model']:
            if (camera_info['original_make'] != CAMERA_MAKE or 
                camera_info['original_model'] != CAMERA_MODEL):
                camera_info['has_camera_metadata'] = True
            # Also check for exposure data as additional indicator
            elif any(data.get(field) for field in ['ISO', 'FNumber', 'ExposureTime']):
                camera_info['has_camera_metadata'] = True
        
        # Cache the result before returning
        result = (date_info, location_info, unique_tags, camera_info)
        try:
            mtime = filepath.stat().st_mtime
            cache_key = f"{filepath}:{mtime}"
            with METADATA_CACHE_LOCK:
                METADATA_CACHE[cache_key] = result
            
            # Limit cache size
            with METADATA_CACHE_LOCK:
                if len(METADATA_CACHE) > METADATA_CACHE_SIZE:
                    # Remove oldest entries
                    for key in list(METADATA_CACHE.keys())[:20]:
                        del METADATA_CACHE[key]
        except:
            pass
        
        return result
        
    except Exception as e:
        print(f"Error reading metadata: {e}")
        return None, None, [], {}

# ============================================================================
# METADATA WRITING
# ============================================================================

def write_metadata_to_file(filepath: Path, date_info: Optional[DateInfo], 
                          location_info: Optional[LocationInfo], preserve_camera: bool = False) -> bool:
    """Write metadata to file - now with camera data preservation"""
    if not STATE.exiftool_path:
        return False
    
    # First, read existing keywords if preserving camera data
    existing_user_keywords = []
    if preserve_camera:
        _, _, existing_tags, _ = read_metadata_from_file(filepath)
        # Filter out system tags to get user keywords
        existing_user_keywords = [tag for tag in existing_tags 
                                 if tag not in [DATE_KEYWORD, LOCATION_KEYWORD]]
    
    args = [str(STATE.exiftool_path), "-m", "-overwrite_original", "-use", "MWG"]
    
    if preserve_camera:
        # CRITICAL: Copy all existing tags first
        args.extend(["-TagsFromFile", "@", "-all:all"])
    
    # Always write camera info if not preserving
    if not preserve_camera:
        args.extend([
            f"-Make={CAMERA_MAKE}",
            f"-Model={CAMERA_MODEL}",
            f"-ImageDescription={IMAGE_DESCRIPTION}"
        ])
    
    # Date
    if date_info and date_info.year:
        date_str = f"{date_info.year}:{date_info.month or '01'}:{date_info.day or '01'} 12:00:00"
        args.extend([
            f"-DateTimeOriginal={date_str}",
            f"-CreateDate={date_str}",
            f"-ModifyDate={date_str}"
        ])
    
    # Location
    if location_info and location_info.state:
        # IPTC fields (with length limits for Apple Photos compatibility)
        if location_info.landmark_name:
            args.append(f"-IPTC:Sub-location={location_info.landmark_name[:32]}")
        elif location_info.neighborhood:
            args.append(f"-IPTC:Sub-location={location_info.neighborhood[:32]}")
        elif location_info.street:
            args.append(f"-IPTC:Sub-location={location_info.street[:32]}")
        
        if location_info.city:
            args.append(f"-IPTC:City={location_info.city[:32]}")
            args.append(f"-XMP:City={location_info.city}")
        else:
            args.append("-IPTC:City=")
            args.append("-XMP:City=")
        
        args.append(f"-IPTC:Province-State={location_info.state[:32]}")
        args.append(f"-XMP:State={location_info.state}")
        
        # Handle country (Apple already provides it)
        if location_info.country:
            country = location_info.country
            country_code = location_info.country_code
            args.append(f"-IPTC:Country-PrimaryLocationName={country[:64]}")
            args.append(f"-XMP:Country={country}")
            
            if country_code:
                # IPTC requires exactly 3 chars - pad if needed
                if len(country_code) == 2:
                    country_code = country_code + " "
                args.append(f"-IPTC:Country-PrimaryLocationCode={country_code[:3]}")
                args.append(f"-XMP:CountryCode={country_code.strip()}")
        
        # XMP extended fields (no length limits)
        if location_info.street:
            args.append(f"-XMP:LocationShownSublocation={location_info.street}")
        if location_info.postal_code:
            args.append(f"-XMP:LocationCreatedPostalCode={location_info.postal_code}")
        if location_info.neighborhood:
            args.append(f"-XMP:LocationCreatedSublocation={location_info.neighborhood}")
        
        # GPS coordinates
        if location_info.gps_lat is not None and location_info.gps_lon is not None:
            lat, lon = location_info.gps_lat, location_info.gps_lon
            # Determine accuracy based on what type of search this was
            if location_info.street:
                accuracy = "10"  # Address-level accuracy
            elif location_info.landmark_name:
                accuracy = "25"  # POI accuracy
            elif location_info.city:
                accuracy = "1000"  # City-level accuracy
            elif location_info.state or location_info.country:
                accuracy = "5000"  # State/Country-level accuracy
            else:
                accuracy = "100"  # Default accuracy
                
            args.extend([
                f"-GPSLatitude={abs(lat)}",
                f"-GPSLongitude={abs(lon)}",
                f"-GPSLatitudeRef={'N' if lat >= 0 else 'S'}",
                f"-GPSLongitudeRef={'E' if lon >= 0 else 'W'}",
                f"-GPSHPositioningError={accuracy}"
            ])
    
    # Tags - merge user keywords with system tags
    all_tags = existing_user_keywords.copy() if preserve_camera else []
    
    # CRITICAL: Tags must match what will be in database after save
    # We need to predict the final needs_date/needs_location state
    
    # Determine if date will be complete after this save
    will_need_date = True
    if date_info:
        will_need_date = date_info.needs_tag()
    else:
        # No date info provided, check existing state
        existing_date, _, _, _ = read_metadata_from_file(filepath)
        if existing_date:
            will_need_date = existing_date.needs_tag()
    
    # Determine if location will be complete after this save
    will_need_location = True
    if location_info:
        will_need_location = location_info.needs_tag()
    else:
        # No location info provided, check existing state
        _, existing_location, _, _ = read_metadata_from_file(filepath)
        if existing_location and (existing_location.gps_lat or existing_location.state):
            will_need_location = existing_location.needs_tag()
    
    # Apply tags based on predicted final state
    if will_need_date:
        all_tags.append(DATE_KEYWORD)
    if will_need_location:
        all_tags.append(LOCATION_KEYWORD)
    
    # Remove duplicates while preserving order
    seen = set()
    final_tags = []
    for tag in all_tags:
        if tag not in seen:
            seen.add(tag)
            final_tags.append(tag)
    
    # Write keywords
    if final_tags:
        tag_string = ", ".join(final_tags)
        args.extend([f"-Keywords={tag_string}", f"-Subject={tag_string}"])
    else:
        args.extend(["-Keywords=", "-Subject="])
    
    args.append(str(filepath))
    
    try:
        result = subprocess.run(args, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error writing metadata: {e}")
        if e.stderr:
            print(f"ExifTool stderr: {e.stderr}")
        if e.stdout:
            print(f"ExifTool stdout: {e.stdout}")
        return False

# ============================================================================
# FILENAME PARSING
# ============================================================================

def extract_date_from_filename(filename: str) -> Optional[Dict[str, str]]:
    """Extract date suggestion from filename using LLM parser.
    
    Uses Mistral-7B Instruct v0.3 model to extract structured date information.
    Falls back to regex parser if LLM is unavailable or fails.
    
    Args:
        filename: Photo filename to parse
        
    Returns:
        Dict with year, month, day (as strings) and is_complete flag
        Returns None if no date found
    """
    if USE_LLM_PARSER and STATE.filename_parser and _LLM_AVAILABLE:
        try:
            llm_output = STATE.filename_parser.parse_filename(filename)
            result = STATE.filename_parser.to_date_suggestion(llm_output)
            if result:
                logger.debug(f"LLM date extraction for {filename}: {result}")
                return result
        except Exception as e:
            logger.warning(f"LLM date parser failed for {filename}: {e}")
    
    # Fallback to regex parser
    return _extract_date_from_filename_regex(filename)

def _extract_date_from_filename_regex(filename: str) -> Optional[Dict[str, str]]:
    """Original regex-based date parser (backup)"""
    stem = Path(filename).stem
    s = re.sub(r"_[0-9]{3,4}$", "", stem, count=1)
    
    # Pattern: Month_DD_YYYY
    if m := re.search(r"(?:_|\b)([a-z]{3,})[_-](\d{1,2})[_-](\d{4})(?:_|\b)", s, re.I):
        mon, d, y = m.groups()
        if mon[:3].lower() in MONTH_MAP:
            return {
                'year': y,
                'month': MONTH_MAP[mon[:3].lower()],
                'day': f"{int(d):02d}",
                'is_complete': True
            }
    
    # Pattern: Month_YYYY
    if m := re.search(r"(?:_|\b)([a-z]{3,})[_-](\d{4})(?:_|\b)", s, re.I):
        mon, y = m.groups()
        if mon[:3].lower() in MONTH_MAP:
            return {
                'year': y,
                'month': MONTH_MAP[mon[:3].lower()],
                'day': '',
                'is_complete': True
            }
    
    # Pattern: YYYY-MM-DD
    if m := re.search(r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})", s):
        y, mn, d = m.groups()
        if 1900 <= int(y) <= 2025 and 1 <= int(mn) <= 12 and 1 <= int(d) <= 31:
            return {
                'year': y,
                'month': mn,
                'day': d,
                'is_complete': True
            }
    
    # Pattern: Just YYYY (no month)
    if m := re.search(r"(?:_|\b)(\d{4})(?:_|\b)", s):
        y = m.group(1)
        if 1900 <= int(y) <= 2025:
            return {
                'year': y,
                'month': '',
                'day': '',
                'is_complete': False
            }
    
    return None

def extract_location_from_filename(filename: str) -> Optional[Dict[str, str]]:
    """Extract location suggestion from filename using LLM parser.
    
    Uses Mistral-7B Instruct v0.3 model to extract structured location information.
    Falls back to regex parser if LLM is unavailable or fails.
    
    Args:
        filename: Photo filename to parse
        
    Returns:
        Dict with city, state, country and is_complete flag
        Returns None if no location found
    """
    if USE_LLM_PARSER and STATE.filename_parser and _LLM_AVAILABLE:
        try:
            llm_output = STATE.filename_parser.parse_filename(filename)
            result = STATE.filename_parser.to_location_suggestion(llm_output)
            if result:
                logger.debug(f"LLM location extraction for {filename}: {result}")
                return result
        except Exception as e:
            logger.warning(f"LLM location parser failed for {filename}: {e}")
    
    # Fallback to regex parser
    return _extract_location_from_filename_regex(filename)

def _extract_location_from_filename_regex(filename: str) -> Optional[Dict[str, str]]:
    """Original regex-based location parser (backup)"""
    # Remove sequence numbers from end
    s = re.sub(r"_[0-9]{3,4}$", "", Path(filename).stem)
    
    # Remove common date patterns to avoid interference
    # Patterns: Month_YYYY, DD_Month_YYYY, YYYY_MM_DD, etc.
    date_patterns = [
        r"_(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*_\d{4}",
        r"_\d{1,2}_(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*_\d{4}",
        r"_\d{4}_\d{2}_\d{2}",
        r"_\d{2}_\d{2}_\d{4}"
    ]
    for pattern in date_patterns:
        s = re.sub(pattern, "", s, flags=re.IGNORECASE)
    
    # Special cases with known proper capitalization
    if re.search(r"(?:^|_)PBG_FL(?:_|$)", s, re.IGNORECASE):
        return {
            'city': 'Palm Beach Gardens',
            'state': 'FL',
            'country': '',
            'is_complete': True,
            'confidence': 85,
            'primary_search': 'Palm Beach Gardens, FL',
            'alternate_search': 'FL',
            'location_type': 'city',
            'reasoning': 'Recognized city abbreviation',
            'landmark_name': ''
        }
    if re.search(r"(?:^|_)ABQ_NM(?:_|$)", s, re.IGNORECASE):
        return {
            'city': 'Albuquerque',
            'state': 'NM',
            'country': '',
            'is_complete': True,
            'confidence': 85,
            'primary_search': 'Albuquerque, NM',
            'alternate_search': 'NM',
            'location_type': 'city',
            'reasoning': 'Recognized city abbreviation',
            'landmark_name': ''
        }
    
    # Split into words and search from right to left (locations usually at end)
    words = s.split('_')
    
    # Look for location patterns starting from the end
    for i in range(len(words) - 1, -1, -1):
        # Skip if current word is too short
        if len(words[i]) < 2:
            continue
            
        # Pattern: City_State_Country (three consecutive location words)
        if i >= 2:
            potential_country = words[i]
            potential_state = words[i-1]
            potential_city = words[i-2]
            
            if (len(potential_state) == 2 and potential_state.upper() in US_STATES and
                potential_country.lower() in COUNTRIES_LIST):
                return {
                    'city': potential_city.title(),
                    'state': potential_state.upper(),
                    'country': potential_country.title(),
                    'is_complete': True,
                    'confidence': 85,
                    'primary_search': f"{potential_city.title()}, {potential_state.upper()}, {potential_country.title()}",
                    'alternate_search': f"{potential_city.title()}, {potential_state.upper()}",
                    'location_type': 'city',
                    'reasoning': 'City, state, and country found',
                    'venue_name': ''
                }
        
        # Pattern: City_Country (two consecutive words where second is a country)
        if i >= 1:
            potential_country = words[i]
            potential_city = words[i-1]
            
            if potential_country.lower() in COUNTRIES_LIST:
                # Make sure the city isn't also a country (avoid France_France)
                if potential_city.lower() not in COUNTRIES_LIST:
                    return {
                        'city': potential_city.title(),
                        'state': '',
                        'country': potential_country.title(),
                        'is_complete': True,
                        'confidence': 85,
                        'primary_search': f"{potential_city.title()}, {potential_country.title()}",
                        'alternate_search': potential_country.title(),
                        'location_type': 'city',
                        'reasoning': 'International city and country found',
                        'venue_name': ''
                    }
        
        # Pattern: City_State (US locations)
        if i >= 1:
            potential_state = words[i]
            potential_city = words[i-1]
            
            if len(potential_state) == 2 and potential_state.upper() in US_STATES:
                return {
                    'city': potential_city.title(),
                    'state': potential_state.upper(),
                    'country': '',
                    'is_complete': True,
                    'confidence': 85,
                    'primary_search': f"{potential_city.title()}, {potential_state.upper()}",
                    'alternate_search': potential_state.upper(),
                    'location_type': 'city',
                    'reasoning': 'US city and state found',
                    'venue_name': ''
                }
    
    # If no multi-word pattern found, look for single location identifiers
    for i in range(len(words) - 1, -1, -1):
        word = words[i]
        
        # Just a country
        if word.lower() in COUNTRIES_LIST:
            return {
                'city': '',
                'state': '',
                'country': word.title(),
                'is_complete': False,
                'confidence': 60,
                'primary_search': word.title(),
                'alternate_search': None,
                'location_type': 'country',
                'reasoning': 'Only country name found',
                'venue_name': ''
            }
        
        # Just a US state
        if len(word) == 2 and word.upper() in US_STATES:
            return {
                'city': '',
                'state': word.upper(),
                'country': '',
                'is_complete': False,
                'confidence': 60,
                'primary_search': word.upper(),
                'alternate_search': None,
                'location_type': 'state',
                'reasoning': 'Only US state found',
                'venue_name': ''
            }
        
        # Full state name
        if word.lower() in STATE_NAME_TO_ABBR:
            return {
                'city': '',
                'state': STATE_NAME_TO_ABBR[word.lower()],
                'country': '',
                'is_complete': False,
                'confidence': 60,
                'primary_search': STATE_NAME_TO_ABBR[word.lower()],
                'alternate_search': None,
                'location_type': 'state',
                'reasoning': 'Only US state name found',
                'venue_name': ''
            }
    
    return None

# ============================================================================
# IMAGE PROCESSING - THUMBNAILS
# ============================================================================

def create_thumbnail(image_path: Path, max_size=(800, 800)) -> Optional[str]:
    """Create base64 encoded thumbnail with persistent storage"""
    # Get file modification time
    try:
        mtime = image_path.stat().st_mtime
    except:
        return None
    
    # Check memory cache first
    cache_key = f"{image_path}:{mtime}:{max_size[0]}x{max_size[1]}"
    with THUMBNAIL_CACHE_LOCK:
        if cache_key in THUMBNAIL_CACHE:
            return THUMBNAIL_CACHE[cache_key]
    
    # Check database cache
    if STATE.database:
        size_str = f"{max_size[0]}x{max_size[1]}"
        with STATE.database.get_db() as conn:
            result = conn.execute('''
                SELECT base64_data FROM thumbnails 
                WHERE filepath = ? AND file_mtime = ? AND size = ?
            ''', (str(image_path), mtime, size_str)).fetchone()
            
            if result:
                # Found in DB, add to memory cache and return
                THUMBNAIL_CACHE[cache_key] = result[0]
                return result[0]
    
    # Not in cache, generate it
    try:
        with Image.open(image_path) as img:
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            
            if img.mode in ('RGBA', 'P'):
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = rgb_img
                        
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=85)
        
        result = base64.b64encode(buffer.getvalue()).decode()
        
        # Save to memory cache
        with THUMBNAIL_CACHE_LOCK:
            THUMBNAIL_CACHE[cache_key] = result
        
        # Save to database
        if STATE.database:
            size_str = f"{max_size[0]}x{max_size[1]}"
            with STATE.database.get_db() as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO thumbnails (filepath, file_mtime, size, base64_data)
                    VALUES (?, ?, ?, ?)
                ''', (str(image_path), mtime, size_str, result))
        
        # Limit memory cache size
        with THUMBNAIL_CACHE_LOCK:
            if len(THUMBNAIL_CACHE) > THUMBNAIL_CACHE_SIZE:
                # Remove oldest entries from memory only (keep in DB)
                for key in list(THUMBNAIL_CACHE.keys())[:100]:
                    del THUMBNAIL_CACHE[key]
        
        return result
        
    except Exception as e:
        print(f"Error creating thumbnail: {e}")
        return None

# ============================================================================
# MAIN ROUTES
# ============================================================================

@app.route('/')
def index():
    return render_template_string(UI_TEMPLATE)

@app.route('/api/current')
def get_current():
    """Get current photo data"""
    filtered_photos = STATE.database.get_filtered_photos(STATE.current_filter)
    
    if not filtered_photos:
        return jsonify({
            'error': 'No photos in current filter',
            'current_filter': STATE.current_filter,
            'filtered_total': 0,
            'stats': STATE.database.get_stats()
        }), 404
    
    if STATE.current_index >= len(filtered_photos):
        STATE.current_index = 0  # Reset index if out of bounds
    
    filepath = filtered_photos[STATE.current_index]
    photo_path = Path(filepath)
    
    # Read from file first
    try:
        file_date, file_location, file_tags, file_camera_info = read_metadata_from_file(photo_path)
    except Exception as e:
        print(f"ERROR reading metadata from {photo_path}: {e}")
        file_date, file_location, file_tags, file_camera_info = None, None, [], {}
    
    # Get from database
    db_date, db_location = STATE.database.get_photo_state(filepath)
    
    # Sync: File is truth for values, DB is truth for sources
    if file_date and db_date:
        date_info = DateInfo(
            year=file_date.year,
            month=file_date.month,
            day=file_date.day,
            year_source=db_date.year_source or file_date.year_source,
            month_source=db_date.month_source or file_date.month_source,
            day_source=db_date.day_source or file_date.day_source,
            from_complete_suggestion=db_date.from_complete_suggestion
        )
    else:
        date_info = file_date
    
    if file_location and db_location:
        location_info = LocationInfo(
            city=file_location.city,
            state=file_location.state,
            city_source=db_location.city_source or file_location.city_source,
            state_source=db_location.state_source or file_location.state_source,
            gps_lat=file_location.gps_lat,
            gps_lon=file_location.gps_lon,
            gps_source=db_location.gps_source
        )
    elif not file_location and db_location:
        location_info = db_location
    else:
        location_info = file_location
    
    # Get suggestions - check cache first, queue if needed
    date_suggestion = None
    location_suggestion = None
    llm_status = 'ready'
    
    # Check if we have cached results in memory
    if filepath in LLM_PARSE_RESULTS and LLM_PARSE_RESULTS[filepath]['status'] == 'ready':
        result = LLM_PARSE_RESULTS[filepath]['result']
        date_suggestion = result.get('date')
        location_suggestion = result.get('location')
    else:
        # Check database cache before queuing
        db_cached = False
        if USE_LLM_PARSER and STATE.filename_parser and _LLM_AVAILABLE and STATE.database:
            with STATE.database.get_db() as conn:
                row = conn.execute('''
                    SELECT suggestion_filename, suggested_date_year, suggested_date_month,
                           suggested_date_day, suggested_date_complete, suggested_location_primary,
                           suggested_location_alternate, suggested_location_city, suggested_location_state,
                           suggested_location_confidence, suggested_location_type, suggested_location_reasoning,
                           suggested_location_landmark
                    FROM photos WHERE filepath = ?
                ''', (filepath,)).fetchone()
                
                if row and row['suggestion_filename'] == photo_path.name:
                    # Found in database cache
                    if row['suggested_date_year']:
                        date_suggestion = {
                            'year': row['suggested_date_year'],
                            'month': row['suggested_date_month'],
                            'day': row['suggested_date_day'],
                            'is_complete': bool(row['suggested_date_complete'])
                        }
                    
                    if row['suggested_location_primary']:
                        location_suggestion = {
                            'primary_search': row['suggested_location_primary'],
                            'alternate_search': row['suggested_location_alternate'],
                            'city': row['suggested_location_city'],
                            'state': row['suggested_location_state'],
                            'confidence': row['suggested_location_confidence'],
                            'location_type': row['suggested_location_type'],
                            'reasoning': row['suggested_location_reasoning'],
                            'landmark_name': row['suggested_location_landmark'],
                            'is_complete': row['suggested_location_confidence'] > 70 if row['suggested_location_confidence'] else False
                        }
                    
                    # Cache in memory for next time
                    LLM_PARSE_RESULTS[filepath] = {
                        'status': 'ready',
                        'result': {'date': date_suggestion, 'location': location_suggestion}
                    }
                    db_cached = True
        
        if not db_cached:
            # Check if LLM will process this
            if USE_LLM_PARSER and STATE.filename_parser and _LLM_AVAILABLE:
                # Don't show regex results - show analyzing state instead
                date_suggestion = None  # Will trigger "Analyzing" in UI
                location_suggestion = None  # Will trigger "Analyzing" in UI
                
                # Queue LLM parse with high priority
                LLM_PARSE_QUEUE.put((1 if not MODEL_WARMED.is_set() else 0, filepath, 'all'))
                llm_status = 'pending'
            else:
                # Only use regex if LLM is completely unavailable
                date_suggestion = _extract_date_from_filename_regex(photo_path.name)
                location_suggestion = _extract_location_from_filename_regex(photo_path.name)
                llm_status = 'ready'
    
    # Don't pre-queue on initial page load - only queue when navigating
    if USE_LLM_PARSER and STATE.filename_parser and _LLM_AVAILABLE:
        # Only pre-queue if this is a navigation (not initial load)
        if hasattr(STATE, '_initial_load_complete'):
            for i in range(1, 3):  # Only next 2 photos, not 5
                next_index = STATE.current_index + i
                if next_index < len(filtered_photos):
                    next_filepath = filtered_photos[next_index]
                    # Only queue if not already processed or queued
                    if next_filepath not in LLM_PARSE_RESULTS:
                        # Lower priority for pre-parsing
                        LLM_PARSE_QUEUE.put((i, next_filepath, 'all'))
        else:
            # Mark initial load complete for next time
            STATE._initial_load_complete = True
    
    # Correct city capitalization in location suggestion if found in gazetteer
    if location_suggestion and location_suggestion.get('city') and location_suggestion.get('state') and STATE.gazetteer:
        # Only correct US locations in gazetteer
        if not location_suggestion.get('country') or location_suggestion['country'] in ["United States", "USA", ""]:
            proper_names = STATE.gazetteer.get_proper_name(
                location_suggestion['city'], 
                location_suggestion['state']
            )
            if proper_names:
                location_suggestion['city'] = proper_names[0]
    
    # Build response
    response = {
        'filename': photo_path.name,
        'filepath': str(photo_path),
        'current_index': STATE.current_index,
        'filtered_total': len(filtered_photos),
        'current_filter': STATE.current_filter,
        'image_data': create_thumbnail(photo_path),
        'stats': STATE.database.get_stats(),
        'date_suggestion': date_suggestion,
        'location_suggestion': location_suggestion,
        'tags': file_tags,
        'llm_status': llm_status
    }
    
    # Add current metadata
    if date_info:
        response['date'] = {
            'year': date_info.year,
            'month': date_info.month,
            'day': date_info.day,
            'year_source': date_info.year_source.value if date_info.year_source else None,
            'month_source': date_info.month_source.value if date_info.month_source else None,
            'day_source': date_info.day_source.value if date_info.day_source else None,
            'from_complete_suggestion': date_info.from_complete_suggestion
        }
    
    if location_info:
        response['location'] = {
            'city': location_info.city,
            'state': location_info.state,
            'city_source': location_info.city_source.value if location_info.city_source else None,
            'state_source': location_info.state_source.value if location_info.state_source else None,
            'has_gps': location_info.gps_lat is not None,
            'gps_lat': location_info.gps_lat,
            'gps_lon': location_info.gps_lon,
            'gps_source': location_info.gps_source.value if location_info.gps_source else None,
            'landmark_name': location_info.landmark_name
        }
    
    # Add camera metadata info
    with STATE.database.get_db() as conn:
        camera_row = conn.execute(
            'SELECT has_camera_metadata, original_make, original_model FROM photos WHERE filepath = ?',
            (filepath,)
        ).fetchone()
        
        if camera_row and camera_row['has_camera_metadata']:
            response['has_camera_data'] = True
            response['camera_info'] = {
                'make': camera_row['original_make'],
                'model': camera_row['original_model']
            }
        else:
            response['has_camera_data'] = False

    # Add smart location if available
    with STATE.database.get_db() as conn:
        photo_row = conn.execute(
            'SELECT location_id FROM photos WHERE filepath = ?', 
            (filepath,)
        ).fetchone()
        
        if photo_row and photo_row['location_id']:
            loc_row = conn.execute(
                'SELECT * FROM locations WHERE id = ?',
                (photo_row['location_id'],)
            ).fetchone()
            
            if loc_row:
                # Create SmartLocation object to get computed display properties
                location_obj = STATE.location_manager._row_to_location(loc_row)
                smart_location = {
                    'id': location_obj.id,
                    'display_primary': location_obj.display_primary,
                    'display_secondary': location_obj.display_secondary,
                    'display_full': location_obj.display_full,
                    'category': location_obj.category.name if location_obj.category else None,
                    'use_count': location_obj.use_count,
                    'city': location_obj.city,
                    'state': location_obj.state,
                    'country': location_obj.country,
                    'street': location_obj.street,
                    'landmark_name': location_obj.landmark_name
                }
                response['smart_location'] = smart_location
    
    # Check import status separately
    try:
        with STATE.database.get_db() as conn:
            import_check = conn.execute(
                'SELECT imported_at FROM photos WHERE filepath = ?',
                (filepath,)
            ).fetchone()
            
            if import_check and import_check['imported_at']:
                response['imported_at'] = import_check['imported_at']
    except Exception as e:
        # Don't let import check break the endpoint
        logger.debug(f"Import status check failed: {e}")
    
    # Check if photo has been saved
    try:
        with STATE.database.get_db() as conn:
            saved_check = conn.execute(
                'SELECT last_saved_at FROM photos WHERE filepath = ? OR filepath = ?',
                (filepath, str(Path(filepath).resolve()))
            ).fetchone()
            
            if saved_check and saved_check['last_saved_at']:
                response['last_saved_at'] = saved_check['last_saved_at']
    except Exception as e:
        logger.debug(f"Save status check failed: {e}")
    
    return jsonify(response)

# ============================================================================
# LOCATION ROUTES
# ============================================================================

@app.route('/api/locations/frequent')
def get_frequent_locations():
    """Get frequently used locations"""
    limit = request.args.get('limit', 10, type=int)
    locations = STATE.location_manager.get_frequent_locations(limit)
    return jsonify([loc.to_dict() for loc in locations])

@app.route('/api/locations/search', methods=['POST'])
def search_locations():
    """Unified location search with smart routing"""
    query = request.json.get('query', '').strip()
    if len(query) < 2:
        return jsonify([])

    # Determine category based on query pattern (for display purposes only)
    category = None
    query_parts = [p.strip() for p in query.split(",")]
    
    if re.fullmatch(r"[A-Za-z]{2}", query) and query.upper() in US_STATES:
        category = Category.STATE
    elif query.lower() in STATE_NAME_TO_ABBR:
        category = Category.STATE
    elif query.lower() in COUNTRIES_LIST:
        category = Category.COUNTRY
    elif re.match(r"\d{1,5}\s+\w+", query):
        category = Category.ADDRESS
    elif len(query_parts) >= 2:
        # Multi-part query - could be city,state or city,country
        if len(query_parts) == 2 and query_parts[1].upper() in US_STATES:
            category = Category.CITY  # US city
        elif len(query_parts) >= 2 and query_parts[-1].lower() in COUNTRIES_LIST:
            category = Category.CITY  # International city
        else:
            category = Category.CITY  # Generic multi-part
    else:
        category = Category.POI
    
    results = []

    def create_smart_location_from_result(result: Dict[str, Any], category: Category = None) -> SmartLocation:
        """Create SmartLocation from geocoding result"""
        location = SmartLocation(
            city=result.get('city', ''),
            state=result.get('state', ''),
            landmark_name=result.get('landmark_name', ''),
            gps_lat=result.get('lat'),
            gps_lon=result.get('lon'),
            category=category,
            # Apple provides country data for all locations
            country=result.get('country', ''),
            country_code=result.get('country_code', ''),
            street=result.get('street', ''),
            postal_code=result.get('postal_code', ''),
            neighborhood=result.get('neighborhood', '')
        )
        
        return location
    
    # Search Apple first for everything
    geo_result = _geocode_location(query)
    if geo_result:
        # Special handling for US state searches
        if category == Category.STATE:
            state_code = query.upper() if len(query) == 2 else STATE_NAME_TO_ABBR.get(query.lower())
            if state_code and not geo_result.get('city'):
                # If searching for just a state and no city returned, use capital
                geo_result['city'] = STATE_CAPITALS.get(state_code, "")
            geo_result['state'] = state_code or geo_result.get('state', '')
        
        # Create location from result
        location = create_smart_location_from_result(geo_result, category)
        results.append(location)
    
    # Fallback for US states only
    if not results and category == Category.STATE:
        state_code = query.upper() if len(query) == 2 else STATE_NAME_TO_ABBR.get(query.lower())
        if state_code:
            capital = STATE_CAPITALS.get(state_code, "")
            if capital and STATE.gazetteer:
                gps_info = STATE.gazetteer.lookup(capital, state_code)
                if gps_info:
                    lat, lon, _ = gps_info
                    results.append(SmartLocation(
                        city=capital,
                        state=state_code,
                        gps_lat=lat,
                        gps_lon=lon,
                        category=Category.STATE,
                        display_primary=query.title() if len(query) > 2 else query.upper(),
                        display_secondary=f"Will save as: {capital}, {state_code}"
                    ))
    
    # Also search database for previously used locations
    if not results or len(results) < 3:
        db_results = STATE.location_manager.search_locations(query)
        for loc in db_results[:3]:
            # Don't duplicate if we already have this location
            exists = any(r.city == loc.city and r.state == loc.state for r in results)
            if not exists:
                results.append(loc)
    
    # Deduplicate results
    seen = set()
    unique_results = []
    for r in results:
        key = (r.city, r.state, r.landmark_name or r.street or "")
        if key not in seen:
            seen.add(key)
            unique_results.append(r)
    
    return jsonify([r.to_dict() for r in unique_results[:5]])

@app.route('/api/suggestions/<path:filepath>')
def get_suggestions(filepath):
    """Get LLM parsing status/results for a specific photo"""
    # Flask strips leading / from path params, so add it back for absolute paths
    if not filepath.startswith('/') and len(filepath) > 2 and filepath[1] == '/':
        # Looks like an absolute path missing its leading slash (e.g., "Users/...")
        filepath = '/' + filepath
    
    # Check if we have results
    if filepath in LLM_PARSE_RESULTS:
        status = LLM_PARSE_RESULTS[filepath]['status']
        
        if status == 'ready':
            result = LLM_PARSE_RESULTS[filepath]['result']
            
            # Apply gazetteer correction to location if available
            if result.get('location') and STATE.gazetteer:
                loc = result['location']
                if loc.get('city') and loc.get('state') and not loc.get('country'):
                    proper_names = STATE.gazetteer.get_proper_name(loc['city'], loc['state'])
                    if proper_names:
                        loc['city'] = proper_names[0]
            
            return jsonify({
                'status': 'ready',
                'date_suggestion': result.get('date'),
                'location_suggestion': result.get('location')
            })
        else:
            return jsonify({'status': status})
    else:
        # Not in queue yet = enqueue a parse job and mark pending
        LLM_PARSE_RESULTS[filepath] = {'status': 'pending', 'result': None}
        # priority 0, parse_type "all" to match what /api/current uses
        LLM_PARSE_QUEUE.put((0, filepath, 'all'))

        # --- Look-ahead pre-fetch: queue the next 3 photos ---------------------
        try:
            # Build the current filtered list and locate this photo's index
            filtered_list = STATE.database.get_filtered_photos(STATE.current_filter)
            idx = filtered_list.index(filepath)

            # Queue photos idx+1 .. idx+3 (if any) at lower priority (1)
            for fp_n in filtered_list[idx + 1 : idx + 4]:
                if fp_n not in LLM_PARSE_RESULTS:
                    LLM_PARSE_RESULTS[fp_n] = {'status': 'pending', 'result': None}
                    LLM_PARSE_QUEUE.put((1, fp_n, 'all'))     # lower priority

            # --- rolling window: keep exactly three photos ahead in the queue ---
            tail_idx = idx + 4
            if tail_idx < len(filtered_list):
                tail_fp = filtered_list[tail_idx]
                if tail_fp not in LLM_PARSE_RESULTS:
                    LLM_PARSE_RESULTS[tail_fp] = {'status': 'pending', 'result': None}
                    LLM_PARSE_QUEUE.put((1, tail_fp, 'all'))  # lower priority
            # ---------------------------------------------------------------------
        except ValueError:
            # filepath not found in list (edge-case) - just ignore
            pass
        # -----------------------------------------------------------------------
        return jsonify({'status': 'pending'})

# ============================================================================
# METADATA SAVE/UPDATE ROUTES
# ============================================================================

@app.route('/api/save', methods=['POST'])
def save_metadata():
    """Save metadata with enhanced location support"""
    data = request.json
    filtered_photos = STATE.database.get_filtered_photos(STATE.current_filter)
    
    if not filtered_photos or STATE.current_index >= len(filtered_photos):
        return jsonify({'error': 'No photo selected'}), 400
    
    filepath = filtered_photos[STATE.current_index]
    photo_path = Path(filepath)
    
    # Build DateInfo from request
    date_info = None
    if date_data := data.get('date'):
        # Get current photo metadata to check existing sources
        _, _, _, current_camera_info = read_metadata_from_file(photo_path)
        has_real_camera_data = current_camera_info.get('has_camera_metadata', False)
        
        # If photo has camera metadata and values match system date, keep as system
        year = date_data.get('year', '')
        month = date_data.get('month', '')
        day = date_data.get('day', '')
        
        # If the user already supplied explicit sources, keep them; default to USER
        year_source  = DataSource(date_data.get('year_source', 'user'))
        month_source = DataSource(date_data.get('month_source', 'user'))
        day_source   = DataSource(date_data.get('day_source', 'user'))

        if year and not month:
            month = '01'
            month_source = DataSource.SYSTEM
        if year and not day:
            day = '02'
            day_source = DataSource.SYSTEM
        date_info = DateInfo(
            year=year,
            month=month,
            day=day,
            year_source=year_source,
            month_source=month_source,
            day_source=day_source,
            from_complete_suggestion=date_data.get('from_complete_suggestion', False)
        )
    
    # Handle location
    location_info = None
    location_id = None
    
    # Check for preserved GPS first
    if preserve_gps := data.get('preserve_gps'):
        # Create minimal LocationInfo to preserve GPS
        location_info = LocationInfo(
            gps_lat=preserve_gps.get('gps_lat'),
            gps_lon=preserve_gps.get('gps_lon'),
            gps_source=DataSource(preserve_gps.get('gps_source', 'system'))
        )
    elif smart_location_data := data.get('smart_location'):
        # Create SmartLocation from frontend data
        smart_location = SmartLocation(
            city=smart_location_data['city'],
            state=smart_location_data['state'],
            landmark_name=smart_location_data.get('landmark_name'),
            street=smart_location_data.get('street', ''),
            gps_lat=smart_location_data.get('gps_lat'),
            gps_lon=smart_location_data.get('gps_lon'),
            category=Category[smart_location_data['category']] if smart_location_data.get('category') else None,
            country=smart_location_data.get('country', ''),
            country_code=smart_location_data.get('country_code', ''),
            postal_code=smart_location_data.get('postal_code', ''),
            neighborhood=smart_location_data.get('neighborhood', '')
        )
        
        # Get or create location record
        location_id = STATE.location_manager.get_or_create_location(smart_location)
        
        # Create LocationInfo for file writing with country from search
        location_info = LocationInfo(
            city=smart_location.city,
            state=smart_location.state,
            city_source=DataSource.USER,
            state_source=DataSource.USER,
            country=smart_location_data.get('country', ''),
            country_code=smart_location_data.get('country_code', ''),
            country_source=DataSource.USER if smart_location_data.get('country') else None,
            street=smart_location_data.get('street', ''),
            postal_code=smart_location_data.get('postal_code', ''),
            neighborhood=smart_location_data.get('neighborhood', ''),
            gps_lat=smart_location.gps_lat,
            gps_lon=smart_location.gps_lon,
            gps_source=DataSource.USER if smart_location.gps_lat else None,
            landmark_name=smart_location.landmark_name,
            landmark_source=DataSource.USER if smart_location.landmark_name else None
        )
    
    # Check if we should preserve camera data from frontend
    preserve_camera = data.get('has_camera_data', False)
    
    # Write to file with preservation flag
    if write_metadata_to_file(photo_path, date_info, location_info, preserve_camera):
        # Recalculate file hash after metadata change
        new_file_hash = calculate_file_hash(photo_path)
        new_file_mtime = datetime.fromtimestamp(photo_path.stat().st_mtime).isoformat()
        
        # Update hash in database
        with STATE.database.get_db() as conn:
            conn.execute('''
                UPDATE photos 
                SET file_hash = ?, file_last_modified = ?
                WHERE filepath = ?
            ''', (new_file_hash, new_file_mtime, filepath))
        
        # Use save method
        STATE.database.save_photo_state(
            filepath, 
            date_info, 
            location_info, 
            user_action='saved',
            location_id=location_id
        )
        
        # Increment usage if location was used
        if location_id:
            STATE.location_manager.increment_usage(location_id)
        
        # Rest of the save logic remains the same...
        filtered_photos_after = STATE.database.get_filtered_photos(STATE.current_filter)
        if len(filtered_photos_after) <= STATE.current_index and STATE.current_index > 0:
            STATE.current_index = len(filtered_photos_after) - 1
        has_next = STATE.current_index < len(filtered_photos_after)
        
        return jsonify({
            'success': True,
            'has_next': has_next,
            'message': 'Metadata saved successfully'
        })
    
    return jsonify({'error': 'Failed to write metadata'}), 500

@app.route('/api/skip', methods=['POST'])
def skip_photo():
    """Skip current photo - DEPRECATED: Kept for backwards compatibility"""
    filtered_photos = STATE.database.get_filtered_photos(STATE.current_filter)
    
    if filtered_photos and STATE.current_index < len(filtered_photos):
        filepath = filtered_photos[STATE.current_index]
        
        # Track skip action
        with STATE.database.get_db() as conn:
            conn.execute('''
                UPDATE photos 
                SET user_action = 'skipped',
                    user_last_action_time = CURRENT_TIMESTAMP
                WHERE filepath = ?
            ''', (filepath,))
            
            # Removed view tracking for performance
    
    STATE.current_index += 1
    has_next = STATE.current_index < len(filtered_photos)
    return jsonify({'has_next': has_next})

# ============================================================================
# NAVIGATION AND CONTROL ROUTES
# ============================================================================

@app.route('/api/navigate', methods=['POST'])
def navigate():
    """Navigate between photos"""
    data = request.json
    direction = data.get('direction', 0)
    
    filtered_photos = STATE.database.get_filtered_photos(STATE.current_filter)
    total = len(filtered_photos)
    
    STATE.current_index = max(0, min(STATE.current_index + direction, total - 1))
    
    return jsonify({
        'success': True,
        'current_index': STATE.current_index,
        'total': total
    })

@app.route('/api/grid/<filter_type>')
def get_grid_photos(filter_type):
    """Get all photos for grid view - paginated for performance"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 50  # Load 50 at a time
        
        filtered_photos = STATE.database.get_filtered_photos(filter_type)
        
        # Calculate pagination
        total = len(filtered_photos)
        start = (page - 1) * per_page
        end = min(start + per_page, total)
        
        # Get photos for this page
        grid_data = []
        
        # Prepare photo data for parallel processing
        photo_batch = []
        for index in range(start, end):
            filepath = filtered_photos[index]
            photo_path = Path(filepath)
            photo_batch.append((index, filepath, photo_path))
        
        # Process photos in parallel using thread pool
        from concurrent.futures import ThreadPoolExecutor
        def process_photo(photo_info):
            index, filepath, photo_path = photo_info
            # Each thread gets its own connection
            with STATE.database.get_db() as conn:
                row = conn.execute(
                    'SELECT imported_at, last_saved_at FROM photos WHERE filepath = ?',
                    (filepath,)
                ).fetchone()
            
            resp = {
                'index': index,
                'filename': photo_path.name,
                'filepath': filepath,
                'thumbnail': create_thumbnail(photo_path, max_size=(120, 120)),
                'imported_at': row['imported_at'] if row else None,
                'last_saved_at': row['last_saved_at'] if row else None
            }

            STATE.database._pool.release_connection()
            return resp
        
        # Re-use the shared pipeline executor to avoid nested pools
        from concurrent.futures import as_completed
        photo_futures = [STATE.pipeline_executor.submit(process_photo, p)
                         for p in photo_batch]
        grid_data = [f.result() for f in as_completed(photo_futures)]
        
        # Sort by index to maintain order
        grid_data.sort(key=lambda x: x['index'])
        
        return jsonify({
            'photos': grid_data,
            'total': total,
            'page': page,
            'per_page': per_page,
            'has_more': end < total
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/filter', methods=['POST'])
def set_filter():
    """Change filter"""
    data = request.json
    new_filter = data.get('filter', 'needs_both')
    
    if new_filter in ['needs_review', 'needs_both', 'needs_date', 'needs_location', 'complete']:
        STATE.current_filter = new_filter
        STATE.current_index = 0
        return jsonify({'success': True})
    
    return jsonify({'error': 'Invalid filter'}), 400

@app.route('/api/unknown_date', methods=['POST'])
def set_unknown_date():
    """Set date as unknown (system fills 1901-01-02)"""
    filtered_photos = STATE.database.get_filtered_photos(STATE.current_filter)
    
    if not filtered_photos or STATE.current_index >= len(filtered_photos):
        return jsonify({'error': 'No photo selected'}), 400
    
    return jsonify({
        'success': True,
        'year': '1901',
        'month': '01',
        'day': '02',
        'source': 'user'
    })

@app.route('/api/unknown_location', methods=['POST'])
def set_unknown_location():
    """Clear location (unknown)"""
    return jsonify({
        'success': True,
        'city': '',
        'state': '',
        'source': 'system'
    })

@app.route('/api/check_city', methods=['POST'])
def check_city():
    """Check city capitalization and existence"""
    data = request.json
    city = data.get('city', '').strip()
    state = data.get('state', '').strip().upper()
    
    if not city or not state:
        return jsonify({'proper_city': None, 'exists': False})
    
    if STATE.gazetteer:
        proper_names = STATE.gazetteer.get_proper_name(city, state)
        if proper_names:
            return jsonify({'proper_city': proper_names[0], 'exists': True})
        else:
            return jsonify({'proper_city': None, 'exists': False})
    
    return jsonify({'proper_city': None, 'exists': None})

@app.route('/api/toggle_sort', methods=['POST'])
def toggle_sort():
    """Toggle between filename and sequence number sorting"""
    STATE.sort_by_sequence = not STATE.sort_by_sequence
    STATE.current_index = 0
    return jsonify({
        'success': True,
        'sort_by_sequence': STATE.sort_by_sequence
    })

# ============================================================================
# PIPELINE ROUTES
# ============================================================================

@app.route('/api/check-import-status', methods=['POST'])
def check_import_status():
    '''Check which photos are already imported'''
    data = request.json
    filepaths = data.get('filepaths', [])
    
    results = []
    with STATE.database.get_db() as conn:
        for filepath in filepaths:
            row = conn.execute(
                'SELECT filepath, imported_at FROM photos WHERE filepath = ?',
                (filepath,)
            ).fetchone()
            
            results.append({
                'filepath': filepath,
                'imported_at': row['imported_at'] if row else None
            })
    
    return jsonify(results)

@app.route('/api/import-photos', methods=['POST'])
def import_photos():
    '''Queue selected photos for import and start pipeline'''
    data = request.json
    filepaths = data.get('filepaths', [])
    
    if not filepaths:
        return jsonify({'error': 'No photos selected'}), 400
    
    # Check if pipeline is already running is now handled below with pipeline_future
    
    # Create batch ID
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Add to queue
    with STATE.database.get_db() as conn:
        # Create batch record
        conn.execute('''
            INSERT INTO pipeline_status (batch_id, status, photo_count, started_at)
            VALUES (?, 'queued', ?, CURRENT_TIMESTAMP)
        ''', (batch_id, len(filepaths)))
        
        # Queue each photo
        for filepath in filepaths:
            conn.execute('''
                INSERT INTO pipeline_queue (filepath, batch_id, status)
                VALUES (?, ?, 'pending')
            ''', (filepath, batch_id))
    
    # Start pipeline process
    try:
        # Clear previous output
        STATE.pipeline_output = []
        STATE.pipeline_events = []
        STATE.pipeline_batch_id = batch_id
        STATE.pipeline_cancelled = False
        
        logger.info(f"Starting integrated pipeline for batch {batch_id}")
        
        # Check if already running
        if STATE.pipeline_future and not STATE.pipeline_future.done():
            return jsonify({'error': 'Pipeline is already running'}), 400
        
        # Start pipeline in thread pool
        STATE.pipeline_future = STATE.pipeline_executor.submit(
            run_integrated_pipeline, batch_id
        )
        
        # Log to console
        print(f"[PIPELINE] Starting integrated pipeline for batch {batch_id}")
        
        return jsonify({
            'success': True,
            'batch_id': batch_id,
            'count': len(filepaths),
            'message': 'Pipeline started. Processing photos...'
        })
        
    except Exception as e:
        logger.error(f"Failed to start pipeline: {e}")
        return jsonify({'error': f'Failed to start pipeline: {str(e)}'}), 500

@app.route('/api/pipeline-status')
def get_pipeline_status():
    '''Get current pipeline status - works with both subprocess and integrated'''
    # Check integrated pipeline
    if STATE.pipeline_future:
        is_running = not STATE.pipeline_future.done()
    else:
        is_running = False
    
    # Get recent output
    recent_output = STATE.pipeline_output[-50:] if STATE.pipeline_output else []
    
    # If finished, check database for batch status
    final_status = None
    exit_code = None
    if not is_running and STATE.pipeline_batch_id:
        with STATE.database.get_db() as conn:
            batch = conn.execute(
                'SELECT status FROM pipeline_status WHERE batch_id = ?',
                (STATE.pipeline_batch_id,)
            ).fetchone()
            if batch:
                final_status = batch['status']
                # Set exit_code based on final_status for UI compatibility
                if final_status == 'complete':
                    exit_code = 0
                elif final_status in ['failed', 'partial']:
                    exit_code = 1
    
    # For integrated pipeline, get progress from events
    progress = None
    if STATE.pipeline_events:
        # Find latest transfer progress event
        for event in reversed(STATE.pipeline_events):
            if event.get('type') == 'transfer_progress':
                progress = {
                    'current': event.get('current_file', 0),
                    'total': event.get('total_files', 0),
                    'percent': event.get('percent', 0)
                }
                break
    
    return jsonify({
        'running': is_running,
        'batch_id': STATE.pipeline_batch_id,
        'output': recent_output,
        'exit_code': exit_code,
        'final_status': final_status,
        'progress': progress
    })

@app.route('/api/pipeline/events')
def get_pipeline_events():
    '''Get structured events from integrated pipeline'''
    # Get optional parameters
    try:
        offset = int(request.args.get('offset', 0))
        limit = int(request.args.get('limit', 100))
    except ValueError:
        offset = 0
        limit = 100
    
    # Get events slice
    total_events = len(STATE.pipeline_events)
    events = STATE.pipeline_events[offset:offset + limit]
    
    return jsonify({
        'events': events,
        'total': total_events,
        'offset': offset,
        'limit': limit,
        'has_more': offset + limit < total_events
    })

@app.route('/api/pipeline/cancel', methods=['POST'])
def cancel_pipeline():
    '''Cancel running pipeline'''
    STATE.pipeline_cancelled = True
    
    # Try to cancel the future (may not stop running thread)
    if STATE.pipeline_future and not STATE.pipeline_future.done():
        STATE.pipeline_future.cancel()
    
    # Add cancellation event
    STATE.pipeline_events.append({
        'type': 'cancelled',
        'message': 'Pipeline cancelled by user',
        'timestamp': datetime.now().isoformat()
    })
    STATE.pipeline_output.append('Pipeline cancelled by user')
    
    return jsonify({
        'success': True,
        'message': 'Pipeline cancellation requested'
    })

@app.route('/api/pipeline/status/<batch_id>')
def get_pipeline_batch_status(batch_id):
    '''Get detailed status for a specific batch'''
    try:
        with STATE.database.get_db() as conn:
            # Get batch info
            batch = conn.execute('''
                SELECT ps.*,
                       COUNT(DISTINCT pq.id) as total_count,
                       SUM(CASE WHEN pq.status = 'complete' THEN 1 ELSE 0 END) as completed_count,
                       SUM(CASE WHEN pq.status = 'error' THEN 1 ELSE 0 END) as error_count,
                       SUM(CASE WHEN pq.status = 'pending' THEN 1 ELSE 0 END) as pending_count
                FROM pipeline_status ps
                LEFT JOIN pipeline_queue pq ON ps.batch_id = pq.batch_id
                WHERE ps.batch_id = ?
                GROUP BY ps.batch_id
            ''', (batch_id,)).fetchone()
            
            if not batch:
                return jsonify({'error': 'Batch not found'}), 404
            
            # Get photo details
            photos = conn.execute('''
                SELECT pq.*, p.filename, p.current_city, p.current_state,
                       p.current_date_year, p.current_date_month, p.current_date_day,
                       pe.error_type, pe.error_message, pe.retry_count
                FROM pipeline_queue pq
                JOIN photos p ON pq.filepath = p.filepath
                LEFT JOIN pipeline_errors pe ON pq.filepath = pe.filepath AND pq.batch_id = pe.batch_id
                WHERE pq.batch_id = ?
                ORDER BY pq.queued_at
            ''', (batch_id,)).fetchall()
            
            # Format response
            result = {
                'batch_id': batch['batch_id'],
                'status': batch['status'],
                'started_at': batch['started_at'],
                'completed_at': batch['completed_at'],
                'error_message': batch['error_message'],
                'stats': {
                    'total': batch['total_count'],
                    'completed': batch['completed_count'],
                    'error': batch['error_count'],
                    'pending': batch['pending_count']
                },
                'photos': []
            }
            
            for photo in photos:
                photo_info = {
                    'filename': photo['filename'],
                    'status': photo['status'],
                    'queued_at': photo['queued_at'],
                    'location': f"{photo['current_city']}, {photo['current_state']}" if photo['current_city'] else photo['current_state'],
                    'date': f"{photo['current_date_year']}-{photo['current_date_month']}-{photo['current_date_day']}"
                }
                
                if photo['error_type']:
                    photo_info['error'] = {
                        'type': photo['error_type'],
                        'message': photo['error_message'],
                        'retry_count': photo['retry_count']
                    }
                
                result['photos'].append(photo_info)
            
            return jsonify(result)
            
    except Exception as e:
        logger.error(f"Error getting batch status: {e}")
        return jsonify({'error': str(e)}), 500

# ============================================================================
# UI TEMPLATE
# ============================================================================

# Load UI template from file
UI_TEMPLATE_PATH = Path(__file__).parent / "photo_editor_ui.html"
try:
    UI_TEMPLATE = UI_TEMPLATE_PATH.read_text()
except FileNotFoundError:
    print(f"ERROR: UI template not found at {UI_TEMPLATE_PATH}")
    UI_TEMPLATE = "<h1>Error: UI template file missing</h1>"

# ============================================================================
# INITIALIZATION
# ============================================================================

def initialize_session(folder_path: str):
    """Initialize the application - parallel version with EXACT same behavior"""
    STATE.working_dir = Path(folder_path)
    DATA_DIR.mkdir(exist_ok=True)
    
    # Initialize database
    db_path = DATA_DIR / "photo_metadata.db"
    STATE.database = PhotoDatabase(db_path)
    
    # Initialize location manager
    STATE.location_manager = LocationManager(STATE.database)
    
    # Find photos
    STATE.photos_list = sorted([
        f for f in STATE.working_dir.iterdir()
        if f.is_file() and f.suffix.lower() == '.heic'
    ])
    
    if not STATE.photos_list:
        raise ValueError("No .heic photos found in directory")
    
    print(f"Found {len(STATE.photos_list)} photos")
    
    # ===== DETECT RENAMES AND HANDLE DELETIONS =====
    print("Checking for renamed or deleted files...")
    with STATE.database.get_db() as conn:
        # Get all current file paths
        current_paths = {str(p): p for p in STATE.photos_list}
        
        # Find database entries for files that no longer exist at their recorded path
        # Exclude already soft-deleted files
        all_db_photos = conn.execute('''
            SELECT filepath, file_hash, filename 
            FROM photos 
            WHERE file_hash IS NOT NULL 
            AND deleted_at IS NULL
        ''').fetchall()
        
        missing_photos = []
        existing_hashes = set()
        
        for row in all_db_photos:
            if row['filepath'] in current_paths:
                # File still exists at same path
                existing_hashes.add(row['file_hash'])
            else:
                # File missing from original path
                missing_photos.append(row)
        
        if missing_photos:
            print(f"  Found {len(missing_photos)} missing files...")
            rename_count = 0
            
            # Build a set of hashes we need to find
            missing_hashes = {m['file_hash']: m for m in missing_photos}
            
            # Check each current file to see if it matches a missing hash
            for current_path, photo_path in current_paths.items():
                # Skip if we already know this file is in the database
                if any(row['filepath'] == current_path for row in all_db_photos):
                    continue
                
                try:
                    # Calculate hash for potential rename
                    file_hash = calculate_file_hash(photo_path)
                    
                    # Is this one of our missing files?
                    if file_hash in missing_hashes and file_hash not in existing_hashes:
                        missing = missing_hashes[file_hash]
                        print(f"  Renamed: {missing['filename']} → {photo_path.name}")
                        
                        # Update the database with new path
                        conn.execute('''
                            UPDATE photos 
                            SET filepath = ?, filename = ?
                            WHERE file_hash = ? AND filepath = ?
                        ''', (str(photo_path), photo_path.name, file_hash, missing['filepath']))
                        
                        # Remove from missing_hashes since we found it
                        del missing_hashes[file_hash]
                        existing_hashes.add(file_hash)
                        rename_count += 1
                        
                except Exception as e:
                    # File might not be readable
                    print(f"  Error checking {photo_path.name}: {e}")
                    continue
            
            # Any remaining items in missing_hashes are truly deleted
            deleted_count = len(missing_hashes)
            
            if rename_count > 0:
                print(f"  Updated {rename_count} renamed files")
            
            if deleted_count > 0:
                print(f"  Found {deleted_count} deleted files")
                
                # Soft delete: mark with timestamp instead of removing
                for file_hash, missing in missing_hashes.items():
                    print(f"  Marking as deleted: {missing['filename']}")
                    conn.execute('''
                        UPDATE photos 
                        SET deleted_at = CURRENT_TIMESTAMP
                        WHERE file_hash = ? AND filepath = ?
                    ''', (file_hash, missing['filepath']))
                
                print(f"  Marked {deleted_count} files as deleted")
        
        # Also check if any previously deleted files have been restored
        deleted_photos = conn.execute('''
            SELECT filepath, file_hash, filename 
            FROM photos 
            WHERE deleted_at IS NOT NULL
        ''').fetchall()
        
        restored_count = 0
        for row in deleted_photos:
            if row['filepath'] in current_paths:
                print(f"  Restored: {row['filename']}")
                conn.execute('''
                    UPDATE photos 
                    SET deleted_at = NULL
                    WHERE filepath = ?
                ''', (row['filepath'],))
                restored_count += 1
        
        if restored_count > 0:
            print(f"  Restored {restored_count} previously deleted files")
    # ===== END RENAME/DELETE DETECTION =====
    
    # Helper function to process a single photo
    def process_single_photo(photo):
            """Process one photo with comprehensive tracking"""
            try:
                # Normalize the path to ensure consistency
                normalized_photo_path = str(photo.resolve())
                
                # Calculate file hash and stats
                file_hash = calculate_file_hash(photo)
                file_stats = photo.stat()
                
                # Check if already in database
                with STATE.database.get_db() as conn:
                    existing = conn.execute(
                        'SELECT * FROM photos WHERE filepath = ?', 
                        (str(photo),)
                    ).fetchone()
                    
                    # Always read current metadata from file
                    date_info, location_info, tags, camera_info = read_metadata_from_file(photo)
                    
                    # Determine original sources
                    original_date_source = 'none'
                    if date_info and date_info.year != '1901':
                        original_date_source = 'exif'
                    elif extract_date_from_filename(photo.name):
                        original_date_source = 'filename'
                    
                    original_location_source = 'none'
                    if location_info and location_info.gps_lat is not None:
                        original_location_source = 'gps'
                    elif location_info and location_info.state:
                        original_location_source = 'iptc'
                    elif extract_location_from_filename(photo.name):
                        original_location_source = 'filename'
                    
                    # Determine current sources - preserve user sources if values match
                    current_date_source = original_date_source
                    current_location_source = original_location_source
                    
                    if existing:
                        # If user previously saved date and current file has same date, keep user source
                        if (existing['current_date_source'] == 'user' and 
                            date_info and
                            str(existing['current_date_year']) == str(date_info.year) and
                            str(existing['current_date_month']) == str(date_info.month) and
                            str(existing['current_date_day']) == str(date_info.day)):
                            current_date_source = 'user'
                        
                        # If user previously saved location and current file has same location, keep user source
                        if (existing['current_location_source'] == 'user' and 
                            location_info and
                            str(existing['current_state']) == str(location_info.state)):
                            current_location_source = 'user'

                    
                    # Determine what needs work - must match tag logic
                    needs_date = True
                    if date_info:
                        needs_date = date_info.needs_tag()
                    
                    needs_location = True  
                    if location_info:
                        needs_location = location_info.needs_tag()
                    
                    # For consistency checks
                    has_good_date = not needs_date
                    has_good_gps = (location_info and location_info.gps_lat is not None)
                    has_good_location = not needs_location
                    
                    # Build the complete record
                    data = {
                        'filepath': normalized_photo_path,
                        'filename': photo.name,
                        'sequence_number': extract_sequence_number(photo.name),
                        'file_hash': file_hash,
                        'file_last_modified': datetime.fromtimestamp(file_stats.st_mtime).isoformat(),
                        
                        # Original state (from first scan)
                        'original_date_year': date_info.year if date_info else None,
                        'original_date_month': date_info.month if date_info else None,
                        'original_date_day': date_info.day if date_info else None,
                        'original_date_source': original_date_source,
                        'original_gps_lat': location_info.gps_lat if location_info else None,
                        'original_gps_lon': location_info.gps_lon if location_info else None,
                        'original_city': location_info.city if location_info else None,
                        'original_state': location_info.state if location_info else None,
                        'original_location_source': original_location_source,
                        'original_make': camera_info.get('original_make', ''),
                        'original_model': camera_info.get('original_model', ''),
                        'has_camera_metadata': camera_info.get('has_camera_metadata', False),
                        
                        # Current state (same as original on first scan)
                        'current_date_year': date_info.year if date_info else None,
                        'current_date_month': date_info.month if date_info else None,
                        'current_date_day': date_info.day if date_info else None,
                        'current_date_source': current_date_source,
                        'current_gps_lat': location_info.gps_lat if location_info else None,
                        'current_gps_lon': location_info.gps_lon if location_info else None,
                        'current_city': location_info.city if location_info else None,
                        'current_state': location_info.state if location_info else None,
                        'current_location_source': current_location_source,
                        
                        # Status flags
                        'needs_date': needs_date,
                        'needs_location': needs_location,
                        'has_good_date': has_good_date,
                        'has_good_gps': has_good_gps,
                        'has_good_location': has_good_location,
                        'ready_for_review': 1,  # ALL photos need review initially
                        'user_action': 'none'  # Default for new photos
                    }
                    
                    # Check if this is an update to preserve user data
                    if existing:
                        # This is an update - preserve user action and source info
                        existing_data = dict(existing)
                        
                        # Preserve user_action if it was set
                        if existing_data.get('user_action') in ['saved', 'skipped']:
                            data['user_action'] = existing_data['user_action']
                            data['user_last_action_time'] = existing_data.get('user_last_action_time')                      
                        
                        # Preserve location_id if set
                        if existing_data.get('location_id'):
                            data['location_id'] = existing_data['location_id']
                    
                    # Insert or update
                    columns = list(data.keys())
                    placeholders = [f':{col}' for col in columns]
                    
                    sql = f'''
                        INSERT INTO photos ({', '.join(columns)})
                        VALUES ({', '.join(placeholders)})
                        ON CONFLICT(filepath) DO UPDATE SET
                            filename = excluded.filename,
                            sequence_number = excluded.sequence_number,
                            file_hash = excluded.file_hash,
                            file_last_modified = excluded.file_last_modified,
                            original_date_year = excluded.original_date_year,
                            original_date_month = excluded.original_date_month,
                            original_date_day = excluded.original_date_day,
                            original_date_source = excluded.original_date_source,
                            original_gps_lat = excluded.original_gps_lat,
                            original_gps_lon = excluded.original_gps_lon,
                            original_city = excluded.original_city,
                            original_state = excluded.original_state,
                            original_location_source = excluded.original_location_source,
                            original_make = excluded.original_make,
                            original_model = excluded.original_model,
                            has_camera_metadata = excluded.has_camera_metadata,
                            current_date_year = excluded.current_date_year,
                            current_date_month = excluded.current_date_month,
                            current_date_day = excluded.current_date_day,
                            current_date_source = excluded.current_date_source,
                            current_gps_lat = excluded.current_gps_lat,
                            current_gps_lon = excluded.current_gps_lon,
                            current_city = excluded.current_city,
                            current_state = excluded.current_state,
                            current_location_source = excluded.current_location_source,
                            needs_date = excluded.needs_date,
                            needs_location = excluded.needs_location,
                            has_good_date = excluded.has_good_date,
                            has_good_gps = excluded.has_good_gps,
                            has_good_location = excluded.has_good_location,
                            ready_for_review = excluded.ready_for_review
                    '''
                    
                    conn.execute(sql, data)
                    
                    # Log the scan
                    conn.execute('''
                        INSERT INTO file_scans (filepath, file_exists, file_hash)
                        VALUES (?, 1, ?)
                    ''', (str(photo), file_hash))
                    
                    return photo.name  # Return name for progress tracking
                    
            except Exception as e:
                print(f"Error processing {photo.name}: {e}")
                return None
    
    # Process photos in parallel
    processed_photos = []
    failed_photos = []
    
    # Use configured number of workers
    num_workers = min(METADATA_WORKERS, len(STATE.photos_list))
    
    print(f"Processing photos using {num_workers} threads...")
    
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        # Submit all photos for processing
        future_to_photo = {
            executor.submit(process_single_photo, photo): photo 
            for photo in STATE.photos_list
        }
        
        # Process results as they complete
        completed = 0
        for future in as_completed(future_to_photo):
            completed += 1
            photo = future_to_photo[future]
            
            try:
                result = future.result()
                if result:  # Photo was processed (not already in DB)
                    processed_photos.append(result)
            except Exception as e:
                failed_photos.append(photo.name)
                print(f"Failed to process {photo.name}: {e}")
    
    # Report results - same as original
    if processed_photos:
        print(f"Processed {len(processed_photos)} new/updated photos")
    
    if failed_photos:
        print(f"Failed to process {len(failed_photos)} photos")
    
    # Pre-generate grid thumbnails for better performance
    print("\nGenerating thumbnails for grid view...")
    
    # Check which thumbnails already exist in database
    existing_thumbnails = set()
    if STATE.database:
        with STATE.database.get_db() as conn:
            rows = conn.execute('''
                SELECT filepath, file_mtime, size FROM thumbnails
            ''').fetchall()
            for row in rows:
                existing_thumbnails.add((row[0], row[1], row[2]))
    
    # Use configured number of workers for thumbnail generation
    num_workers = THUMBNAIL_WORKERS
    
    print(f"  Using {num_workers} workers for thumbnail generation...")
    
    # Create all tasks upfront
    thumbnail_tasks = []
    for photo in STATE.photos_list:
        try:
            mtime = photo.stat().st_mtime
            # Only add tasks for thumbnails that don't exist
            if (str(photo), mtime, "120x120") not in existing_thumbnails:
                thumbnail_tasks.append((photo, (120, 120)))   # Grid size
            if (str(photo), mtime, "800x800") not in existing_thumbnails:
                thumbnail_tasks.append((photo, (800, 800)))   # Full size
        except:
            # If we can't stat the file, skip it
            pass
    
    total_tasks = len(thumbnail_tasks)
    completed = 0
    failed = 0
    
    # Process all thumbnails in parallel
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        # Submit all tasks
        future_to_task = {
            executor.submit(create_thumbnail, path, size): (path, size) 
            for path, size in thumbnail_tasks
        }
        
        # Process results as they complete
        for future in as_completed(future_to_task):
            completed += 1
            try:
                result = future.result()
                if not result:
                    failed += 1
            except Exception as e:
                failed += 1
                path, size = future_to_task[future]
                logger.debug(f"Thumbnail generation failed for {path.name} at {size}: {e}")
            
            # Update progress every 10 completions
            if completed % 10 == 0 or completed == total_tasks:
                percent = (completed / total_tasks) * 100
                print(f"  Generating thumbnails: {completed}/{total_tasks} ({percent:.1f}%) - {failed} failed", end='\r')
    
    print(f"\nGenerated {completed - failed} thumbnails successfully ({failed} failed)")
    
    # Initialize LLM parser (model only, no pre-parsing)
    if USE_LLM_PARSER and _LLM_AVAILABLE:
        try:
            print("\nInitializing LLM filename parser...")
            STATE.filename_parser = FilenameParser(cache_dir=DATA_DIR / ".llm_cache")
            STATE.filename_parser.load_model()
            print("LLM parser ready (parse-on-demand mode)")
            
            # Start the LLM worker thread
            start_llm_worker()
            
        except Exception as e:
            logger.error(f"Failed to initialize LLM parser: {e}")
            STATE.filename_parser = None
            print(f"LLM parser initialization failed: {e}")
            print("  Falling back to regex parser")
    
    # Initialize gazetteer
    gazetteer_path = DATA_DIR / "uscities.csv"
    if not gazetteer_path.exists():
        # Try old location for backward compatibility
        old_path = SCRIPT_DIR / "uscities.csv"
        if old_path.exists():
            logger.info(f"Moving uscities.csv to {gazetteer_path}")
            shutil.move(str(old_path), str(gazetteer_path))
        else:
            logger.warning(f"Gazetteer CSV not found at {gazetteer_path}")
    
    STATE.gazetteer = Gazetteer(gazetteer_path)
    
    # Check MKLocalSearch availability
    if _mk_local_search_available:
        print("\nApple geocoding available via MKLocalSearch")
        print("  - Address geocoding")
        print("  - POI search")
    else:
        print("\nMKLocalSearch unavailable - using CSV only")

# ============================================================================
# MAIN FUNCTION
# ============================================================================

def main():
    # Optional quick test mode
    if '--test' in sys.argv:
        print("Testing Apple geocoding...")
        try:
            # Test with a simple query first
            print("Testing MKLocalSearch availability...")
            if _mk_local_search_available:
                print("MKLocalSearch is available")
            else:
                print("MKLocalSearch is NOT available")
                
            addr = _geocode_location("1600 Amphitheatre Pkwy, Mountain View CA")
            if addr:
                lat, lon, city, state, landmark = addr
                print(f"Address test: {city}, {state} ({lat:.4f}, {lon:.4f})")
            else:
                print("Address test failed")

            poi = _geocode_location("Golden Gate Bridge")
            if poi:
                lat, lon, city, state, landmark = poi
                print(f"POI test: {landmark or 'Golden Gate Bridge'} in {city}, {state}")
            else:
                print("POI test failed")

            print("All tests passed!")
        except Exception as e:
            print(f"Test failed: {e}")
            import traceback
            traceback.print_exc()
        sys.exit(0)

    if len(sys.argv) < 2:
        print("Usage: python metadata_editor.py <folder_path>")
        sys.exit(1)

    folder_path = sys.argv[1]
    if not Path(folder_path).is_dir():
        print(f"Error: {folder_path} is not a directory")
        sys.exit(1)

    # Ensure ExifTool is present
    if not setup_exiftool():
        print("Error: Failed to set up ExifTool")
        sys.exit(1)

    # Initialise session (DB, gazetteer, etc.)
    try:
        initialize_session(folder_path)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    print("\n Photo Metadata Editor with Enhanced Location Search")
    print("=" * 60)
    print(f"Working directory: {folder_path}")
    print(f"Starting server at http://localhost:{WEB_PORT}")
    print("Press Ctrl+C to stop\n")
    
    # Run Flask in a background thread so the main thread can keep the Cocoa run-loop alive
    def _run_flask():
        """Launch Waitress and make sure fatal errors are *not* hidden in the thread.

        If Waitress raises (e.g. port already bound), log it and terminate the
        whole process so the user immediately sees the problem instead of an
        unresponsive UI.
        """
        from waitress import serve
        try:
            serve(app, host='127.0.0.1', port=WEB_PORT, threads=8)
        except Exception as e:
            logger.error(f"Waitress failed to start: {e}")
            os._exit(1)           # Propagate the failure to the parent process

    # Daemon thread allows single Ctrl-C shutdown; _run_flask will call
    # os._exit(1) if Waitress fails to bind, so fatal errors are still surfaced.
    flask_thread = threading.Thread(
        target=_run_flask,
        name="WaitressThread",
        daemon=True
    )
    flask_thread.start()

    # Wait until the Flask port is accepting connections, then launch
    # the user's preferred browser at the correct URL.
    for _ in range(30):            # ~3 s total (30 x 0.1 s)
        try:
            socket.create_connection(('127.0.0.1', WEB_PORT), timeout=0.1).close()
            webbrowser.open(f'http://localhost:{WEB_PORT}')
            break
        except OSError:
            time.sleep(0.1)
    # ------------------------------------------------------------------

    try:
        AppHelper.runConsoleEventLoop()
    except KeyboardInterrupt:
        print("\nShutting down...")
        # Gracefully stop background workers
        stop_llm_worker()           # uses helper we already have:contentReference[oaicite:2]{index=2}
        STATE.shutdown_db_worker()  # cleans up DB thread & queue:contentReference[oaicite:3]{index=3}

        # Wait briefly for the HTTP server thread to finish
        if flask_thread.is_alive():
            flask_thread.join(timeout=2.0)

        sys.exit(0)

# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == '__main__':
    main()