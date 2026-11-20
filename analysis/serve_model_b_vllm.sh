#!/bin/bash
# Serve Qwen3-14B-AWQ for Exercise 2 with thinking disabled.
# Run inside WSL: bash analysis/serve_model_b_vllm.sh   (log: ~/vllm_ex2.log, endpoint: http://localhost:8080/v1)
# VLLM_USE_FLASHINFER_SAMPLER=0: FlashInfer would JIT-compile its sampler and needs nvcc, which is not installed.
# max-model-len 12288: 16k did not leave enough KV-cache memory on a 16 GB GPU.
# Simulation env for this model: TEXT_MODEL_URL=http://localhost:8080/v1 TEXT_MODEL_KEY=local TEXT_MODEL_LLM=Qwen/Qwen3-14B-AWQ
export VLLM_USE_FLASHINFER_SAMPLER=0
exec ~/vllm-venv/bin/vllm serve Qwen/Qwen3-14B-AWQ \
  --port 8080 \
  --max-model-len 12288 \
  --gpu-memory-utilization 0.92 \
  --limit-mm-per-prompt '{"image":0,"video":0}' \
  --default-chat-template-kwargs '{"enable_thinking": false}' \
  > ~/vllm_ex2.log 2>&1
