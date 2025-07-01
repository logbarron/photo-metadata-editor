#!/usr/bin/env -S UV_NO_BINARY_PACKAGE=llama-cpp-python CMAKE_ARGS=-DGGML_CUDA=on FORCE_CMAKE=1 uv run --script
# /// script
# dependencies = [
#   "huggingface-hub",
#   "llama-cpp-python",
# ]
# ///

"""
Prompt Engineering Harness
Run on Cloud GPU
"""

import json
import time
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from dataclasses import dataclass, asdict
import argparse
import sys

# For LLM integration
from llama_cpp import Llama
from huggingface_hub import hf_hub_download


@dataclass
class TestCase:
    """Single test case from ground truth file"""
    test_id: str
    filename: str
    expected_date_suggestion: Optional[Dict[str, str]]
    expected_location_suggestion: Optional[Dict[str, Any]]
    
    @classmethod
    def from_json(cls, data: dict) -> 'TestCase':
        return cls(
            test_id=data['test_id'],
            filename=data['filename'],
            expected_date_suggestion=data.get('expected_date_suggestion'),
            expected_location_suggestion=data.get('expected_location_suggestion')
        )


@dataclass
class TestResult:
    """Result of testing a single filename"""
    test_case: TestCase
    llm_output: dict
    date_suggestion: Optional[dict]
    location_suggestion: Optional[dict]
    
    # Success metrics
    location_decision_correct: bool = False
    search_quality_good: bool = False
    date_extraction_correct: bool = False
    overall_success: bool = False
    
    # Error categorization
    error_type: Optional[str] = None
    error_details: Optional[str] = None


