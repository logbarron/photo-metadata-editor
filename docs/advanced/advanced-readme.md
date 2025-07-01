# Advanced Development Tools

This directory documents the tools used to develop and improve the LLM model inside the metadata program

## Development Folders

### 01_Initial_Model_Evaluation
LLM Model comparison and selection tools
  - `Single_LLM_Filename_Test_Harness.py` - Tests one LLM model against 33 filename patterns
  - `Multiple_LLM_Filename_Test_Harness.py` - Compares multiple LLM models side-by-side against 33 filename patternsmultiple LLM models side-by-side against 33 filename patterns

### 02_File_Name_Generator
Synthetic data generation for training (creates data for Prompt Tune &/or Fine Tune)
  - `filename_generator_LLM_enrich.py` - Generates test filenames with ground truth and LLM reasoning
  - `dataforfilegenerator.json` - Location/name/pattern data used by the generator

### 03_Prompt_Tuning
Prompt optimization tools
  - `lambda_harness.py` - Interactive prompt testing on cloud GPU
  - `local_harness.py` - Same tool for local Mac testing
  - `production_prompt.txt` - Current production prompt
  - `lambda_cheatsheet.txt` - Quick reference for Lambda cloud setup

### 04_Finetune_LLM
Model fine-tuning pipeline
  - `train.py` - Fine-tuning script for Mistral-7B
  - `requirements.txt` - Python dependencies for training
  - `readme-finetune.md` - Step-by-step Lambda cloud instructions
  - `prepare_data.py` - Splits JSONL to training and evaluation
  - `diagnose_deps.py` - Verifies environment setup
  - `convert-to-gguf.py` - Converts checkpoint to GGUF on cloud
  - `convert-to-gguf_standalone.py` - Local GGUF conversion if cloud failure
  - `config.yaml` - Training hyperparameters