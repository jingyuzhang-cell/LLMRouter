"""Collection clients. Both speak OpenAI-compatible streaming so TTFT/decode/total
and server-side token usage are captured uniformly.

Local: vLLM server (managed by runner.py), model name = served-model-name.
API:   DashScope compatible-mode, deepseek-r1-distill-qwen-14b (reasoning model:
       reasoning_content streamed separately when present).
"""
import os
import re
import threading
import time

from openai import OpenAI

MAX_TOKENS = {"math": 4096, "code": 2048, "knowledge": 2048, "general": 4096}
THINK_RE = re.compile(r"<think>(.*?)</think>", re.S)


def split_thinking(text):
    m = THINK_RE.search(text)
    if m:
        return THINK_RE.sub("", text, count=1).strip(), m.group(1).strip()
    return text.strip(), None


def generate(client, model, row, max_retries=3):
    """One streamed generation. Returns a response-slot dict (protocol v1.1 fields)."""
    last_err = None
    for attempt in range(max_retries):
        try:
            t0 = time.perf_counter()
            ttft = None
            content, reasoning = [], []
            usage = {}
            fr = None
            stream = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": row["query"]}],
                temperature=0.0, top_p=1.0,
                max_tokens=MAX_TOKENS[row["task_type"]],
                stream=True, stream_options={"include_usage": True},
            )
            for chunk in stream:
                if not chunk.choices:
                    if getattr(chunk, "usage", None):
                        usage = chunk.usage.model_dump()
                    continue
                delta = chunk.choices[0].delta
                piece = getattr(delta, "reasoning_content", None) or ""
                if piece:
                    if ttft is None:
                        ttft = time.perf_counter() - t0
                    reasoning.append(piece)
                piece = getattr(delta, "content", None) or ""
                if piece:
                    if ttft is None:
                        ttft = time.perf_counter() - t0
                    content.append(piece)
                if chunk.choices[0].finish_reason:
                    fr = chunk.choices[0].finish_reason
            total = time.perf_counter() - t0
            text = "".join(content)
            think = "".join(reasoning) or None
            if think is None and text.startswith("<think>"):
                text, think = split_thinking(text)
            out_tok = usage.get("completion_tokens")
            estimated = out_tok is None or usage.get("prompt_tokens") is None
            if out_tok is None:
                out_tok = len(text + (think or "")) // 3
            in_tok = usage.get("prompt_tokens")
            dec = total - (ttft or 0)
            return dict(
                answer=text if text else None,
                thinking=think,
                cost=dict(tokens_input=in_tok, tokens_output=out_tok,
                          tokens_estimated=estimated),
                latency=dict(total_ms=round(total * 1000, 1),
                             ttft_ms=round((ttft or total) * 1000, 1),
                             decode_ms=round(dec * 1000, 1),
                             tokens_per_second=round(out_tok / dec, 1) if dec > 0 else None),
                finish_reason=fr, requested_max_tokens=MAX_TOKENS[row["task_type"]],
                status="ok" if (fr == "stop" and text) else ("truncated" if fr == "length" else "failed"),
            )
        except Exception as e:  # noqa: BLE001 - retry any transport/API error
            last_err = e
            time.sleep(2 * (attempt + 1))
    return dict(answer=None, thinking=None, cost=dict(tokens_input=None, tokens_output=None,
                tokens_estimated=True),
                latency=dict(total_ms=None, ttft_ms=None, decode_ms=None, tokens_per_second=None),
                status="failed", error=str(last_err))


def make_local_client(port=8100):
    return OpenAI(base_url=f"http://127.0.0.1:{port}/v1", api_key="local")


def make_dashscope_client():
    return OpenAI(base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                 api_key=os.environ["QWEN_API_KEY"], timeout=600)


def collect_parallel(client, model, rows, worker_fn=None, n_threads=6, on_done=None):
    """Threaded collection preserving row order; on_done(slot_dict, row) per completion."""
    results = [None] * len(rows)
    lock = threading.Lock()
    idx_q = list(range(len(rows)))

    def work():
        while True:
            with lock:
                if not idx_q:
                    return
                i = idx_q.pop(0)
            slot = generate(client, model, rows[i])
            results[i] = slot
            if on_done:
                on_done(slot, rows[i])

    errors = []
    def guarded_work():
        try:
            work()
        except Exception as exc:
            with lock:
                errors.append(exc)
    threads = [threading.Thread(target=guarded_work) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        raise RuntimeError("Collection worker failed; raw completed rows are preserved") from errors[0]
    return results
