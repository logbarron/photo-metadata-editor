# Mistral 7B Fine-tuningon 8x H100 @lambda.ai

# 1. Launch Lambda instance

# 2. Clone mistral-finetune (creates ./mistral-finetune directory)
git clone https://github.com/mistralai/mistral-finetune.git

# 3. Install HuggingFace CLI
pip install -U "huggingface_hub[cli]"
huggingface-cli login
huggingface-cli download mistralai/Mistral-7B-Instruct-v0.3 --include "params.json" "consolidated.safetensors" "tokenizer.model.v3" --local-dir ./mistral-7b-instruct-v0.3

# 4. Upload your files (from local machine)
scp train.py config.yaml prepare_data.py diagnose_deps.py convert-to-gguf.py requirements.txt data.jsonl ubuntu@IP:~/

# 5. Prepare data
python prepare_data.py data.jsonl

# 6. Check dependencies
python diagnose_deps.py

# 7. Install Requirements
pip install -r requirements.txt
cd mistral-finetune
pip install -r requirements.txt
cd ..
pip install mistral_common==1.3.1 --force-reinstall

# 8. Run training
python train.py

# 9. Convert to GGUF (Requires checkpoint number)
python convert-to-gguf.py 000700

# 10.  Download the GGUF (Requires checkpoint from above)
scp ubuntu@IP:~/mistral-7b-finetuned-000700-q4_k_m.gguf ./

--

# 11. If failure of GGUF conversion, download the full checkpoint (Requires the checkpoint from above)
scp -r ubuntu@IP:/home/ubuntu/runs/mistral-7b-finetuned/checkpoints/checkpoint_000700 ./

# 12. Convert to GGUF (Requires checkpoint number)
python convert-to-gguf_standalone.py 000700

