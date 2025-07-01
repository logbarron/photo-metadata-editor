#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "llama-cpp-python",
#   "huggingface-hub"
# ]
# ///
"""
Comprehensive LLM Metadata Extraction Test Harness

Tests different LLMs on extracting ALL metadata from photo filenames:
- Date (year, month, day)
- Location (city, state, country) 
- POI (points of interest)
- Address (street addresses)
- Names (people/photographers)
- Sequence numbers
- Events

Features:
- Runs scored test cases with expected outputs
- Runs your custom filenames (add to CUSTOM_FILENAMES list) 
- Both test types run in a single execution
- Tracks results over time to compare models and prompts

Run with uv:
  # Make executable (first time only)
  chmod +x Multiple_LLM_Filename_Test_Harness.py
  
  # Test with default model (runs both scored + custom)
  ./Multiple_LLM_Filename_Test_Harness.py
  
  # Or run directly with uv
  uv run Multiple_LLM_Filename_Test_Harness.py
  
  # Test multiple models
  ./Multiple_LLM_Filename_Test_Harness.py phi-3.5-mini gemma-3-4b-q4
  
  # Quick test with fewer examples
  ./Multiple_LLM_Filename_Test_Harness.py --quick
  
  # Use different prompt version
  ./Multiple_LLM_Filename_Test_Harness.py --prompt v2_structured
"""

import json
import time
import sys
import csv
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from datetime import datetime
from collections import Counter
import argparse

# Comprehensive test cases with all expected fields
TEST_CASES = [
    # Basic patterns
    ("christmas_dinner_2022.heic", {
        "date": {"year": 2022, "month": 12, "day": 25},
        "location": {},
        "poi": None,
        "address": None,
        "names": None,
        "sequence": None,
        "event": "christmas dinner",
        "notes": "Holiday date inference"
    }),
    
    ("july_4th_fireworks_2023.heic", {
        "date": {"year": 2023, "month": 7, "day": 4},
        "location": {},
        "poi": None,
        "address": None,
        "names": None,
        "sequence": None,
        "event": "fireworks",
        "notes": "July 4th is a date, not event"
    }),
    
    # POI and location patterns
    ("nyc_central_park_2021.heic", {
        "date": {"year": 2021},
        "location": {"city": "New York City", "state": "NY"},
        "poi": "Central Park",
        "address": None,
        "names": None,
        "sequence": None,
        "event": None,
        "notes": "POI within city"
    }),
    
    ("grand_canyon_arizona_july_2023.heic", {
        "date": {"year": 2023, "month": 7},
        "location": {"state": "Arizona"},
        "poi": "Grand Canyon",
        "address": None,
        "names": None,
        "sequence": None,
        "event": None,
        "notes": "Famous landmark"
    }),
    
    # International with POI
    ("eiffel_tower_paris_france_bastille_day_2023.heic", {
        "date": {"year": 2023, "month": 7, "day": 14},
        "location": {"city": "Paris", "country": "France"},
        "poi": "Eiffel Tower",
        "address": None,
        "names": None,
        "sequence": None,
        "event": "Bastille Day",
        "notes": "POI + holiday"
    }),
    
    # Address patterns
    ("123_main_street_boston_ma_2020.heic", {
        "date": {"year": 2020},
        "location": {"city": "Boston", "state": "MA"},
        "poi": None,
        "address": "123 Main Street",
        "names": None,
        "sequence": None,
        "event": None,
        "notes": "Street address"
    }),
    
    ("1600_pennsylvania_ave_washington_dc.heic", {
        "date": {},
        "location": {"city": "Washington", "state": "DC"},
        "poi": None,
        "address": "1600 Pennsylvania Ave",
        "names": None,
        "sequence": None,
        "event": None,
        "notes": "Famous address"
    }),
    
    # Names and sequences
    ("carleton_watkins_yosemite_1865_0147.heic", {
        "date": {"year": 1865},
        "location": {},
        "poi": "Yosemite",
        "address": None,
        "names": "Carleton Watkins",
        "sequence": "0147",
        "event": None,
        "notes": "Historical photographer"
    }),
    
    ("london_october_1_1888_sherlock_holmes.heic", {
        "date": {"year": 1888, "month": 10, "day": 1},
        "location": {"city": "London"},
        "poi": None,
        "address": None,
        "names": "Sherlock Holmes",
        "sequence": None,
        "event": None,
        "notes": "Names at end"
    }),
    
    # Complex multi-field
    ("golden_gate_bridge_san_francisco_ca_2024_2023.heic", {
        "date": {"year": 2024},
        "location": {"city": "San Francisco", "state": "CA"},
        "poi": "Golden Gate Bridge",
        "address": None,
        "names": None,
        "sequence": "2023",
        "event": None,
        "notes": "Sequence that looks like year"
    }),
    
    ("mom_birthday_olive_garden_des_moines_ia_may_15_2023.heic", {
        "date": {"year": 2023, "month": 5, "day": 15},
        "location": {"city": "Des Moines", "state": "IA"},
        "poi": "Olive Garden",
        "address": None,
        "names": None,
        "sequence": None,
        "event": "mom birthday",
        "notes": "Restaurant as POI"
    }),
    
    # Edge cases
    ("IMG_4567.heic", {
        "date": {},
        "location": {},
        "poi": None,
        "address": None,
        "names": None,
        "sequence": "4567",
        "event": None,
        "notes": "IMG pattern"
    }),
    
    ("miami_beach_vacation_august_2022.heic", {
        "date": {"year": 2022, "month": 8},
        "location": {"city": "Miami Beach"},
        "poi": None,
        "address": None,
        "names": None,
        "sequence": None,
        "event": "vacation",
        "notes": "Multi-word city, not POI"
    }),
    
    ("mount_rushmore_july_1998.heic", {
        "date": {"year": 1998, "month": 7},
        "location": {},
        "poi": "Mount Rushmore",
        "address": None,
        "names": None,
        "sequence": None,
        "event": None,
        "notes": "Landmark without location"
    }),
]


