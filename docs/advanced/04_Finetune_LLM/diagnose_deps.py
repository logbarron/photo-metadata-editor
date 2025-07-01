#!/usr/bin/env python3
import subprocess
import sys

print(f"Python: {sys.version}")

result = subprocess.run([sys.executable, "-m", "pip", "list"], capture_output=True, text=True)
print("Pre-installed packages:")
for line in result.stdout.split('\n'):
    if any(pkg in line.lower() for pkg in ['numpy', 'torch', 'mistral']):
        print(f"  {line}")

sys.path.append('./mistral-finetune')
try:
    from train import main
    print("SUCCESS: mistral-finetune imports work")
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {e}")
    print("\nFull traceback:")
    import traceback
    traceback.print_exc()