#!/usr/bin/env python3
"""
Deploy Qwen2.5-3B-Instruct as local inference server.
Provides OpenAI-compatible API endpoint for router training.
"""

import argparse
import json
import time
from typing import Any
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch


# ============================================================
# Model Configuration
# ============================================================

# AutoDL has the model cached locally - use actual snapshot path
MODEL_PATH = "/root/.cache/huggingface/hub/models--Qwen--Qwen2.5-3B-Instruct/snapshots/aa8e72537993ba99e69dfaafa59ed015b17504d1"
MODEL_NAME = "Qwen/Qwen2.5-3B-Instruct"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
MAX_NEW_TOKENS = 512
TEMPERATURE = 0.7
TOP_P = 0.9


# ============================================================
# Global Model State
# ============================================================

tokenizer = None
model = None


def load_model():
    """Load model and tokenizer."""
    global tokenizer, model
    print(f"Loading {MODEL_NAME} from {MODEL_PATH} on {DEVICE}...")
    print(f"PyTorch version: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"CUDA device: {torch.cuda.get_device_name(0)}")

    # Use local cache with slow tokenizer (faster loading, avoids fast tokenizer issues)
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_PATH,
        trust_remote_code=True,
        local_files_only=True,
        use_fast=False,
    )

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH,
        torch_dtype=torch.float16 if DEVICE == "cuda" else torch.float32,
        device_map="auto" if DEVICE == "cuda" else None,
        trust_remote_code=True,
        local_files_only=True,
    )

    if DEVICE == "cpu":
        model = model.to(DEVICE)

    print(f"✓ Model loaded successfully on {DEVICE}")


# ============================================================
# FastAPI App
# ============================================================

app = FastAPI(title="Qwen2.5-3B-Instruct Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Data Models
# ============================================================

class Message(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[Message]
    temperature: float = TEMPERATURE
    max_tokens: int = MAX_NEW_TOKENS
    top_p: float = TOP_P


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[dict[str, Any]]
    usage: dict[str, int]


# ============================================================
# API Endpoints
# ============================================================


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "model": MODEL_NAME,
        "device": DEVICE,
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """OpenAI-compatible chat completion endpoint."""
    if tokenizer is None or model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    try:
        # Build prompt from messages (Qwen format)
        prompt = tokenizer.apply_chat_template(
            request.messages,
            tokenize=False,
            add_generation_prompt=True,
        )

        # Tokenize
        inputs = tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=4096,
        ).to(DEVICE)

        # Generate
        with torch.no_grad():
            outputs = model.generate(
                inputs.input_ids,
                max_new_tokens=request.max_tokens,
                temperature=request.temperature,
                top_p=request.top_p,
                do_sample=True if request.temperature > 0 else False,
                pad_token_id=tokenizer.eos_token_id,
            )

        # Decode response
        response_text = tokenizer.decode(
            outputs[0][inputs.input_ids.shape[1]:],
            skip_special_tokens=True,
        ).strip()

        # Calculate tokens
        input_tokens = inputs.input_ids.shape[1]
        output_tokens = outputs.shape[1] - input_tokens

        # Build response
        response = ChatCompletionResponse(
            id=f"chatcmpl-{int(time.time())}",
            created=int(time.time()),
            model=request.model,
            choices=[
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": response_text,
                    },
                    "finish_reason": "stop",
                }
            ],
            usage={
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        )

        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Lifecycle
# ============================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load model on startup."""
    load_model()
    yield
    # Cleanup if needed


app.router.lifespan_context = lifespan


# ============================================================
# Main
# ============================================================


def main():
    parser = argparse.ArgumentParser(description="Qwen2.5-3B-Instruct Local Server")
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind to",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind to",
    )
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"Qwen2.5-3B-Instruct Local Server")
    print(f"{'='*60}")
    print(f"Model: {MODEL_NAME}")
    print(f"Device: {DEVICE}")
    print(f"Host: {args.host}:{args.port}")
    print(f"{'='*60}\n")

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()