class PromptEngineeringHarness:
    """Simple, practical harness for prompt iteration"""
    
    def __init__(self, test_file: str, cache_dir: Path = Path("./llm_cache")):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(exist_ok=True)
        
        # Load test cases
        print(f"Loading test cases from: {test_file}")
        self.test_cases = self._load_test_cases(test_file)
        print(f"Loaded {len(self.test_cases)} test cases")
        
        # Split data (70% train, 30% validation)
        split_idx = int(len(self.test_cases) * 0.7)
        self.train_cases = self.test_cases[:split_idx]
        self.val_cases = self.test_cases[split_idx:]
        print(f"Split: {len(self.train_cases)} train, {len(self.val_cases)} validation")
        
        # Initialize LLM
        self.llm = None
        self._load_llm()
        
        # Tracking
        self.baseline_results = None
        self.current_best = None
        self.last_results = None
        self.iteration = 0
        
    def _load_test_cases(self, test_file: str) -> List[TestCase]:
        """Load test cases from JSON file"""
        with open(test_file, 'r') as f:
            data = json.load(f)
        
        # Handle different JSON structures
        if isinstance(data, list):
            cases_data = data
        elif isinstance(data, dict):
            # Look for common keys
            if 'ground_truth_examples' in data:
                cases_data = data['ground_truth_examples']
            elif 'test_cases' in data:
                cases_data = data['test_cases']
            elif 'examples' in data:
                cases_data = data['examples']
            else:
                # Maybe it's a single test case
                cases_data = [data]
        else:
            raise ValueError(f"Unexpected JSON structure: {type(data)}")
            
        return [TestCase.from_json(case) for case in cases_data]
    
    def _load_llm(self):
        """Load Mistral-7B model"""
        print("Loading Mistral-7B model...")
        model_path = hf_hub_download(
            repo_id="bartowski/Mistral-7B-Instruct-v0.3-GGUF",
            filename="Mistral-7B-Instruct-v0.3-Q4_K_M.gguf",
            cache_dir=self.cache_dir
        )
        
        self.llm = Llama(
            model_path=str(model_path),
            n_ctx=2048,
            n_gpu_layers=-1,
            verbose=False,
            n_threads=32,
            seed=42  # For reproducibility
        )
        print("Model loaded")
    
    def test_prompt(self, prompt: str, prompt_name: str = "New Prompt", 
                   notes: str = "", is_baseline: bool = False) -> Dict[str, Any]:
        """Test a prompt and return results"""
        
        if not is_baseline:
            self.iteration += 1
            
        print(f"\n{'='*70}")
        print(f"Testing: {prompt_name}")
        if notes:
            print(f"Notes: {notes}")
        print(f"{'='*70}")
        
        # Test on both splits
        print(f"\nTesting on training set ({len(self.train_cases)} cases)...")
        train_results = self._test_on_cases(prompt, self.train_cases, show_progress=True)
        
        print(f"\nTesting on validation set ({len(self.val_cases)} cases)...")
        val_results = self._test_on_cases(prompt, self.val_cases, show_progress=True)
        
        # Calculate metrics
        metrics = self._calculate_metrics(train_results, val_results)
        
        # Store results
        results = {
            'prompt_name': prompt_name,
            'iteration': self.iteration if not is_baseline else 0,
            'notes': notes,
            'timestamp': datetime.now().isoformat(),
            'metrics': metrics,
            'train_results': train_results,
            'val_results': val_results,
            'prompt_hash': hashlib.md5(prompt.encode()).hexdigest()[:8]
        }
        
        # Update tracking
        if is_baseline:
            self.baseline_results = results
            self.current_best = results
        else:
            self.last_results = results
            if metrics['val_success_rate'] > self.current_best['metrics']['val_success_rate']:
                self.current_best = results
                
        # Display results
        self._display_results(results)
        
        # Show comparisons
        if not is_baseline:
            self._display_comparisons(results)
            
        # Generate analysis file
        analysis_file = self._generate_analysis(results, prompt)
        print(f"\nAnalysis saved to: {analysis_file}")
        print("Share this file with your LLM for prompt improvements")
        
        return results
    
    def _test_on_cases(self, prompt: str, cases: List[TestCase], 
                      show_progress: bool = False) -> List[TestResult]:
        """Test prompt on a set of cases"""
        results = []
        
        for i, test_case in enumerate(cases):
            if show_progress:
                print(f"  Progress: {i+1}/{len(cases)} - {test_case.filename[:50]}...", end='\r')
                
            try:
                result = self._test_single_case(prompt, test_case)
                results.append(result)
            except Exception as e:
                print(f"\n  Error on case {i+1} ({test_case.filename}): {str(e)}")
                # Create a failed result
                result = TestResult(
                    test_case=test_case,
                    llm_output={"error": str(e)},
                    date_suggestion=None,
                    location_suggestion=None,
                    location_decision_correct=False,
                    search_quality_good=False,
                    date_extraction_correct=False,
                    overall_success=False,
                    error_type="test_error",
                    error_details=str(e)
                )
                results.append(result)
            
        if show_progress:
            print(f"  Completed {len(cases)} cases                                          ")
            
        return results
    
    def _test_single_case(self, prompt: str, test_case: TestCase) -> TestResult:
        """Test a single case"""
        # Format prompt with filename
        full_prompt = prompt.replace("{filename}", test_case.filename)
        
        # Call LLM
        try:
            response = self.llm(
                full_prompt,
                max_tokens=400,
                temperature=0.1,
                stop=["Filename:"],
                echo=False
            )
            
            llm_text = response['choices'][0]['text'].strip()
            llm_output = json.loads(llm_text)
        except Exception as e:
            llm_output = {"error": str(e)}
        
        # Convert to production format
        date_suggestion = self._to_date_suggestion(llm_output)
        location_suggestion = self._to_location_suggestion(llm_output)
        
        # Create result
        result = TestResult(
            test_case=test_case,
            llm_output=llm_output,
            date_suggestion=date_suggestion,
            location_suggestion=location_suggestion
        )
        
        # Evaluate success
        try:
            self._evaluate_result(result)
        except Exception as e:
            # Handle evaluation errors gracefully
            result.overall_success = False
            result.error_type = "evaluation_error"
            result.error_details = f"Error during evaluation: {str(e)}"
        
        return result
    
    def _to_date_suggestion(self, llm_output: dict) -> Optional[dict]:
        """Convert LLM output to date suggestion (production logic)"""
        if not llm_output or 'error' in llm_output:
            return None
            
        date_parts = None
        if 'extracted' in llm_output and isinstance(llm_output.get('extracted'), dict):
            date_parts = llm_output['extracted'].get('date_parts', {})
            
        if not date_parts or not isinstance(date_parts, dict):
            return None
            
        year = date_parts.get('year')
        month = date_parts.get('month')
        day = date_parts.get('day')
        
        # Convert to strings
        year = str(year) if year is not None else None
        month = str(month) if month is not None else None
        day = str(day) if day is not None else None
        
        if not year:
            return None
            
        # Ensure 2-digit format
        if month and len(month) == 1:
            month = f'0{month}'
        if day and len(day) == 1:
            day = f'0{day}'
            
        return {
            'year': year,
            'month': month or '',
            'day': day or '',
            'is_complete': bool(month)
        }
    
    def _to_location_suggestion(self, llm_output: dict) -> Optional[dict]:
        """Convert LLM output to location suggestion (production logic)"""
        if not llm_output or 'error' in llm_output:
            return None
            
        # Map confidence to numbers
        confidence_map = {
            "high": 85,
            "medium": 60,
            "low": 30,
            "none": 0
        }
        
        conf_str = llm_output.get("location_confidence", "none")
        confidence = confidence_map.get(conf_str, 0)
        
        # Apply threshold
        if confidence < 40:
            return None
            
        primary_search = llm_output.get("primary_search")
        if not primary_search:
            return None
            
        extracted = llm_output.get("extracted", {})
        
        return {
            'confidence': confidence,
            'primary_search': primary_search,
            'alternate_search': llm_output.get("alternate_search"),
            'location_type': llm_output.get("location_type"),
            'reasoning': llm_output.get("location_context", ''),
            'landmark_name': extracted.get("landmark_name", ''),
            'city': extracted.get('city', ''),
            'state': extracted.get('state', '').upper() if extracted.get('state') else '',
            'country': extracted.get('country', ''),
            'is_complete': confidence > 70
        }
    
    def _evaluate_result(self, result: TestResult):
        """Evaluate if result matches expected"""
        tc = result.test_case
        
        # Location decision
        expected_location = tc.expected_location_suggestion is not None
        got_location = result.location_suggestion is not None
        result.location_decision_correct = expected_location == got_location
        
        # Search quality (if both have locations)
        if expected_location and got_location:
            expected_search = tc.expected_location_suggestion.get('primary_search', '').lower()
            actual_search = result.location_suggestion.get('primary_search', '').lower()
            
            # Simple quality check - main terms present
            if expected_search and actual_search:
                expected_terms = set(expected_search.replace(',', '').split())
                actual_terms = set(actual_search.replace(',', '').split())
                
                # Good if actual doesn't have too many extra words
                extra_words = actual_terms - expected_terms
                result.search_quality_good = len(extra_words) <= 2
            else:
                result.search_quality_good = expected_search == actual_search
        else:
            result.search_quality_good = True  # N/A
            
        # Date extraction
        if tc.expected_date_suggestion:
            exp_date = tc.expected_date_suggestion
            got_date = result.date_suggestion or {}
            
            result.date_extraction_correct = (
                exp_date.get('year') == got_date.get('year') and
                exp_date.get('month') == got_date.get('month') and
                exp_date.get('day') == got_date.get('day')
            )
        else:
            result.date_extraction_correct = result.date_suggestion is None
            
        # Overall success
        result.overall_success = (
            result.location_decision_correct and
            result.search_quality_good and
            result.date_extraction_correct
        )
        
        # Categorize errors
        if not result.overall_success:
            if not result.location_decision_correct:
                if got_location and not expected_location:
                    result.error_type = "false_positive"
                    result.error_details = f"Suggested '{result.location_suggestion.get('primary_search')}' for non-location"
                else:
                    result.error_type = "false_negative"
                    result.error_details = f"Missed location '{tc.expected_location_suggestion.get('primary_search') if tc.expected_location_suggestion else 'unknown'}'"
            elif not result.search_quality_good:
                result.error_type = "search_quality"
                result.error_details = f"Expected '{tc.expected_location_suggestion.get('primary_search')}', got '{result.location_suggestion.get('primary_search')}'"
            elif not result.date_extraction_correct:
                result.error_type = "date_extraction"
                exp = tc.expected_date_suggestion
                got = result.date_suggestion or {}
                if exp:
                    result.error_details = f"Expected {exp.get('year')}-{exp.get('month')}-{exp.get('day')}, got {got.get('year')}-{got.get('month')}-{got.get('day')}"
                else:
                    result.error_details = f"Expected no date, but got {got.get('year')}-{got.get('month')}-{got.get('day')}"
    
    def _calculate_metrics(self, train_results: List[TestResult], 
                         val_results: List[TestResult]) -> Dict[str, Any]:
        """Calculate key metrics"""
        
        def calc_for_split(results):
            total = len(results)
            successes = sum(1 for r in results if r.overall_success)
            false_positives = sum(1 for r in results if r.error_type == "false_positive")
            
            # Group failures by type
            failures_by_type = {}
            for r in results:
                if not r.overall_success:
                    error_type = r.error_type or "other"
                    if error_type not in failures_by_type:
                        failures_by_type[error_type] = []
                    failures_by_type[error_type].append({
                        'filename': r.test_case.filename,
                        'details': r.error_details,
                        'expected_location': r.test_case.expected_location_suggestion,
                        'got_location': r.location_suggestion,
                        'expected_date': r.test_case.expected_date_suggestion,
                        'got_date': r.date_suggestion,
                        'llm_output': r.llm_output
                    })
                    
            return {
                'total_cases': total,
                'successes': successes,
                'success_rate': successes / total if total > 0 else 0,
                'false_positive_rate': false_positives / total if total > 0 else 0,
                'failures_by_type': failures_by_type
            }
        
        train_metrics = calc_for_split(train_results)
        val_metrics = calc_for_split(val_results)
        
        # Generalization gap
        gap = train_metrics['success_rate'] - val_metrics['success_rate']
        
        return {
            'train_success_rate': train_metrics['success_rate'],
            'val_success_rate': val_metrics['success_rate'],
            'generalization_gap': gap,
            'overfitting_risk': 'high' if gap > 0.05 else 'low',
            'train_metrics': train_metrics,
            'val_metrics': val_metrics
        }
    
    def _display_results(self, results: Dict[str, Any]):
        """Display results in terminal"""
        metrics = results['metrics']
        
        print(f"\nRESULTS: {results['prompt_name']}")
        print("─" * 50)
        print(f"Training:   {metrics['train_success_rate']:.1%} ({metrics['train_metrics']['successes']}/{metrics['train_metrics']['total_cases']})")
        print(f"Validation: {metrics['val_success_rate']:.1%} ({metrics['val_metrics']['successes']}/{metrics['val_metrics']['total_cases']})")
        print(f"Gap:        {metrics['generalization_gap']:+.1%} ({metrics['overfitting_risk']} risk)")
        
        # Show TRAINING failure breakdown
        train_failures = metrics['train_metrics']['failures_by_type']
        if train_failures:
            print(f"\nTraining Failures by Type:")
            for error_type, failures in train_failures.items():
                print(f"  {error_type}: {len(failures)} cases")
                # Show first few examples
                for i, failure in enumerate(failures[:3]):
                    print(f"    • {failure['filename']}")
                    print(f"      {failure['details']}")
                if len(failures) > 3:
                    print(f"    ... and {len(failures)-3} more")
        
        # Show validation failure breakdown
        val_failures = metrics['val_metrics']['failures_by_type']
        if val_failures:
            print(f"\nValidation Failures by Type:")
            for error_type, failures in val_failures.items():
                print(f"  {error_type}: {len(failures)} cases")
                for failure in failures[:2]:
                    print(f"    • {failure['filename']}")
                    print(f"      {failure['details']}")
                if len(failures) > 2:
                    print(f"    ... and {len(failures)-2} more")
    
    def _display_comparisons(self, results: Dict[str, Any]):
        """Display comparisons to baseline and last"""
        metrics = results['metrics']
        
        # vs Baseline
        if self.baseline_results:
            baseline_metrics = self.baseline_results['metrics']
            print(f"\nvs Production Baseline:")
            
            val_improvement = metrics['val_success_rate'] - baseline_metrics['val_success_rate']
            print(f"  Success Rate: {val_improvement:+.1%}")
            
            if val_improvement > 0.01:
                print(f"  BETTER than production!")
            elif val_improvement < -0.01:
                print(f"  WORSE than production")
            else:
                print(f"  Similar to production")
                
        # vs Last Attempt
        if self.last_results and self.iteration > 1:
            last_metrics = self.last_results['metrics']
            print(f"\nvs Last Attempt:")
            
            val_change = metrics['val_success_rate'] - last_metrics['val_success_rate']
            print(f"  Success Rate: {val_change:+.1%}")
            
            if val_change > 0.01:
                print(f"  Improvement!")
            elif val_change < -0.01:
                print(f"  Regression")
            else:
                print(f"  No significant change")
    

    
    def _generate_analysis(self, results: Dict[str, Any], prompt_text: str) -> str:
        """Generate analysis file for LLM"""
        
        # Analyze failure patterns
        train_failures = results['metrics']['train_metrics']['failures_by_type']
        val_failures = results['metrics']['val_metrics']['failures_by_type']
        
        # Build analysis
        analysis = {
            'iteration': results['iteration'],
            'timestamp': results['timestamp'],
            'notes': results['notes'],
            
            'performance': {
                'train_success': results['metrics']['train_success_rate'],
                'val_success': results['metrics']['val_success_rate'],
                'generalization_gap': results['metrics']['generalization_gap'],
                'overfitting_risk': results['metrics']['overfitting_risk']
            },
            
            'vs_baseline': None,
            'vs_last_attempt': None,
            
            'training_failures': {},
            'validation_failures': {},
            
            'current_prompt': prompt_text,
            
            'specific_improvements_needed': []
        }
        
        # Add comparisons
        if self.baseline_results:
            baseline_val = self.baseline_results['metrics']['val_success_rate']
            current_val = results['metrics']['val_success_rate']
            analysis['vs_baseline'] = {
                'baseline_success': baseline_val,
                'current_success': current_val,
                'improvement': current_val - baseline_val,
                'verdict': 'BETTER' if current_val > baseline_val + 0.01 else 'WORSE' if current_val < baseline_val - 0.01 else 'SIMILAR'
            }
            
        # Extract failure patterns with FULL details for training failures
        for error_type, failures in train_failures.items():
            analysis['training_failures'][error_type] = {
                'count': len(failures),
                'examples': failures  # ALL training failures with full details
            }
            
        for error_type, failures in val_failures.items():
            analysis['validation_failures'][error_type] = {
                'count': len(failures),
                'examples': failures  # ALL validation failures too
            }
        
        # Generate specific improvement recommendations based on failures
        if 'false_positive' in train_failures:
            analysis['specific_improvements_needed'].append({
                'issue': 'False positives on personal/generic locations',
                'count': len(train_failures['false_positive']),
                'suggestion': 'Need better rules to exclude non-searchable locations'
            })
        
        if 'false_negative' in train_failures:
            analysis['specific_improvements_needed'].append({
                'issue': 'Missing real locations',
                'count': len(train_failures['false_negative']),
                'suggestion': 'Need to recognize more location patterns'
            })
            
        if 'date_extraction' in train_failures:
            analysis['specific_improvements_needed'].append({
                'issue': 'Date parsing errors',
                'count': len(train_failures['date_extraction']),
                'suggestion': 'Need more robust date format handling'
            })
            
        # Save to file
        filename = f"iteration_{results['iteration']:03d}_analysis.json"
        with open(filename, 'w') as f:
            json.dump(analysis, f, indent=2)
            
        return filename
    
    def run_baseline(self, prompt: str):
        """Test the production baseline prompt"""
        return self.test_prompt(prompt, "Production Baseline", 
                               "Current production prompt", is_baseline=True)
    
    def run_iteration(self, prompt: str, notes: str = ""):
        """Run a new iteration"""
        return self.test_prompt(prompt, f"Iteration {self.iteration + 1}", notes)


