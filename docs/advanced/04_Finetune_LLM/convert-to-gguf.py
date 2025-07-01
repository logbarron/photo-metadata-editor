#!/usr/bin/env python3
import subprocess
import sys
import os
import json
import shutil
from pathlib import Path

# Get checkpoint from command line (required)
if len(sys.argv) < 2:
    print(f"Error: No checkpoint specified")
    print(f"Usage: python {sys.argv[0]} <checkpoint_number>")
    print(f"Example: python {sys.argv[0]} 000700")
    checkpoints_dir = Path("runs/mistral-7b-finetuned/checkpoints")
    if checkpoints_dir.exists():
        print(f"\nAvailable checkpoints:")
        for cp in sorted(checkpoints_dir.glob("checkpoint_*")):
            print(f"  {cp.name.split('_')[1]}")
    sys.exit(1)

checkpoint_num = sys.argv[1]
checkpoint = f"checkpoint_{checkpoint_num}"

# Verify checkpoint exists
checkpoint_path = Path(f"runs/mistral-7b-finetuned/checkpoints/{checkpoint}")
if not checkpoint_path.exists():
    print(f"Error: {checkpoint} not found")
    checkpoints_dir = Path("runs/mistral-7b-finetuned/checkpoints")
    if checkpoints_dir.exists():
        print(f"Available checkpoints:")
        for cp in sorted(checkpoints_dir.glob("checkpoint_*")):
            print(f"  {cp.name.split('_')[1]}")
    sys.exit(1)

lora_path = checkpoint_path / "consolidated" / "lora.safetensors"
output_name = f"mistral-7b-finetuned-{checkpoint_num}-q4_k_m.gguf"
print(f"Converting checkpoint {checkpoint_num} to GGUF...")
print(f"Using: {lora_path}")
print(f"Output will be: {output_name}")
print()

# Ensure all dependencies are installed
print("Installing system dependencies...")
# Set non-interactive mode to avoid service restart prompts
os.environ['DEBIAN_FRONTEND'] = 'noninteractive'
subprocess.run(["sudo", "apt", "update"], check=True)
subprocess.run(["sudo", "apt", "install", "-y", "build-essential", "cmake", "git", "python3-pip"], check=True)

print("Installing Python dependencies...")
result = subprocess.run([sys.executable, "-m", "pip", "install", "safetensors", "torch", "transformers", "sentencepiece"])
if result.returncode != 0:
    print("\nERROR: Failed to install dependencies")
    print("If you see 'externally-managed-environment', run:")
    print("  pip install --break-system-packages safetensors torch transformers sentencepiece")
    print("\nThen run this script again.")
    sys.exit(1)

from safetensors.torch import load_file, save_file
import torch

# Create merged model directory
if Path("merged_model").exists():
    shutil.rmtree("merged_model")
Path("merged_model").mkdir()

# Load and merge weights
print("Merging LoRA weights...")
base_weights = load_file("mistral-7b-instruct-v0.3/consolidated.safetensors")
lora_weights = load_file(str(lora_path))

# Apply LoRA formula: W' = W + scale * BA
scale = 2.0  # from training config
for key in list(lora_weights.keys()):
    if key.endswith(".lora_A.weight"):
        base_key = key.replace(".lora_A.weight", ".weight")
        b_key = key.replace(".lora_A.weight", ".lora_B.weight")
        if base_key in base_weights and b_key in lora_weights:
            # Ensure computation matches base weight dtype
            dtype = base_weights[base_key].dtype
            lora_product = scale * (lora_weights[b_key] @ lora_weights[key])
            base_weights[base_key] += lora_product.to(dtype)

# Save with the filename convert_hf_to_gguf.py expects (not consolidated.safetensors)
save_file(base_weights, "merged_model/model.safetensors")

# Copy tokenizer - convert_hf_to_gguf.py needs tokenizer.model (not .v3)
shutil.copy2("mistral-7b-instruct-v0.3/tokenizer.model.v3", "merged_model/tokenizer.model")

# Copy params.json if it exists
if Path("mistral-7b-instruct-v0.3/params.json").exists():
    shutil.copy2("mistral-7b-instruct-v0.3/params.json", "merged_model/")

# Create config.json for HuggingFace format
config = {
    "architectures": ["MistralForCausalLM"],
    "model_type": "mistral",
    "vocab_size": 32768,
    "hidden_size": 4096,
    "intermediate_size": 14336,
    "num_hidden_layers": 32,
    "num_attention_heads": 32,
    "num_key_value_heads": 8,
    "hidden_act": "silu",
    "max_position_embeddings": 32768,
    "rms_norm_eps": 1e-05,
    "sliding_window": 4096,
    "rope_theta": 1000000.0,
    "torch_dtype": "bfloat16"
}
with open("merged_model/config.json", "w") as f:
    json.dump(config, f, indent=2)

# Build llama.cpp
if not Path("llama.cpp").exists():
    subprocess.run(["git", "clone", "https://github.com/ggerganov/llama.cpp.git"], check=True)

# Use cmake build with CURL disabled
if not Path("llama.cpp/build/bin/llama-quantize").exists():
    subprocess.run(["cmake", "-B", "llama.cpp/build", "-S", "llama.cpp", "-DLLAMA_CURL=OFF"], check=True)
    subprocess.run(["cmake", "--build", "llama.cpp/build", "--config", "Release"], check=True)

# Convert to GGUF using the NEW script name
print("Converting to GGUF...")
subprocess.run([
    sys.executable, "llama.cpp/convert_hf_to_gguf.py",
    "merged_model",
    "--outfile", "mistral-7b-finetuned-f16.gguf",
    "--outtype", "f16"
], check=True)

# Quantize to 4-bit using the CORRECT binary name
print("Quantizing to 4-bit...")
subprocess.run([
    "./llama.cpp/build/bin/llama-quantize",
    "mistral-7b-finetuned-f16.gguf",
    output_name,
    "q4_k_m"
], check=True)

# Cleanup
os.remove("mistral-7b-finetuned-f16.gguf")
shutil.rmtree("merged_model")

size_gb = Path(output_name).stat().st_size / 1e9
print(f"\nSuccess! Output: {output_name} ({size_gb:.1f}GB)")