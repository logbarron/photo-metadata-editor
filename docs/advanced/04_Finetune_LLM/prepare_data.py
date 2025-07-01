#!/usr/bin/env python3
import json
import sys
import random

if len(sys.argv) != 2:
    print("Usage: python prepare_data.py input.jsonl")
    sys.exit(1)

input_file = sys.argv[1]

# Load data
with open(input_file, 'r') as f:
    data = [json.loads(line) for line in f]

# Split 90/10
random.seed(42)
random.shuffle(data)
split_idx = int(len(data) * 0.9)

# Save
with open('train_data.jsonl', 'w') as f:
    for item in data[:split_idx]:
        f.write(json.dumps(item) + '\n')

with open('eval_data.jsonl', 'w') as f:
    for item in data[split_idx:]:
        f.write(json.dumps(item) + '\n')

print(f"Train: {split_idx}")
print(f"Eval: {len(data) - split_idx}")