def main():
    parser = argparse.ArgumentParser(description='Prompt Engineering Harness')
    parser.add_argument('test_file', help='Path to ground truth test file (JSON)')
    parser.add_argument('--baseline-prompt', help='Path to baseline prompt file')
    args = parser.parse_args()
    
    # Initialize harness
    harness = PromptEngineeringHarness(args.test_file)
    
    # Test baseline if provided
    if args.baseline_prompt:
        with open(args.baseline_prompt, 'r') as f:
            baseline_prompt = f.read()
        harness.run_baseline(baseline_prompt)
    
    # Interactive iteration loop
    print("\n" + "="*70)
    print("PROMPT ENGINEERING SESSION")
    print("="*70)
    print("Enter prompts to test iteratively.")
    print("Type 'quit' to exit.\n")
    
    while True:
        print(f"\nIteration {harness.iteration + 1}")
        print("Enter your prompt (type 'END' on a new line when done):")
        
        prompt_lines = []
        while True:
            line = input()
            if line.strip() == 'END':
                break
            if line.strip() == 'quit':
                print("Exiting...")
                sys.exit(0)
            prompt_lines.append(line)
            
        if not prompt_lines:
            print("No prompt entered. Try again.")
            continue
            
        prompt = '\n'.join(prompt_lines)
        
        notes = input("\nNotes for this iteration: ")
        
        # Test the prompt
        harness.run_iteration(prompt, notes)
        
        # Ask to continue
        cont = input("\nContinue with another iteration? [Y/n]: ")
        if cont.lower() == 'n':
            break
    
    print("\nSession complete!")
    print(f"Best validation performance: {harness.current_best['metrics']['val_success_rate']:.1%}")


if __name__ == "__main__":
    main()