@dataclass
class TestResult:
    """Result of a single test case"""
    filename: str
    model_name: str
    prompt_version: str
    timestamp: str
    parse_time: float
    
    # Raw output
    raw_output: str
    parsed_json: Optional[Dict]
    parse_error: Optional[str]
    
    # Extracted data
    extracted_date: Optional[Dict]
    extracted_location: Optional[Dict]
    extracted_poi: Optional[str]
    extracted_address: Optional[str]
    extracted_names: Optional[str]
    extracted_sequence: Optional[str]
    extracted_event: Optional[str]
    
    # Scoring
    date_score: float
    location_score: float
    poi_score: float
    address_score: float
    names_score: float
    sequence_score: float
    event_score: float
    overall_score: float
    
    # Detailed feedback
    field_errors: Dict[str, List[str]]
    
    def to_dict(self):
        return asdict(self)


class ResultsTracker:
    """Track and analyze results over time"""
    
    def __init__(self, results_dir: Path = Path("test_results")):
        self.results_dir = results_dir
        self.results_dir.mkdir(exist_ok=True)
        self.current_results: List[TestResult] = []
        self.fields = ["date", "location", "poi", "address", "names", "sequence", "event"]
    
    def add_result(self, result: TestResult):
        """Add a test result"""
        self.current_results.append(result)
    
    def save_results(self, run_id: str, custom_results: List[Dict] = None):
        """Save results to JSON file"""
        filepath = self.results_dir / f"run_{run_id}.json"
        data = {
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "scored_results": [r.to_dict() for r in self.current_results],
            "custom_results": custom_results or []
        }
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
    
    def save_summary_csv(self):
        """Append summary to CSV for tracking over time"""
        csv_path = self.results_dir / "summary_metrics.csv"
        
        if not self.current_results:
            return
            
        total = len(self.current_results)
        
        # Calculate field averages
        field_scores = {}
        for field in self.fields:
            field_scores[field] = sum(getattr(r, f"{field}_score") for r in self.current_results) / total
        
        avg_overall = sum(r.overall_score for r in self.current_results) / total
        avg_parse_time = sum(r.parse_time for r in self.current_results) / total
        
        model_name = self.current_results[0].model_name
        prompt_version = self.current_results[0].prompt_version
        parse_errors = sum(1 for r in self.current_results if r.parse_error)
        
        # Write header if needed
        if not csv_path.exists():
            headers = ["timestamp", "model", "prompt_version", "total_tests", "overall_score",
                      "avg_parse_time", "parse_errors", "est_10k_hours"] + \
                     [f"{field}_score" for field in self.fields]
            
            with open(csv_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
        
        # Write row
        row = [
            datetime.now().isoformat(),
            model_name,
            prompt_version,
            total,
            f"{avg_overall:.3f}",
            f"{avg_parse_time:.3f}",
            parse_errors,
            f"{avg_parse_time * 10000 / 3600:.1f}"
        ] + [f"{field_scores[field]:.3f}" for field in self.fields]
        
        with open(csv_path, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(row)
    
    def print_summary(self):
        """Print detailed summary of current results (scored tests only)"""
        if not self.current_results:
            print("No scored test results to summarize")
            return
        
        total = len(self.current_results)
        model = self.current_results[0].model_name
        
        print(f"\n{'='*80}")
        print(f"SCORED TESTS SUMMARY: {model}")
        print(f"{'='*80}")
        
        # Overall metrics
        avg_overall = sum(r.overall_score for r in self.current_results) / total * 100
        avg_time = sum(r.parse_time for r in self.current_results) / total
        
        print(f"\nOverall Performance: {avg_overall:.1f}%")
        print(f"Avg Parse Time: {avg_time:.3f}s")
        print(f"Est. 10K files: {avg_time * 10000 / 3600:.1f} hours")
        
        # Field-by-field accuracy
        print(f"\nField Accuracy:")
        field_scores = {}
        for field in self.fields:
            scores = [getattr(r, f"{field}_score") for r in self.current_results]
            avg_score = sum(scores) / len(scores) * 100
            field_scores[field] = avg_score
            print(f"  {field:12}: {avg_score:5.1f}%")
        
        # Parse errors
        parse_errors = [r for r in self.current_results if r.parse_error]
        if parse_errors:
            print(f"\nParse Errors: {len(parse_errors)}/{total}")
            for r in parse_errors[:3]:
                print(f"  {r.filename}: {r.parse_error}")
        
        # Common issues by field
        print(f"\nCommon Issues by Field:")
        for field in self.fields:
            all_errors = []
            for r in self.current_results:
                all_errors.extend(r.field_errors.get(field, []))
            
            if all_errors:
                print(f"\n  {field}:")
                for error, count in Counter(all_errors).most_common(3):
                    print(f"    - {error}: {count}x")
        
        # Detailed results
        print(f"\n{'='*80}")
        print("DETAILED RESULTS")
        print(f"{'='*80}")
        
        for r in self.current_results:
            status = "✓" if r.overall_score >= 0.8 else "✗"
            print(f"\n[{status}] {r.filename}")
            print(f"    Overall: {r.overall_score:.2f}")
            print(f"    Time: {r.parse_time:.3f}s")
            
            # Show extracted values
            if r.extracted_date:
                print(f"    Date: {r.extracted_date}")
            if r.extracted_location:
                print(f"    Location: {r.extracted_location}")
            if r.extracted_poi:
                print(f"    POI: {r.extracted_poi}")
            if r.extracted_names:
                print(f"    Names: {r.extracted_names}")
            if r.extracted_sequence:
                print(f"    Sequence: {r.extracted_sequence}")
            if r.extracted_event:
                print(f"    Event: {r.extracted_event}")
            if r.extracted_address:
                print(f"    Address: {r.extracted_address}")
            
            # Show errors
            for field, errors in r.field_errors.items():
                if errors:
                    print(f"    {field} issues: {', '.join(errors)}")


class ModelComparisonTracker:
    """Track and compare results across multiple models"""
    
    def __init__(self):
        self.model_results: Dict[str, Dict] = {}  # model_name -> results summary
        self.test_case_failures: Dict[str, List[str]] = {}  # filename -> list of failed models
        self.current_model = None
        self.total_models = 0
        self.completed_models = 0
    
    def start_model(self, model_name: str, total_models: int):
        """Start tracking a new model"""
        self.current_model = model_name
        self.total_models = total_models
        self.model_results[model_name] = {
            'results': [],
            'start_time': time.time(),
            'progress': 0,
            'total_tests': 0
        }
    
    def update_progress(self, current: int, total: int, current_score: float = None):
        """Update progress for current model"""
        if self.current_model:
            self.model_results[self.current_model]['progress'] = current
            self.model_results[self.current_model]['total_tests'] = total
            if current_score is not None:
                self.model_results[self.current_model]['running_score'] = current_score
    
    def finish_model(self, results: List[TestResult]):
        """Finish tracking current model"""
        if self.current_model and results:
            model_data = self.model_results[self.current_model]
            model_data['results'] = results
            model_data['end_time'] = time.time()
            model_data['total_time'] = model_data['end_time'] - model_data['start_time']
            
            # Calculate summary stats
            model_data['overall_score'] = sum(r.overall_score for r in results) / len(results)
            model_data['avg_parse_time'] = sum(r.parse_time for r in results) / len(results)
            model_data['parse_errors'] = sum(1 for r in results if r.parse_error)
            
            # Field scores
            for field in ["date", "location", "poi", "address", "names", "sequence", "event"]:
                scores = [getattr(r, f"{field}_score") for r in results]
                model_data[f"{field}_score"] = sum(scores) / len(scores)
            
            # Track failures by test case
            for result in results:
                if result.overall_score < 0.8:
                    if result.filename not in self.test_case_failures:
                        self.test_case_failures[result.filename] = []
                    self.test_case_failures[result.filename].append(self.current_model)
            
            self.completed_models += 1
    
    def print_progress_bar(self):
        """Print live progress bars for all models"""
        # Build the entire output as a string
        output_lines = []
        output_lines.append("Testing Models...")
        output_lines.append("━" * 80)
        
        for model_name, data in self.model_results.items():
            progress = data.get('progress', 0)
            total = data.get('total_tests', 0)
            score = data.get('running_score', 0)
            
            if total > 0:
                pct = progress / total
                bar_width = 20
                filled = int(bar_width * pct)
                bar = "█" * filled + "░" * (bar_width - filled)
                
                status = "✓" if progress == total else "→"
                avg_time = data.get('avg_parse_time', 0)
                
                output_lines.append(f"{model_name:20} [{bar}] {progress:2d}/{total:2d}  "
                                  f"Score: {score*100:4.1f}%  ⏱ {avg_time:.2f}s  {status}")
            else:
                output_lines.append(f"{model_name:20} [{'░' * 20}]  Queued...")
        
        output_lines.append("━" * 80)
        
        # Clear screen and print all at once
        print("\033[H\033[2J", end="")  # Home cursor, then clear screen
        print("\n".join(output_lines), flush=True)
    
    def print_comparison_dashboard(self):
        """Print comprehensive comparison dashboard"""
        if not self.model_results:
            return
        
        print("\n" + "═" * 80)
        print("MULTI-MODEL COMPARISON DASHBOARD")
        print("═" * 80)
        
        # Leaderboard
        print("\n🏆 LEADERBOARD (by Overall Score)")
        print("┌─────────────────────────┬─────────┬────────┬────────┬─────────────┐")
        print("│ Model                   │ Overall │ Speed  │ Errors │ Best Field  │")
        print("├─────────────────────────┼─────────┼────────┼────────┼─────────────┤")
        
        sorted_models = sorted(self.model_results.items(), 
                             key=lambda x: x[1].get('overall_score', 0), 
                             reverse=True)
        
        for rank, (model_name, data) in enumerate(sorted_models, 1):
            if 'overall_score' not in data:
                continue
                
            # Find best field
            field_scores = {f: data.get(f"{f}_score", 0) for f in 
                          ["date", "location", "poi", "address", "names", "sequence", "event"]}
            best_field = max(field_scores.items(), key=lambda x: x[1])
            
            print(f"│ {rank}. {model_name:21} │ {data['overall_score']*100:5.1f}% │ "
                  f"{data['avg_parse_time']:5.1f}s │ {data['parse_errors']:6d} │ "
                  f"{best_field[0]} {best_field[1]*100:.0f}% │")
        
        print("└─────────────────────────┴─────────┴────────┴────────┴─────────────┘")
        
        # Field Performance Matrix
        print("\n📊 FIELD PERFORMANCE MATRIX")
        print("┌─────────────────────────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┐")
        print("│ Model                   │ Date │ Loc  │ POI  │ Addr │Names │ Seq  │Event │")
        print("├─────────────────────────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┤")
        
        for model_name, data in sorted_models:
            if 'overall_score' not in data:
                continue
            print(f"│ {model_name:23} │", end="")
            for field in ["date", "location", "poi", "address", "names", "sequence", "event"]:
                score = data.get(f"{field}_score", 0) * 100
                print(f" {score:3.0f}% │", end="")
            print()
        
        print("└─────────────────────────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┘")
        
        # Speed vs Accuracy Analysis
        print("\n⚡ SPEED vs ACCURACY ANALYSIS")
        
        valid_models = [(name, data) for name, data in self.model_results.items() 
                       if 'overall_score' in data]
        
        if valid_models:
            # Best balance (score * speed factor)
            best_balance = max(valid_models, 
                             key=lambda x: x[1]['overall_score'] / (1 + x[1]['avg_parse_time']))
            print(f"Best Balance: {best_balance[0]} "
                  f"({best_balance[1]['overall_score']*100:.1f}% @ {best_balance[1]['avg_parse_time']:.1f}s)")
            
            # Fastest
            fastest = min(valid_models, key=lambda x: x[1]['avg_parse_time'])
            print(f"Fastest: {fastest[0]} "
                  f"({fastest[1]['avg_parse_time']:.1f}s, but only {fastest[1]['overall_score']*100:.0f}% accurate)")
            
            # Most accurate
            most_accurate = max(valid_models, key=lambda x: x[1]['overall_score'])
            print(f"Most Accurate: {most_accurate[0]} "
                  f"({most_accurate[1]['overall_score']*100:.0f}%, but {most_accurate[1]['avg_parse_time']:.1f}s)")
    
    def print_problem_patterns(self):
        """Print universal challenges across models"""
        if not self.test_case_failures:
            return
            
        print("\n🔍 UNIVERSAL CHALLENGES (failed by 3+ models)")
        print("━" * 80)
        
        # Sort by number of failures
        sorted_failures = sorted(self.test_case_failures.items(), 
                               key=lambda x: len(x[1]), reverse=True)
        
        for filename, failed_models in sorted_failures:
            if len(failed_models) >= 3:
                # Find the specific issue from test case
                test_case = next((tc for tc in TEST_CASES if tc[0] == filename), None)
                if test_case:
                    print(f"\n• \"{filename}\" - Failed by {len(failed_models)}/{self.completed_models} models")
                    print(f"  → {test_case[1].get('notes', 'Complex pattern')}")
                    print(f"  Models that failed: {', '.join(failed_models[:5])}")
                    if len(failed_models) > 5:
                        print(f"  ... and {len(failed_models) - 5} more")
    
    def print_model_profiles(self):
        """Print model-specific insights"""
        print("\n📋 MODEL PROFILES")
        print("━" * 80)
        
        for model_name, data in self.model_results.items():
            if 'overall_score' not in data:
                continue
                
            print(f"\n{model_name}:")
            
            # Find weakest and strongest fields
            field_scores = {f: data.get(f"{f}_score", 0) for f in 
                          ["date", "location", "poi", "address", "names", "sequence", "event"]}
            
            weakest = min(field_scores.items(), key=lambda x: x[1])
            strongest = max(field_scores.items(), key=lambda x: x[1])
            
            print(f"  ❌ Weak: {weakest[0]} extraction ({weakest[1]*100:.0f}%)")
            print(f"  ✅ Strong: {strongest[0]} extraction ({strongest[1]*100:.0f}%)")
            
            # Speed assessment
            if data['avg_parse_time'] < 2.5:
                print(f"  ⚡ Fast processing ({data['avg_parse_time']:.1f}s avg)")
            elif data['avg_parse_time'] > 4.0:
                print(f"  🐌 Slow processing ({data['avg_parse_time']:.1f}s avg)")
            
            # Recommendation
            if data['overall_score'] > 0.8:
                print(f"  💡 Recommendation: Excellent choice for production use")
            elif data['overall_score'] > 0.65:
                print(f"  💡 Recommendation: Good for non-critical applications")
            else:
                print(f"  💡 Recommendation: Consider other models or prompt optimization")
    
    def print_quick_recommendations(self):
        """Print quick decision helper"""
        if not self.model_results:
            return
            
        print("\n🎯 QUICK RECOMMENDATIONS")
        print("━" * 80)
        
        valid_models = [(name, data) for name, data in self.model_results.items() 
                       if 'overall_score' in data]
        
        if valid_models:
            # Best overall
            best_overall = max(valid_models, key=lambda x: x[1]['overall_score'])
            print(f"For best overall accuracy → Use {best_overall[0]}")
            
            # Fastest
            fastest = min(valid_models, key=lambda x: x[1]['avg_parse_time'])
            print(f"For fastest processing → Use {fastest[0]}")
            
            # Best for specific fields
            for field in ["date", "location", "poi", "address"]:
                best_field = max(valid_models, key=lambda x: x[1].get(f"{field}_score", 0))
                if best_field[1].get(f"{field}_score", 0) > 0.7:
                    print(f"For {field}-heavy workloads → Use {best_field[0]}")
        
        print("\nPrompt Analysis:")
        if valid_models:
            # Get prompt version from first model's results
            first_model = valid_models[0][1]
            if first_model.get('results'):
                prompt_version = first_model['results'][0].prompt_version
                print(f"Current prompt: '{prompt_version}'")
        print("Consider testing different prompts for poorly performing models")
    
    def export_comparison_data(self, run_id: str):
        """Export comprehensive comparison data"""
        comparison_data = {
            'run_id': run_id,
            'timestamp': datetime.now().isoformat(),
            'summary_rankings': [],
            'field_performance_matrix': {},
            'problem_patterns': {},
            'recommendations': {},
            'detailed_results': {}
        }
        
        # Summary rankings
        sorted_models = sorted(self.model_results.items(), 
                             key=lambda x: x[1].get('overall_score', 0), 
                             reverse=True)
        
        for rank, (model_name, data) in enumerate(sorted_models, 1):
            if 'overall_score' in data:
                comparison_data['summary_rankings'].append({
                    'rank': rank,
                    'model': model_name,
                    'overall_score': data['overall_score'],
                    'avg_parse_time': data['avg_parse_time'],
                    'parse_errors': data['parse_errors']
                })
        
        # Field performance matrix
        for model_name, data in self.model_results.items():
            if 'overall_score' in data:
                comparison_data['field_performance_matrix'][model_name] = {
                    field: data.get(f"{field}_score", 0)
                    for field in ["date", "location", "poi", "address", "names", "sequence", "event"]
                }
        
        # Problem patterns
        comparison_data['problem_patterns'] = {
            filename: failed_models 
            for filename, failed_models in self.test_case_failures.items()
            if len(failed_models) >= 3
        }
        
        # Save to file
        filepath = Path("test_results") / f"model_comparison_{run_id}.json"
        filepath.parent.mkdir(exist_ok=True)
        
        with open(filepath, 'w') as f:
            json.dump(comparison_data, f, indent=2)
        
        print(f"\n📁 Comparison data exported to: {filepath}")


class MetadataExtractor:
    """Extract all metadata fields from LLM output"""
    
    @staticmethod
    def extract_json(text: str) -> Optional[Dict]:
        """Try to extract JSON from LLM output"""
        try:
            # Direct parse
            return json.loads(text)
        except:
            pass
        
        # Find JSON in text
        try:
            start = text.find('{')
            end = text.rfind('}')
            if start >= 0 and end > start:
                return json.loads(text[start:end+1])
        except:
            pass
        
        return None
    
    @staticmethod
    def extract_date(data: Dict) -> Optional[Dict]:
        """Extract date information"""
        if not data:
            return None
        
        date_info = {}
        
        # Check for date object
        if 'date' in data and isinstance(data['date'], dict):
            d = data['date']
            for field in ['year', 'month', 'day']:
                if field in d and d[field] is not None:
                    try:
                        date_info[field] = int(d[field])
                    except:
                        pass
        
        # Check top-level fields
        for field in ['year', 'month', 'day']:
            if field in data and data[field] is not None:
                try:
                    date_info[field] = int(data[field])
                except:
                    pass
        
        return date_info if date_info else None
    
    @staticmethod
    def extract_location(data: Dict) -> Optional[Dict]:
        """Extract location information"""
        if not data:
            return None
        
        location_info = {}
        
        # Check location object
        if 'location' in data and isinstance(data['location'], dict):
            loc = data['location']
            for field in ['city', 'state', 'country']:
                if loc.get(field):
                    location_info[field] = str(loc[field])
        
        # Check top-level
        for field in ['city', 'state', 'country']:
            if data.get(field):
                location_info[field] = str(data[field])
        
        return location_info if location_info else None
    
    @staticmethod
    def extract_field(data: Dict, field: str) -> Optional[str]:
        """Extract a simple string field"""
        if not data:
            return None
        
        value = data.get(field)
        if value and isinstance(value, str):
            return value
        elif value:
            return str(value)
        
        # Check alternative names
        alternatives = {
            'poi': ['point_of_interest', 'landmark', 'place'],
            'names': ['name', 'people', 'person', 'photographer'],
            'event': ['events', 'occasion']
        }
        
        if field in alternatives:
            for alt in alternatives[field]:
                if data.get(alt):
                    return str(data[alt])
        
        return None
    
    @staticmethod
    def score_field(expected: Any, actual: Any, field_type: str) -> Tuple[float, List[str]]:
        """Score a field extraction and return errors"""
        errors = []
        
        # Handle None/empty cases
        if not expected and not actual:
            return 1.0, errors
        
        if not expected and actual:
            errors.append(f"Unexpected {field_type}: {actual}")
            return 0.5, errors  # Partial credit for extra info
        
        if expected and not actual:
            errors.append(f"Missing {field_type}")
            return 0.0, errors
        
        # Type-specific scoring
        if field_type == "date":
            score = 0.0
            total = len(expected)
            for key in ['year', 'month', 'day']:
                if key in expected:
                    if key in actual and actual[key] == expected[key]:
                        score += 1
                    else:
                        errors.append(f"Wrong {key}: expected {expected[key]}, got {actual.get(key)}")
            return score / total if total > 0 else 0.0, errors
        
        elif field_type == "location":
            score = 0.0
            total = len(expected)
            for key in ['city', 'state', 'country']:
                if key in expected:
                    if key in actual and actual[key].lower() == expected[key].lower():
                        score += 1
                    else:
                        errors.append(f"Wrong {key}: expected {expected[key]}, got {actual.get(key)}")
            return score / total if total > 0 else 0.0, errors
        
        else:
            # String comparison
            if str(actual).lower() == str(expected).lower():
                return 1.0, errors
            else:
                errors.append(f"Wrong: expected '{expected}', got '{actual}'")
                return 0.0, errors


class LLMAdapter:
    """Base class for LLM adapters"""
    
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.is_loaded = False
    
    def load(self):
        """Load the model"""
        raise NotImplementedError
    
    def generate(self, prompt: str, max_tokens: int = 400) -> str:
        """Generate response from prompt"""
        raise NotImplementedError
    
    def unload(self):
        """Unload the model to free memory"""
        pass


class LlamaCppAdapter(LLMAdapter):
    """Adapter for llama-cpp-python models"""
    
    def __init__(self, model_name: str, repo_id: str, filename: str, **kwargs):
        super().__init__(model_name)
        self.repo_id = repo_id
        self.filename = filename
        self.kwargs = kwargs
        self.llm = None
    
    def load(self):
        try:
            from llama_cpp import Llama
            from huggingface_hub import hf_hub_download
            
            print(f"Loading {self.model_name}...")
            model_path = hf_hub_download(
                repo_id=self.repo_id,
                filename=self.filename,
                cache_dir=Path(".llm_cache")
            )
            
            self.llm = Llama(
                model_path=str(model_path),
                n_ctx=2048,
                n_gpu_layers=-1,
                verbose=False,
                **self.kwargs
            )
            self.is_loaded = True
            print(f"✓ {self.model_name} loaded\n")
            
        except ImportError:
            raise ImportError("Please install llama-cpp-python and huggingface-hub")
    
    def generate(self, prompt: str, max_tokens: int = 400) -> str:
        if not self.is_loaded:
            raise RuntimeError("Model not loaded")
        
        response = self.llm(
            prompt,
            max_tokens=max_tokens,
            temperature=0.1,
            echo=False
        )
        return response['choices'][0]['text'].strip()


class TestHarness:
    """Main test harness"""
    
    def __init__(self, prompt_version: str = "comprehensive_v1", comparison_tracker: ModelComparisonTracker = None):
        self.prompt_version = prompt_version
        self.results_tracker = ResultsTracker()
        self.comparison_tracker = comparison_tracker
        
        # Comprehensive prompt
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
    
    def test_model(self, adapter: LLMAdapter, test_cases=None, custom_filenames=None):
        """Test a model against both scored test cases and custom filenames"""
        if test_cases is None:
            test_cases = TEST_CASES
        
        if not self.comparison_tracker:
            # Original single-model behavior
            print(f"Testing {adapter.model_name} with prompt {self.prompt_version}")
            print("="*60)
        
        # Load model once
        adapter.load()
        
        # First run scored test cases
        if not self.comparison_tracker:
            print(f"\n=== SCORED TEST CASES ({len(test_cases)} files) ===")
        
        running_scores = []
        for idx, (filename, test_data) in enumerate(test_cases):
            if not self.comparison_tracker:
                print(f"\nTesting: {filename}")
            
            # Generate prompt
            prompt = self.prompt_template.replace("{filename}", filename)
            
            # Time the generation
            start_time = time.time()
            try:
                raw_output = adapter.generate(prompt)
                parse_time = time.time() - start_time
                parse_error = None
            except Exception as e:
                raw_output = str(e)
                parse_time = time.time() - start_time
                parse_error = str(e)
            
            # Extract all fields
            parsed_json = MetadataExtractor.extract_json(raw_output) if not parse_error else None
            
            extracted = {
                'date': MetadataExtractor.extract_date(parsed_json),
                'location': MetadataExtractor.extract_location(parsed_json),
                'poi': MetadataExtractor.extract_field(parsed_json, 'poi'),
                'address': MetadataExtractor.extract_field(parsed_json, 'address'),
                'names': MetadataExtractor.extract_field(parsed_json, 'names'),
                'sequence': MetadataExtractor.extract_field(parsed_json, 'sequence'),
                'event': MetadataExtractor.extract_field(parsed_json, 'event')
            }
            
            # Score each field
            field_scores = {}
            field_errors = {}
            
            # Date
            expected_date = test_data.get("date", {})
            field_scores['date'], field_errors['date'] = MetadataExtractor.score_field(
                expected_date, extracted['date'], 'date')
            
            # Location
            expected_location = test_data.get("location", {})
            field_scores['location'], field_errors['location'] = MetadataExtractor.score_field(
                expected_location, extracted['location'], 'location')
            
            # Other fields
            for field in ['poi', 'address', 'names', 'sequence', 'event']:
                expected = test_data.get(field)
                actual = extracted.get(field)
                field_scores[field], field_errors[field] = MetadataExtractor.score_field(
                    expected, actual, field)
            
            # Overall score
            overall_score = sum(field_scores.values()) / len(field_scores)
            
            # Create result
            result = TestResult(
                filename=filename,
                model_name=adapter.model_name,
                prompt_version=self.prompt_version,
                timestamp=datetime.now().isoformat(),
                parse_time=parse_time,
                raw_output=raw_output,
                parsed_json=parsed_json,
                parse_error=parse_error,
                extracted_date=extracted['date'],
                extracted_location=extracted['location'],
                extracted_poi=extracted['poi'],
                extracted_address=extracted['address'],
                extracted_names=extracted['names'],
                extracted_sequence=extracted['sequence'],
                extracted_event=extracted['event'],
                date_score=field_scores['date'],
                location_score=field_scores['location'],
                poi_score=field_scores['poi'],
                address_score=field_scores['address'],
                names_score=field_scores['names'],
                sequence_score=field_scores['sequence'],
                event_score=field_scores['event'],
                overall_score=overall_score,
                field_errors=field_errors
            )
            
            self.results_tracker.add_result(result)
            
            # Track running score
            running_scores.append(overall_score)
            current_avg = sum(running_scores) / len(running_scores)
            
            # Update progress if using comparison tracker
            if self.comparison_tracker:
                self.comparison_tracker.update_progress(idx + 1, len(test_cases), current_avg)
                self.comparison_tracker.print_progress_bar()
            else:
                # Original single-model feedback
                status = "✓" if overall_score >= 0.8 else "✗"
                print(f"  {status} Score: {overall_score:.2f}")
                if parse_error:
                    print(f"  ⚠ Parse error: {parse_error}")
        
        # Then run custom filenames if provided
        custom_results = []
        if custom_filenames:
            if not self.comparison_tracker:
                print(f"\n\n=== CUSTOM FILENAMES ({len(custom_filenames)} files) ===")
            
            for filename in custom_filenames:
                if not self.comparison_tracker:
                    print(f"\n{'='*60}")
                    print(f"Filename: {filename}")
                    print(f"{'='*60}")
                
                # Generate prompt
                prompt = self.prompt_template.replace("{filename}", filename)
                
                # Time the generation
                start_time = time.time()
                try:
                    raw_output = adapter.generate(prompt)
                    parse_time = time.time() - start_time
                    parse_error = None
                except Exception as e:
                    raw_output = str(e)
                    parse_time = time.time() - start_time
                    parse_error = str(e)
                
                # Extract all fields
                parsed_json = MetadataExtractor.extract_json(raw_output) if not parse_error else None
                
                if parse_error:
                    if not self.comparison_tracker:
                        print(f"❌ Parse Error: {parse_error}")
                    continue
                
                if not parsed_json:
                    if not self.comparison_tracker:
                        print(f"❌ Failed to extract JSON from output")
                        print(f"Raw output: {raw_output[:200]}...")
                    continue
                
                # Extract fields
                extracted = {
                    'date': MetadataExtractor.extract_date(parsed_json),
                    'location': MetadataExtractor.extract_location(parsed_json),
                    'poi': MetadataExtractor.extract_field(parsed_json, 'poi'),
                    'address': MetadataExtractor.extract_field(parsed_json, 'address'),
                    'names': MetadataExtractor.extract_field(parsed_json, 'names'),
                    'sequence': MetadataExtractor.extract_field(parsed_json, 'sequence'),
                    'event': MetadataExtractor.extract_field(parsed_json, 'event')
                }
                
                # Display results only if not using comparison tracker
                if not self.comparison_tracker:
                    print(f"\n📅 Date:")
                    if extracted['date']:
                        date = extracted['date']
                        # Build date string carefully handling None values
                        year = date.get('year', '????')
                        month = date.get('month')
                        day = date.get('day')
                        
                        if month is not None and day is not None:
                            date_str = f"{year}-{month:02d}-{day:02d}"
                        elif month is not None:
                            date_str = f"{year}-{month:02d}-??"
                        else:
                            date_str = f"{year}-??-??"
                        
                        print(f"   {date_str}")
                        for k, v in date.items():
                            print(f"   - {k}: {v}")
                    else:
                        print("   (none found)")
                    
                    print(f"\n📍 Location:")
                    if extracted['location']:
                        loc_parts = []
                        if extracted['location'].get('city'):
                            loc_parts.append(extracted['location']['city'])
                        if extracted['location'].get('state'):
                            loc_parts.append(extracted['location']['state'])
                        if extracted['location'].get('country'):
                            loc_parts.append(extracted['location']['country'])
                        print(f"   {', '.join(loc_parts)}")
                        for k, v in extracted['location'].items():
                            print(f"   - {k}: {v}")
                    else:
                        print("   (none found)")
                    
                    if extracted['poi']:
                        print(f"\n🏛️  POI: {extracted['poi']}")
                    
                    if extracted['address']:
                        print(f"\n🏠 Address: {extracted['address']}")
                    
                    if extracted['names']:
                        print(f"\n👤 Names: {extracted['names']}")
                    
                    if extracted['sequence']:
                        print(f"\n🔢 Sequence: {extracted['sequence']}")
                    
                    if extracted['event']:
                        print(f"\n🎉 Event: {extracted['event']}")
                    
                    print(f"\n⏱️  Parse time: {parse_time:.3f}s")
                    
                    # Also show the raw JSON for easy copying
                    print(f"\n📋 Raw extracted JSON:")
                    print(json.dumps(parsed_json, indent=2))
                
                # Store result
                custom_results.append({
                    'filename': filename,
                    'parse_time': parse_time,
                    'extracted': extracted,
                    'raw_json': parsed_json
                })
            
            # Custom summary only if not using comparison tracker
            if custom_results and not self.comparison_tracker:
                print(f"\n{'='*80}")
                print(f"CUSTOM FILES SUMMARY")
                print(f"{'='*80}")
                
                successful = len([r for r in custom_results if r['extracted']['date'] or r['extracted']['location']])
                print(f"Files with metadata: {successful}/{len(custom_filenames)}")
                
                avg_time = sum(r['parse_time'] for r in custom_results) / len(custom_results) if custom_results else 0
                print(f"Average parse time: {avg_time:.3f}s")
        else:
            # No custom filenames provided
            if not self.comparison_tracker:
                print(f"\n\n{'='*80}")
                print("💡 TIP: Add your own filenames to test!")
                print("Find CUSTOM_FILENAMES list near line 165 and add your filenames there")
                print("Example: CUSTOM_FILENAMES = ['IMG_1234.heic', 'vacation_2023.heic']")
                print("Then run: uv run Multiple_LLM_Filename_Test_Harness.py")
                print(f"{'='*80}")
        
        # Unload model
        adapter.unload()
        
        # Save results
        run_id = f"{adapter.model_name}_{self.prompt_version}_{int(time.time())}"
        self.results_tracker.save_results(run_id, custom_results)
        self.results_tracker.save_summary_csv()
        
        # Print summary only if not using comparison tracker
        if not self.comparison_tracker:
            self.results_tracker.print_summary()
        else:
            # Let comparison tracker know this model is done
            self.comparison_tracker.finish_model(self.results_tracker.current_results)
        
        # Clear for next model
        self.results_tracker.current_results = []


# ============================================================================
# CUSTOM TEST FILENAMES - Add your own filenames here!
# ============================================================================

CUSTOM_FILENAMES = [
    # Add your own filenames here to test without expected outputs
    # Just paste them as strings, one per line
    # Examples:
    # "IMG_20230615_142532.heic",
    # "family_reunion_grandma_house_july_2023_001.heic",
    # "disney_world_orlando_florida_summer_vacation_2022.heic",
    # "DSC_0234.heic",
    # "wedding_sarah_john_central_park_nyc_september_15_2023.heic",
    # "birthday_party_chuck_e_cheese_tommy_5th_2024.heic",
    # "grand_canyon_sunrise_october_2022_pano_001.heic",
    
    # YOUR FILENAMES HERE (uncomment and add):
    # "your_actual_filename_here.heic",
    
]

# ============================================================================

# Model configurations
MODEL_CONFIGS = {
    "gemma-3-4b-q4": {
        "class": LlamaCppAdapter,
        "args": {
            "model_name": "Gemma-3-4B-Q4",
            "repo_id": "bartowski/google_gemma-3-4b-it-GGUF",
            "filename": "google_gemma-3-4b-it-Q4_K_M.gguf",
            "n_threads": 8
        }
    },
    "mistral-7b-v0.3-q4": {
        "class": LlamaCppAdapter,
        "args": {
            "model_name": "Mistral-7B-v0.3-Q4",
            "repo_id": "bartowski/Mistral-7B-Instruct-v0.3-GGUF",
            "filename": "Mistral-7B-Instruct-v0.3-Q4_K_M.gguf",
            "n_threads": 8
        }
    },
    "deepseek-r1-7b-q4": {
        "class": LlamaCppAdapter,
        "args": {
            "model_name": "DeepSeek-R1-7B-Q4",
            "repo_id": "unsloth/DeepSeek-R1-Distill-Qwen-7B-GGUF",
            "filename": "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",
            "n_threads": 8
        }
    },
    "gemma-3-4b-q3": {
        "class": LlamaCppAdapter,
        "args": {
            "model_name": "Gemma-3-4B-Q3",
            "repo_id": "bartowski/google_gemma-3-4b-it-GGUF",
            "filename": "google_gemma-3-4b-it-Q3_K_M.gguf",
            "n_threads": 8
        }
    },
    "deepseek-r1-7b-q3": {
        "class": LlamaCppAdapter,
        "args": {
            "model_name": "DeepSeek-R1-7B-Q3",
            "repo_id": "unsloth/DeepSeek-R1-Distill-Qwen-7B-GGUF",
            "filename": "DeepSeek-R1-Distill-Qwen-7B-Q3_K_M.gguf",
            "n_threads": 8
        }
    },
    "mistral-7b-v0.3-q3": {
        "class": LlamaCppAdapter,
        "args": {
            "model_name": "Mistral-7B-v0.3-Q3",
            "repo_id": "bartowski/Mistral-7B-Instruct-v0.3-GGUF",
            "filename": "Mistral-7B-Instruct-v0.3-Q3_K_M.gguf",
            "n_threads": 8
        }
    },
    "qwen2.5-7b-q3": {
        "class": LlamaCppAdapter,
        "args": {
            "model_name": "Qwen2.5-7B-Q3",
            "repo_id": "Qwen/Qwen2.5-7B-Instruct-GGUF",
            "filename": "qwen2.5-7b-instruct-q3_k_m.gguf",
            "n_threads": 8
        }
    },
    "llama-3.2-3b-q4": {
        "class": LlamaCppAdapter,
        "args": {
            "model_name": "Llama-3.2-3B-Q4",
            "repo_id": "bartowski/Llama-3.2-3B-Instruct-GGUF",
            "filename": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
            "n_threads": 8
        }
    },
    "gemma-3-4b-q2": {
        "class": LlamaCppAdapter,
        "args": {
            "model_name": "Gemma-3-4B-Q2",
            "repo_id": "bartowski/google_gemma-3-4b-it-GGUF",
            "filename": "google_gemma-3-4b-it-Q2_K.gguf",
            "n_threads": 8
        }
    },
    "deepseek-r1-7b-q2": {
        "class": LlamaCppAdapter,
        "args": {
            "model_name": "DeepSeek-R1-7B-Q2",
            "repo_id": "unsloth/DeepSeek-R1-Distill-Qwen-7B-GGUF",
            "filename": "DeepSeek-R1-Distill-Qwen-7B-Q2_K.gguf",
            "n_threads": 8
        }
    },
    "mistral-7b-v0.3-q2": {
        "class": LlamaCppAdapter,
        "args": {
            "model_name": "Mistral-7B-v0.3-Q2",
            "repo_id": "bartowski/Mistral-7B-Instruct-v0.3-GGUF",
            "filename": "Mistral-7B-Instruct-v0.3-Q2_K.gguf",
            "n_threads": 8
        }
    },
    "qwen2.5-7b-q2": {
        "class": LlamaCppAdapter,
        "args": {
            "model_name": "Qwen2.5-7B-Q2",
            "repo_id": "Qwen/Qwen2.5-7B-Instruct-GGUF",
            "filename": "qwen2.5-7b-instruct-q2_k.gguf",
            "n_threads": 8
        }
    },
    "llama-3.2-1b-q5": {
        "class": LlamaCppAdapter,
        "args": {
            "model_name": "Llama-3.2-1B-Q5",
            "repo_id": "unsloth/Llama-3.2-1B-Instruct-GGUF",
            "filename": "Llama-3.2-1B-Instruct-Q5_K_M.gguf",
            "n_threads": 8
        }
    },
    "phi-4-mini-q6": {
        "class": LlamaCppAdapter,
        "args": {
            "model_name": "phi-4-mini-q5",
            "repo_id": "unsloth/Llama-3.2-1B-Instruct-GGUF",
            "filename": "Phi-4-mini-instruct.Q6_K.gguf",
            "n_threads": 8
        }
    },
    "phi-3.5-mini": {
        "class": LlamaCppAdapter,
        "args": {
            "model_name": "Phi-3.5-mini",
            "repo_id": "bartowski/Phi-3.5-mini-instruct-GGUF",
            "filename": "Phi-3.5-mini-instruct-Q4_K_M.gguf",
            "n_threads": 8
        }
    }
}

def main():
    parser = argparse.ArgumentParser(description="Test LLMs for metadata extraction")
    parser.add_argument("models", nargs="*", help="Models to test (default: phi-3.5-mini)")
    parser.add_argument("--prompt", default="comprehensive_v1", help="Prompt version to use")
    parser.add_argument("--quick", action="store_true", help="Use subset of test cases")
    
    args = parser.parse_args()
    
    # Select models
    if args.models:
        models_to_test = args.models
    else:
        models_to_test = list(MODEL_CONFIGS.keys())  # Default to all
    
    # Select test cases
    test_cases = TEST_CASES[:5] if args.quick else TEST_CASES
    
    # Create comparison tracker if testing multiple models
    comparison_tracker = None
    if len(models_to_test) > 1:
        comparison_tracker = ModelComparisonTracker()
        print(f"🔬 Testing {len(models_to_test)} models on {len(test_cases)} test cases")
        print(f"📝 Prompt version: {args.prompt}")
        print(f"{'='*80}\n")
    
    # Test each model
    for idx, model_name in enumerate(models_to_test):
        if model_name not in MODEL_CONFIGS:
            print(f"Unknown model: {model_name}")
            print(f"Available: {', '.join(MODEL_CONFIGS.keys())}")
            continue
        
        # Start tracking this model
        if comparison_tracker:
            comparison_tracker.start_model(model_name, len(models_to_test))
        
        # Create harness (new instance for each model to ensure clean state)
        harness = TestHarness(prompt_version=args.prompt, comparison_tracker=comparison_tracker)
        
        config = MODEL_CONFIGS[model_name]
        adapter_class = config["class"]
        adapter = adapter_class(**config["args"])
        
        try:
            # Always test both scored cases and custom filenames
            harness.test_model(adapter, test_cases, CUSTOM_FILENAMES)
                
        except Exception as e:
            print(f"\n❌ Error testing {model_name}: {e}")
            import traceback
            traceback.print_exc()
        
        if not comparison_tracker:
            print("\n" + "="*80 + "\n")
    
    # Print comparison results if testing multiple models
    if comparison_tracker and comparison_tracker.completed_models > 0:
        print("\n" * 3)  # Clear some space
        comparison_tracker.print_comparison_dashboard()
        comparison_tracker.print_problem_patterns()
        comparison_tracker.print_model_profiles() 
        comparison_tracker.print_quick_recommendations()
        
        # Export comparison data
        run_id = f"comparison_{args.prompt}_{int(time.time())}"
        comparison_tracker.export_comparison_data(run_id)
        
        print(f"\n{'='*80}")
        print(f"✅ Tested {comparison_tracker.completed_models} models successfully")
        print(f"📊 Results saved to test_results/")
        print(f"{'='*80}")


if __name__ == "__main__":
    main()