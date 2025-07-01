#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#     "openai",
# ]
# ///
"""
Integrated Photo Filename Generator with Lambda.ai Inference Enrichment
Generates test dataset and enriched training data in one run

Run with uv:
caffeinate -i ./filename_generator_LLM_enrich.py dataforfilegenerator.json
"""

import json
import random
import calendar
import getpass
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
from pathlib import Path
import sys
from openai import OpenAI

class GeographicTruthEngine:
    """Maintains relationships between locations to ensure geographic accuracy"""
    
    def __init__(self, location_data: Dict):
        self.data = location_data
        self._build_indexes()
        
    def _build_indexes(self):
        """Build reverse lookups for fast validation"""
        # Landmark -> City/Country lookup
        self.landmark_to_location = {}
        for landmark in self.data.get('landmarks', []):
            self.landmark_to_location[landmark['id']] = {
                'city_id': landmark.get('city_id'),
                'state_id': landmark.get('state_id'),
                'country_id': landmark.get('country_id')
            }
            
        # City -> State/Country lookup  
        self.city_to_location = {}
        for city in self.data.get('cities', []):
            self.city_to_location[city['id']] = {
                'state_id': city.get('state_id'),
                'country_id': city.get('country_id')
            }
            
        # Build name variations index
        self.name_to_entity = {}
        for landmark in self.data.get('landmarks', []):
            for name in landmark.get('names', []):
                self.name_to_entity[name.lower()] = ('landmark', landmark)
                
        for city in self.data.get('cities', []):
            for name in city.get('names', []):
                self.name_to_entity[name.lower()] = ('city', city)
                
    def get_location_component(self) -> Dict[str, Any]:
        """Get a location component with truth data"""
        location_type = random.choice(['landmark', 'city'])
        
        if location_type == 'landmark':
            landmark = random.choice(self.data['landmarks'])
            
            # OPTIMIZATION 4: Prefer multi-word landmarks for easier detection
            # Check if primary name has multiple words
            primary_name = landmark['names'][0]
            if ' ' in primary_name and random.random() < 0.7:  # 70% prefer multi-word
                name = primary_name
            else:
                # Still allow variation in single-word or when not preferring multi-word
                name = random.choice(landmark['names'])
            
            # Get associated location info
            city = None
            state = None
            country = None
            
            if landmark.get('city_id'):
                city = self._get_by_id(self.data['cities'], landmark['city_id'])
            if landmark.get('state_id'):
                state = self._get_by_id(self.data['states'], landmark['state_id'])
            if landmark.get('country_id'):
                country = self._get_by_id(self.data['countries'], landmark['country_id'])
                
            # Build text variations
            variations = [name]
            
            if city and random.random() < 0.3:
                city_name = random.choice(city['names'])
                variations.append(f"{name}_{city_name}")
                
            if state and random.random() < 0.2:
                variations.append(f"{name}_{state['code']}")
                
            text = random.choice(variations).replace(' ', '_')
            
            # Build truth data
            truth = {
                'primary_search': self._build_search_string(landmark, city, state, country),
                'alternate_search': self._build_alternate_search(city, state, country),
                'confidence': 85,
                'location_type': 'landmark',
                'landmark_name': landmark['names'][0],
                'city': city['names'][0] if city else '',
                'state': state['code'] if state else '',
                'country': country['names'][0] if country else ''
            }
            
            return {'text': text, 'truth': truth}
            
        elif location_type == 'city':
            city = random.choice(self.data['cities'])
            state = None
            country = None
            
            if city.get('state_id'):
                state = self._get_by_id(self.data['states'], city['state_id'])
            if city.get('country_id'):
                country = self._get_by_id(self.data['countries'], city['country_id'])
                
            # Build text
            city_name = random.choice(city['names'])
            variations = [city_name]
            
            if state and random.random() < 0.5:
                variations.append(f"{city_name}_{state['code']}")
                
            text = random.choice(variations).replace(' ', '_')
            
            # Build truth
            truth = {
                'primary_search': f"{city['names'][0]}, {state['code'] if state else country['names'][0] if country else ''}".strip(', '),
                'alternate_search': state['code'] if state else country['names'][0] if country else '',
                'confidence': 60,
                'location_type': 'city',
                'landmark_name': '',
                'city': city['names'][0],
                'state': state['code'] if state else '',
                'country': country['names'][0] if country else ''
            }
            
            return {'text': text, 'truth': truth}
            
    def _get_by_id(self, collection: List[Dict], id: str) -> Optional[Dict]:
        """Get entity by ID"""
        for item in collection:
            if item.get('id') == id:
                return item
        return None
        
    def _build_search_string(self, landmark, city, state, country) -> str:
        """Build primary search string"""
        parts = [landmark['names'][0]]
        
        if city:
            parts.append(city['names'][0])
        if state:
            parts.append(state['code'])
        elif country:
            parts.append(country['names'][0])
            
        return ', '.join(parts)
        
    def _build_alternate_search(self, city, state, country) -> str:
        """Build alternate search string"""
        if city and state:
            return f"{city['names'][0]}, {state['code']}"
        elif city and country:
            return f"{city['names'][0]}, {country['names'][0]}"
        elif state:
            return state['code']
        elif country:
            return country['names'][0]
        return ''


