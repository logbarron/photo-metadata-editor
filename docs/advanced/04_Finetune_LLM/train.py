#!/usr/bin/env python3
import subprocess
import sys
import os

# Force numpy<2 before any imports
subprocess.run([sys.executable, "-m", "pip", "install", "numpy<2", "--force-reinstall"], check=False)

# Add mistral-finetune to path
sys.path.insert(0, "./mistral-finetune")

# Print versions
import torch
import numpy
import transformers
print(f"torch=={torch.__version__}")
print(f"numpy=={numpy.__version__}")
print(f"transformers=={transformers.__version__}")

# Check files exist
if not os.path.exists("train_data.jsonl"):
    raise FileNotFoundError("train_data.jsonl not found")
if not os.path.exists("eval_data.jsonl"):
    raise FileNotFoundError("eval_data.jsonl not found")
if not os.path.exists("config.yaml"):
    raise FileNotFoundError("config.yaml not found")
if not os.path.exists("./mistral-finetune/train.py"):
    raise FileNotFoundError("mistral-finetune not found")

# Get GPU count
gpu_count = torch.cuda.device_count()
if gpu_count == 0:
    raise RuntimeError("No GPUs found")
print(f"GPUs: {gpu_count}")

# Set CUDA_VISIBLE_DEVICES
os.environ["CUDA_VISIBLE_DEVICES"] = ",".join(str(i) for i in range(gpu_count))

# Run training
cmd = [
    "torchrun",
    f"--nproc-per-node={gpu_count}",
    "-m", "train",
    "../config.yaml"
]

result = subprocess.run(cmd, cwd="./mistral-finetune")
sys.exit(result.returncode)