class FlexibleFilenameGenerator:
    """Generates realistic filenames with flexible component ordering"""
    
    def __init__(self, data_file: str):
        with open(data_file, 'r') as f:
            self.data = json.load(f)
            
        self.geo_engine = GeographicTruthEngine(self.data['locations'])
        self.test_id = 1
        self._current_pattern_type = None
        
    def generate_cases(self, count: int) -> List[Dict]:
        """Generate test cases with realistic distribution"""
        cases = []
        
        # OPTIMIZATION 1: Increase location signal from 25% to 35%
        distributions = [
            ('searchable_location', 0.35),    # ↑ from 0.25 - Has extractable location
            ('date_only', 0.15),              # ↓ from 0.20 - Just date, no location
            ('non_searchable', 0.25),         # ↓ from 0.30 - Personal/generic location
            ('device_default', 0.15),         # unchanged - IMG_1234.jpg style
            ('complex_mixed', 0.10)           # unchanged - Multiple components
        ]
        
        # For small counts, ensure we generate at least something
        if count < len(distributions):
            # Just cycle through pattern types for very small counts
            pattern_types = [d[0] for d in distributions]
            for i in range(count):
                pattern_type = pattern_types[i % len(pattern_types)]
                case = self._generate_case(pattern_type)
                case['test_id'] = str(self.test_id)
                cases.append(case)
                self.test_id += 1
        else:
            # Normal distribution for larger counts
            remaining = count
            for i, (pattern_type, weight) in enumerate(distributions):
                # For the last pattern, use all remaining cases
                if i == len(distributions) - 1:
                    pattern_count = remaining
                else:
                    pattern_count = int(count * weight)
                    remaining -= pattern_count
                
                for _ in range(pattern_count):
                    case = self._generate_case(pattern_type)
                    case['test_id'] = str(self.test_id)
                    cases.append(case)
                    self.test_id += 1
                
        random.shuffle(cases)
        return cases
        
    def _generate_case(self, pattern_type: str) -> Dict:
        """Generate a single test case"""
        # Store pattern type for separator logic
        self._current_pattern_type = pattern_type
        
        if pattern_type == 'searchable_location':
            return self._generate_searchable_location()
        elif pattern_type == 'date_only':
            return self._generate_date_only()
        elif pattern_type == 'non_searchable':
            return self._generate_non_searchable()
        elif pattern_type == 'device_default':
            return self._generate_device_default()
        else:  # complex_mixed
            return self._generate_complex_mixed()
            
    def get_venue_component(self) -> Dict[str, Any]:
        """Get a venue component (restaurant, store, etc.)"""
        # Choose venue pattern
        pattern = random.choice([
            # Pattern 1: modifier + type (most common)
            lambda: f"{random.choice(self.data['components']['venue_modifiers'])}_{random.choice(self.data['components']['venue_types'])}",
            # Pattern 2: chain name
            lambda: random.choice(self.data['components']['chain_names']),
            # Pattern 3: personal venue
            lambda: f"{random.choice(self.data['components']['names']['first'])}s_{random.choice(self.data['components']['venue_types'])}"
        ])
        
        venue_text = pattern()
        
        # 40% chance to add location
        if random.random() < 0.4:
            city = random.choice(self.data['locations']['cities'])
            state = None
            if city.get('state_id'):
                state = self._get_by_id(self.data['locations']['states'], city['state_id'])
            
            # Add location to venue
            if state:
                venue_with_location = f"{venue_text}_{random.choice(city['names'])}_{state['code']}"
                truth = {
                    'primary_search': f"{city['names'][0]}, {state['code']}",
                    'alternate_search': state['code'],
                    'confidence': 60,
                    'location_type': 'city',
                    'landmark_name': '',
                    'city': city['names'][0],
                    'state': state['code'],
                    'country': 'USA'  # US cities have states
                }
            else:
                # International city
                venue_with_location = f"{venue_text}_{random.choice(city['names'])}"
                country = self._get_by_id(self.data['locations']['countries'], city['country_id'])
                truth = {
                    'primary_search': f"{city['names'][0]}, {country['names'][0] if country else ''}",
                    'alternate_search': country['names'][0] if country else '',
                    'confidence': 60,
                    'location_type': 'city',
                    'landmark_name': '',
                    'city': city['names'][0],
                    'state': '',
                    'country': country['names'][0] if country else ''
                }
            
            return {'text': venue_with_location, 'truth': truth}
        else:
            # Just venue, no location
            return {'text': venue_text, 'truth': None}
            
    def _generate_searchable_location(self) -> Dict:
        """Generate filename with searchable location"""
        components = []
        
        # Maybe add name
        if random.random() < 0.6:
            components.append(self._get_name())
            
        # Maybe add activity or ordinal event
        if random.random() < 0.4:
            if random.random() < 0.3:  # 30% chance of ordinal event
                components.append(self._get_ordinal_event())
            else:
                components.append(random.choice(self.data['components']['activities']))
            
        # Add location (required for this type) - either landmark or venue with location
        if random.random() < 0.7:  # 70% landmarks, 30% venues with locations
            location_data = self.geo_engine.get_location_component()
        else:
            # Get a venue with location
            location_data = self.get_venue_component()
            while location_data['truth'] is None:  # Ensure it has location
                location_data = self.get_venue_component()
                
        components.append(location_data['text'])
        
        # Maybe add date
        date_info = None
        if random.random() < 0.7:
            date_comp, date_info = self._get_date_component()
            components.append(date_comp)
            
        # SHUFFLE components for realistic ordering
        random.shuffle(components)
        
        # Ensure we have at least the location
        if not components:
            components.append(location_data['text'])
            
        separator = self._get_separator()
        filename = separator.join(components) + self._get_extension()
        
        # Apply casing style
        filename = self._apply_casing(filename, separator)
        
        return {
            'filename': filename,
            'expected_location_suggestion': location_data['truth'],
            'expected_date_suggestion': date_info
        }
        
    def _generate_date_only(self) -> Dict:
        """Generate filename with date but no location"""
        components = []
        
        # Maybe add name
        if random.random() < 0.5:
            components.append(self._get_name())
            
        # Maybe add generic descriptor or ordinal event
        if random.random() < 0.6:
            if random.random() < 0.2:  # 20% ordinal events
                components.append(self._get_ordinal_event())
            else:
                components.append(random.choice(self.data['components']['descriptors']))
            
        # Add date (required)
        date_comp, date_info = self._get_date_component()
        components.append(date_comp)
        
        # Maybe add sequence
        if random.random() < 0.3:
            components.append(f"{random.randint(1, 9999):04d}")
            
        random.shuffle(components)
        
        # Ensure we have at least the date
        if not components:
            components = [date_comp]
            
        separator = self._get_separator()
        filename = separator.join(components) + self._get_extension()
        
        # Apply casing style
        filename = self._apply_casing(filename, separator)
        
        return {
            'filename': filename,
            'expected_location_suggestion': None,
            'expected_date_suggestion': date_info
        }
        
    def _generate_non_searchable(self) -> Dict:
        """Generate filename with non-searchable location"""
        components = []
        
        # Usually has name
        if random.random() < 0.8:
            components.append(self._get_name())
            
        # Add non-searchable location - either personal location or venue without location
        if random.random() < 0.7:  # 70% personal locations
            components.append(random.choice(self.data['components']['non_searchable_locations']))
        else:  # 30% venues without location
            venue_data = self.get_venue_component()
            while venue_data['truth'] is not None:  # Ensure it has NO location
                venue_data = self.get_venue_component()
            components.append(venue_data['text'])
            
        # Maybe add activity or ordinal event
        if random.random() < 0.5:
            if random.random() < 0.25:  # 25% ordinal events
                components.append(self._get_ordinal_event())
            else:
                components.append(random.choice(self.data['components']['activities']))
            
        # OPTIMIZATION 2: Increase date probability to reduce pure noise
        date_info = None
        if random.random() < 0.8:  # ↑ from 0.6
            date_comp, date_info = self._get_date_component()
            components.append(date_comp)
            
        random.shuffle(components)
        
        # Ensure we have at least something
        if not components:
            components.append(random.choice(self.data['components']['non_searchable_locations']))
            
        separator = self._get_separator()
        filename = separator.join(components) + self._get_extension()
        
        # Apply casing style
        filename = self._apply_casing(filename, separator)
        
        return {
            'filename': filename,
            'expected_location_suggestion': None,
            'expected_date_suggestion': date_info
        }
        
    def _generate_device_default(self) -> Dict:
        """Generate device default filename (IMG_1234.jpg style)"""
        # Decide if this device pattern should have a date
        has_date = random.random() < 0.4  # 40% of device files have dates
        
        if has_date:
            # Use patterns from JSON data
            date_patterns = self.data['components']['device_patterns_with_date']
            pattern = random.choice(date_patterns)
            
            # Generate date components
            year = random.randint(1900, 2030)
            month = random.randint(1, 12)
            last_day = calendar.monthrange(year, month)[1]
            day = random.randint(1, last_day)
            
            # Replace placeholders
            filename = pattern
            filename = filename.replace('{seq}', f"{random.randint(1, 9999):04d}")
            filename = filename.replace('{date}', f"{year}-{month:02d}-{day:02d}")
            filename = filename.replace('{time}', datetime.now().strftime('%H%M%S'))
            filename = filename.replace('{year}', str(year))
            filename = filename.replace('{month:02d}', f"{month:02d}")
            filename = filename.replace('{day:02d}', f"{day:02d}")
            
            date_info = {'year': str(year), 'month': f"{month:02d}", 'day': f"{day:02d}", 'is_complete': True}
        else:
            # Use patterns from JSON data
            no_date_patterns = self.data['components']['device_patterns_no_date']
            pattern = random.choice(no_date_patterns)
            
            # Replace placeholders
            filename = pattern
            filename = filename.replace('{seq}', f"{random.randint(1, 9999):04d}")
            
            date_info = None
        
        # Add extension if not already in pattern
        if not any(filename.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.heic']):
            filename += self._get_extension()
            
        # Device patterns usually don't have casing changes
        if random.random() < 0.9:  # 90% keep original casing
            return {
                'filename': filename,
                'expected_location_suggestion': None,
                'expected_date_suggestion': date_info
            }
        else:
            # 10% might have casing changes
            separator = self._detect_separator(filename)
            filename = self._apply_casing(filename, separator)
            return {
                'filename': filename,
                'expected_location_suggestion': None,
                'expected_date_suggestion': date_info
            }
        
    def _generate_complex_mixed(self) -> Dict:
        """Generate complex filename with multiple components"""
        components = []
        
        # Multiple names possible
        if random.random() < 0.7:
            components.append(self._get_name())
            if random.random() < 0.3:  # Sometimes multiple people
                components.append(self._get_name())
                
        # Multiple descriptors/activities/ordinal events
        if random.random() < 0.6:
            if random.random() < 0.25:  # 25% ordinal events
                components.append(self._get_ordinal_event())
            else:
                components.append(random.choice(self.data['components']['activities']))
        if random.random() < 0.4:
            components.append(random.choice(self.data['components']['descriptors']))
            
        # Maybe location (landmark, city, or venue)
        location_data = None
        if random.random() < 0.5:
            if random.random() < 0.6:  # 60% real locations
                location_data = self.geo_engine.get_location_component()
            else:  # 40% venues
                location_data = self.get_venue_component()
            if location_data and location_data['text']:
                components.append(location_data['text'])
            
        # Maybe date
        date_info = None
        if random.random() < 0.7:
            date_comp, date_info = self._get_date_component()
            components.append(date_comp)
            
        # Maybe device model
        if random.random() < 0.2:  # 20% include device model
            components.append(random.choice(self.data['components']['device_models']))
            
        # Shuffle for realism
        random.shuffle(components)
        
        # Ensure we have at least something
        if not components:
            components.append(f"IMG_{random.randint(1000, 9999)}")
            
        separator = self._get_separator()
        filename = separator.join(components) + self._get_extension()
        
        # Apply casing style
        filename = self._apply_casing(filename, separator)
        
        return {
            'filename': filename,
            'expected_location_suggestion': location_data['truth'] if location_data else None,
            'expected_date_suggestion': date_info
        }
        
    def _get_name(self) -> str:
        """Get a name component"""
        patterns = ['first', 'last', 'first_last', 'last_first']
        pattern = random.choice(patterns)
        
        first = random.choice(self.data['components']['names']['first'])
        last = random.choice(self.data['components']['names']['last'])
        
        if pattern == 'first':
            return first
        elif pattern == 'last':
            return last
        elif pattern == 'first_last':
            return f"{first}_{last}"
        else:  # last_first
            return f"{last}_{first}"
            
    def _get_ordinal_event(self) -> str:
        """Generate ordinal event like '25th_Anniversary' or '1st_Birthday'"""
        ordinal = random.choice(self.data['components']['ordinal_numbers'])
        event = random.choice(self.data['components']['ordinal_events'])
        
        # Sometimes include year for context
        if random.random() < 0.3:
            year = random.randint(1900, 2030)
            return f"{ordinal}_{event}_{year}"
        
        return f"{ordinal}_{event}"
        
    def _get_date_component(self) -> Tuple[str, Optional[Dict]]:
        """Get date component and truth data"""
        year = random.randint(1900, 2030)
        month = random.randint(1, 12)
        last_day = calendar.monthrange(year, month)[1]
        day = random.randint(1, last_day)

        
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        month_full_names = ["January", "February", "March", "April", "May", "June",
                            "July", "August", "September", "October", "November", "December"]
        
        patterns = [
            (f"{year}-{month:02d}-{day:02d}", {'year': str(year), 'month': f"{month:02d}", 'day': f"{day:02d}", 'is_complete': True}),
            (f"{day:02d}-{month:02d}-{year}", {'year': str(year), 'month': f"{month:02d}", 'day': f"{day:02d}", 'is_complete': True}),
            (f"{year}_{month:02d}_{day:02d}", {'year': str(year), 'month': f"{month:02d}", 'day': f"{day:02d}", 'is_complete': True}),
            (f"{month:02d}{day:02d}{year}", {'year': str(year), 'month': f"{month:02d}", 'day': f"{day:02d}", 'is_complete': True}),
            (f"{month_names[month-1]}_{day}_{year}", {'year': str(year), 'month': f"{month:02d}", 'day': f"{day:02d}", 'is_complete': True}),
            (f"{year}-{month:02d}", {'year': str(year), 'month': f"{month:02d}", 'day': '', 'is_complete': False}),
            (f"{year}_{month:02d}", {'year': str(year), 'month': f"{month:02d}", 'day': '', 'is_complete': False}),
            (f"{month_names[month-1]}_{year}", {'year': str(year), 'month': f"{month:02d}", 'day': '', 'is_complete': False}),
            (f"{month_full_names[month-1]}_{year}", {'year': str(year), 'month': f"{month:02d}", 'day': '', 'is_complete': False}),
            (str(year), {'year': str(year), 'month': '', 'day': '', 'is_complete': False}),
        ]

        date_str, date_info = random.choice(patterns)
        return date_str, date_info
        
    def _get_separator(self) -> str:
        """Get separator for this filename"""
        # Device defaults typically use specific patterns
        if self._current_pattern_type == 'device_default':
            return '_'  # Keep consistent for device patterns
        
        # Weight towards underscore for compatibility
        weights = [0.6, 0.2, 0.1, 0.05, 0.05]  # _, -, space, ., empty
        return random.choices(self.data['components']['separators'], weights=weights)[0]
        
    def _get_extension(self) -> str:
        """Get file extension"""
        extensions = ['.jpg', '.jpeg', '.png', '.heic', '.HEIC', '.JPG', '.JPEG', '.PNG']
        return random.choice(extensions)
        
    def _apply_casing(self, filename: str, separator: str) -> str:
        """Apply casing style to filename"""
        # Preserve extension casing most of the time
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        
        # Choose casing style with realistic distribution
        style_weights = {
            'lowercase': 0.4,      # most common
            'CamelCase': 0.2,      # some people use this
            'UPPERCASE': 0.05,     # rare but happens
            'mixedCase': 0.1,      # some mixing
            'Title_Case': 0.15,    # fairly common
            'preserve': 0.1        # keep as is
        }
        
        style = random.choices(
            list(style_weights.keys()), 
            weights=list(style_weights.values())
        )[0]
        
        if style == 'preserve':
            return filename
        
        # Split by separator
        parts = name.split(separator) if separator else [name]
        
        if style == 'lowercase':
            parts = [p.lower() for p in parts]
        elif style == 'UPPERCASE':
            parts = [p.upper() for p in parts]
        elif style == 'CamelCase':
            # Remove separator and capitalize each word
            name = ''.join(p.capitalize() for p in parts)
            return f"{name}.{ext}" if ext else name
        elif style == 'mixedCase':
            # First part lowercase, rest capitalized
            if parts:
                parts = [parts[0].lower()] + [p.capitalize() for p in parts[1:]]
        elif style == 'Title_Case':
            parts = [p.capitalize() for p in parts]
        
        # Reconstruct with separator
        name = separator.join(parts) if separator else ''.join(parts)
        
        # Extension casing (usually lowercase, sometimes uppercase)
        if ext:
            ext = ext.lower() if random.random() < 0.9 else ext.upper()
            return f"{name}.{ext}"
        
        return name
        
    def _detect_separator(self, text: str) -> str:
        """Detect separator in text"""
        for sep in ['_', '-', '.', ' ']:
            if sep in text:
                return sep
        return ''
        
    def _get_by_id(self, collection: List[Dict], id: str) -> Optional[Dict]:
        """Get entity by ID"""
        for item in collection:
            if item.get('id') == id:
                return item
        return None


# Lambda enrichment functions (from training-data-generator.py)
def create_reasoning_prompt(filename: str, location_data: Optional[Dict], date_data: Optional[Dict]) -> str:
    """Create prompt for a single example."""
    location_str = json.dumps(location_data) if location_data else "null"
    date_str = json.dumps(date_data) if date_data else "null"
    
    return f"""Filename: {filename}
Location Result: {location_str}
Date Result: {date_str}

Output EXACTLY this JSON format:
{{
  "location_context": "explain why this location result is correct",
  "subject": "what the photo likely shows",
  "where_taken": "echo location from result or 'Unknown location' if null",
  "search_strategy": "venue_first OR city_first OR landmark_only OR need_more_info"
}}"""


def create_batch_prompt(examples: List[Dict]) -> str:
    """Create prompt for multiple examples."""
    prompt = """Task: Generate reasoning that JUSTIFIES pre-determined parsing results.

CRITICAL RULES:
- You are NOT parsing the filename
- You are explaining WHY the given result is correct
- search_strategy MUST be one of: venue_first, city_first, landmark_only, need_more_info
- If location is null, search_strategy MUST be need_more_info
- If landmark_name exists, search_strategy SHOULD be landmark_only
- If only city exists, search_strategy SHOULD be city_first

For each example below, output a JSON object with location_context, subject, where_taken, and search_strategy.

"""
    
    for i, example in enumerate(examples):
        prompt += f"\nExample {i+1}:\n"
        prompt += create_reasoning_prompt(
            example["filename"],
            example.get("expected_location_suggestion"),
            example.get("expected_date_suggestion")
        )
        prompt += "\n"
    
    prompt += f"\nOutput a JSON array with {len(examples)} objects, one for each example. Do not wrap the JSON in markdown code blocks, just output the raw JSON array:"
    
    return prompt


def generate_full_output(filename: str, location_data: Optional[Dict], date_data: Optional[Dict], 
                        reasoning: Dict) -> Dict:
    """Combine ground truth with generated reasoning into full output format."""
    
    # Start with base structure
    output = {
        "location_confidence": "none",
        "primary_search": None,
        "alternate_search": None,
        "location_type": "unknown",
        "location_context": reasoning.get("location_context", "No location information found"),
        "extracted": {
            "subject": reasoning.get("subject", "Unknown subject"),
            "where_taken": reasoning.get("where_taken", "Unknown location"),
            "landmark_name": None,
            "city": None,
            "state": None,
            "country": None,
            "date_parts": {"year": None, "month": None, "day": None}
        },
        "search_strategy": reasoning.get("search_strategy", "need_more_info")
    }
    
    # Update with location data if present
    if location_data:
        # Map confidence number to string
        conf_num = location_data.get("confidence", 0)
        if conf_num >= 80:
            conf_str = "high"
        elif conf_num >= 50:
            conf_str = "medium"
        elif conf_num >= 30:
            conf_str = "low"
        else:
            conf_str = "none"
            
        output["location_confidence"] = conf_str
        output["primary_search"] = location_data.get("primary_search")
        output["alternate_search"] = location_data.get("alternate_search")
        output["location_type"] = location_data.get("location_type", "unknown")
        
        # Update extracted fields
        output["extracted"]["landmark_name"] = location_data.get("landmark_name")
        output["extracted"]["city"] = location_data.get("city")
        output["extracted"]["state"] = location_data.get("state")
        output["extracted"]["country"] = location_data.get("country")
    
    # Update with date data if present
    if date_data:
        output["extracted"]["date_parts"] = {
            "year": date_data.get("year"),
            "month": date_data.get("month"),
            "day": date_data.get("day")
        }
    
    return output


def create_training_example(filename: str, full_output: Dict) -> Dict:
    """Create a chat-style training example for fine-tuning."""
    
    # Full prompt with instructions that the model will see in production
    user_prompt = f"""Analyze this photo filename to determine WHERE the photo was taken.

For each filename, think step by step:
1. What is likely the SUBJECT of the photo? (what's in it)
2. Is there a LOCATION NAME explicitly written in the filename?
3. Are there any clues about the type of location? (restaurant, park, home, tourist spot, etc.)
4. Is this a place you could find on a public map, or is it someone's personal property?

Output JSON with these fields:
{{
  "location_confidence": "high/medium/low/none",
  "primary_search": "<best search query for Apple Maps>",
  "alternate_search": "<backup search if primary is wrong>",
  "location_type": "venue/landmark/city/address/unknown",
  "location_context": "<explanation of your reasoning>",
  "extracted": {{
    "subject": "<what the photo is OF>",
    "where_taken": "<where you think it was taken>",
    "landmark_name": "<specific place name if mentioned>",
    "city": "<city if found - keep abbreviations like NYC, SF, LA as-is>",
    "state": "<2-letter code if US/Canada>",
    "country": "<country if not US>",
    "date_parts": {{"year": null, "month": null, "day": null}}
  }},
  "search_strategy": "venue_first/city_first/landmark_only/need_more_info"
}}

Filename: {filename}"""
    
    # Assistant responds with the complete JSON (no markdown, just JSON)
    # Use compact JSON format (no indentation) as the model should output in production
    assistant_response = json.dumps(full_output, separators=(',', ':'))
    
    return {
        "messages": [
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": assistant_response}
        ]
    }


def process_batch(client: OpenAI, batch: List[Dict], batch_num: int, total_batches: int) -> List[Dict]:
    """Process a batch of examples using Lambda API."""
    results = []
    batch_size = 10  # Process 10 examples per API call
    
    for sub_idx in range(0, len(batch), batch_size):
        sub_batch = batch[sub_idx:sub_idx + batch_size]
        print(f"\rBatch {batch_num}/{total_batches} - Processing {sub_idx+len(sub_batch)}/{len(batch)}", end="", flush=True)
        
        # Create batch prompt
        prompt = create_batch_prompt(sub_batch)
        
        try:
            # Call Lambda API
            response = client.chat.completions.create(
                model="llama-4-scout-17b-16e-instruct",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that generates training data. Always respond with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=1500
            )
            
            reasoning_text = response.choices[0].message.content.strip()
            
            # Parse JSON array response
            try:
                # Remove markdown code blocks if present
                if "```json" in reasoning_text:
                    start = reasoning_text.find("```json") + 7
                    end = reasoning_text.find("```", start)
                    if end != -1:
                        reasoning_text = reasoning_text[start:end].strip()
                elif "```" in reasoning_text:
                    start = reasoning_text.find("```") + 3
                    end = reasoning_text.find("```", start)
                    if end != -1:
                        reasoning_text = reasoning_text[start:end].strip()
                
                # Find JSON array
                start = reasoning_text.find('[')
                end = reasoning_text.rfind(']')
                
                if start != -1 and end != -1:
                    json_str = reasoning_text[start:end+1]
                    reasoning_array = json.loads(json_str)
                else:
                    reasoning_array = json.loads(reasoning_text)
                
                # Process each result
                for i, example in enumerate(sub_batch):
                    if i < len(reasoning_array):
                        reasoning = reasoning_array[i]
                    else:
                        reasoning = {
                            "location_context": "Unable to determine location from filename",
                            "subject": "Unknown subject",
                            "where_taken": "Unknown location",
                            "search_strategy": "need_more_info"
                        }
                    
                    # Generate full output
                    full_output = generate_full_output(
                        example["filename"],
                        example.get("expected_location_suggestion"),
                        example.get("expected_date_suggestion"),
                        reasoning
                    )
                    
                    # Create training example
                    training_example = create_training_example(example["filename"], full_output)
                    results.append(training_example)
                    
            except (json.JSONDecodeError, IndexError) as e:
                print(f"\nJSON parse error: {e}")
                print(f"Expected JSON array with {len(sub_batch)} items")
                print(f"API Response (first 1000 chars): {reasoning_text[:1000]}")
                print("\n--- Falling back to individual processing ---")
                
                # Fallback to individual processing
                for example in sub_batch:
                    try:
                        single_prompt = create_reasoning_prompt(
                            example["filename"],
                            example.get("expected_location_suggestion"),
                            example.get("expected_date_suggestion")
                        )
                        
                        single_response = client.chat.completions.create(
                            model="llama-4-scout-17b-16e-instruct",
                            messages=[
                                {"role": "user", "content": f"Task: Generate reasoning that JUSTIFIES pre-determined parsing results.\n\n{single_prompt}"}
                            ],
                            temperature=0.1,
                            max_tokens=300
                        )
                        
                        single_text = single_response.choices[0].message.content.strip()
                        reasoning = json.loads(single_text)
                        
                    except:
                        reasoning = {
                            "location_context": "Unable to determine location from filename",
                            "subject": "Unknown subject",
                            "where_taken": "Unknown location",
                            "search_strategy": "need_more_info"
                        }
                    
                    full_output = generate_full_output(
                        example["filename"],
                        example.get("expected_location_suggestion"),
                        example.get("expected_date_suggestion"),
                        reasoning
                    )
                    training_example = create_training_example(example["filename"], full_output)
                    results.append(training_example)
                    
        except Exception as e:
            print(f"\nAPI error: {e}")
            continue
    
    print(f"\nBatch {batch_num} complete. Generated {len(results)} examples.")
    return results


def main():
    # Get data file from command line or use default
    data_file = sys.argv[1] if len(sys.argv) > 1 else 'dataforfilegenerator.json'
    
    if not Path(data_file).exists():
        print(f"Error: Data file not found: {data_file}")
        print("Please provide the path to dataforfilegenerator.json")
        sys.exit(1)
        
    print("Integrated Flexible Filename Test & Training Data Generator")
    print(f"Loading data from: {data_file}")
    
    generator = FlexibleFilenameGenerator(data_file)
    
    # Ask for number of test cases
    while True:
        try:
            count_input = input("\nHow many test cases would you like to generate? ")
            count = int(count_input)
            if count <= 0:
                print("Please enter a positive number.")
                continue
            if count < 5:
                print("Note: Small test sets may not show representative distributions.")
            break
        except ValueError:
            print("Please enter a valid number.")
    
    print(f"\nGenerating {count} test cases...")
    
    # Generate test cases
    cases = generator.generate_cases(count)
    
    # Calculate statistics
    with_location = sum(1 for c in cases if c.get('expected_location_suggestion'))
    with_date = sum(1 for c in cases if c.get('expected_date_suggestion'))
    no_signal = sum(1 for c in cases if not c.get('expected_location_suggestion') and not c.get('expected_date_suggestion'))
    
    # Count multi-word landmarks
    multi_word_landmarks = sum(1 for c in cases 
                              if c.get('expected_location_suggestion') 
                              and c['expected_location_suggestion'].get('location_type') == 'landmark'
                              and ' ' in c['expected_location_suggestion'].get('landmark_name', ''))
    
    output = {
        'generated_date': datetime.now().isoformat(),
        'total_cases': len(cases),
        'ground_truth_examples': cases,
        'dataset_stats': {
            'data_file': data_file,
            'cases_with_location': with_location,
            'cases_with_date': with_date,
            'cases_with_no_signal': no_signal,
            'multi_word_landmarks': multi_word_landmarks,
            'location_percentage': f"{with_location/len(cases)*100:.1f}%" if cases else "0.0%",
            'date_percentage': f"{with_date/len(cases)*100:.1f}%" if cases else "0.0%",
            'no_signal_percentage': f"{no_signal/len(cases)*100:.1f}%" if cases else "0.0%"
        }
    }
    
    output_file = 'filename_dataset.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        
    print(f"\nGenerated {len(cases)} test cases")
    if cases:
        print(f"{with_location} ({with_location/len(cases)*100:.1f}%) have locations")
        print(f"{with_date} ({with_date/len(cases)*100:.1f}%) have dates") 
        print(f"{no_signal} ({no_signal/len(cases)*100:.1f}%) have no signal")
    else:
        print("0 (0.0%) have locations")
        print("0 (0.0%) have dates")
        print("0 (0.0%) have no signal")
    print(f"{multi_word_landmarks} multi-word landmarks for easier detection")
    print(f"Saved to: {output_file}")

    # Ask about Lambda enrichment
    print("\n" + "="*60)
    enrich_choice = input("Enrich data with Lambda AI for fine-tuning? (y/n): ")
    
    if enrich_choice.lower() != 'y':
        print("\nTest dataset created successfully.")
        print("Note: Without LLM enrichment, the dataset lacks the reasoning fields needed for fine-tuning.")
        print(f"To generate training data later, run the enrichment script with: {output_file}")
        sys.exit(0)

    # Lambda enrichment phase
    print("\nLAMBDA ENRICHMENT FOR TRAINING DATA")
    print("="*60)
    
    # Securely prompt for Lambda API key
    api_key = getpass.getpass("\nEnter your Lambda Cloud API key (input will be hidden): ")
    
    # Initialize Lambda client (OpenAI-compatible)
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.lambda.ai/v1"
    )
    
    # Test API connection
    print("Testing Lambda API connection...")
    try:
        test_response = client.chat.completions.create(
            model="llama-4-scout-17b-16e-instruct",
            messages=[{"role": "user", "content": "Test"}],
            max_tokens=10
        )
        print("Lambda API connection successful")
    except Exception as e:
        print(f"Lambda API connection failed: {e}")
        sys.exit(1)
    
    # Calculate costs for Lambda
    est_input_tokens = len(cases) * 100
    est_output_tokens = len(cases) * 150
    est_cost = (est_input_tokens * 0.08 / 1_000_000) + (est_output_tokens * 0.30 / 1_000_000)
    
    print(f"\nLambda AI Model: llama-4-scout-17b-16e-instruct")
    print(f"Estimated API cost: ${est_cost:.2f}")
    print(f"Pricing: $0.08 per 1M input tokens, $0.30 per 1M output tokens")
    
    confirm = input("\nProceed with enrichment? (y/n): ")
    if confirm.lower() != 'y':
        print("Cancelled enrichment. Test dataset was saved.")
        sys.exit(0)
    
    start_time = datetime.now()
    
    # Process in batches
    batch_size = 250
    all_results = []
    
    for i in range(0, len(cases), batch_size):
        batch = cases[i:i+batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(cases) + batch_size - 1) // batch_size
        
        print(f"\nProcessing batch {batch_num} of {total_batches}")
        batch_results = process_batch(client, batch, batch_num, total_batches)
        all_results.extend(batch_results)
        
        print(f"Progress: {len(all_results)}/{len(cases)} examples")
    
    # Save final results
    output_file = "fine_tune_training_data.jsonl"
    with open(output_file, 'w', encoding='utf-8') as f:
        for result in all_results:
            f.write(json.dumps(result, ensure_ascii=False) + '\n')
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds() / 60
    
    # Calculate actual cost
    actual_input_tokens = len(all_results) * 100
    actual_output_tokens = len(all_results) * 150
    actual_cost = (actual_input_tokens * 0.08 / 1_000_000) + (actual_output_tokens * 0.30 / 1_000_000)
    
    print(f"\nCompleted! Generated {len(all_results)} training examples in {duration:.1f} minutes")
    print(f"Actual cost: ${actual_cost:.2f}")
    print(f"Saved enriched training data to: {output_file}")
    print("Format: Chat-style messages ready for fine-tuning")


if __name__ == "__main__":
    main()