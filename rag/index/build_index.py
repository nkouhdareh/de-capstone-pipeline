"""Phase 3: embed every chunk into a versioned, resumable index.

Measured before this was written (2026-09-24, i5-1334U, no GPU): 7.2 chunks per
second at full precision, so all 360,916 chunks take about 14 hours. Everything
below follows from that number:

- It resumes. Vectors are saved in shards of 10,000 chunks the moment each one
  is done, so a crash, a reboot or a closed lid costs one shard, not the night.
  Running the same command again carries on where it stopped.
- It refuses to mix. A half-built index remembers how it was started, and a
  re-run with a different model, precision or chunk file stops rather than
  resuming into a mismatched index.
- It sorts chunks by length, so every batch needs little padding: about 20%
  faster for nothing. The order is saved beside the vectors, so nothing else
  depends on it.
- It keeps Windows awake while it runs, and only while it runs. That covers
  sleeping from idleness; closing the lid still follows the lid setting.

Output, in data/rag/index/<name>/:
  vectors.npy     float32, one L2-normalised row per chunk
  chunk_ids.txt   the chunk id of each row, in the same order
  manifest.json   what produced it: model, precision, prefixes, header version,
                  chunk-file hash, library versions, git commit, timings

Usage:
  python -m rag.index.build_index --limit 500     # smoke test, about 2 minutes
  python -m rag.index.build_index                 # the full build, about 14 hours
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np

from rag.corpus.chunker import token_counter
from rag.index.embedding_text import (
    HEADER_VERSION,
    MODEL_ID,
    QUERY_PREFIX,
    TOKEN_LIMIT,
    passage_text,
)

RAGDATA = Path("D:/capstone/data/rag")
CHUNKS = RAGDATA / "chunks.parquet"
MODELS = RAGDATA / "models"        # a fixed home for model files, not the Temp folder
INDEXES = RAGDATA / "index"

DIM = 384
SHARD = 10_000
BATCH = 64         # the RAM dial: chunks through the model at once
THREADS = 8        # 8, 10 and 12 all measured 7.1 to 7.2 per second; 8 leaves the laptop usable
MODEL_FILES = {"fp32": "onnx/model.onnx", "int8": "onnx/model_int8.onnx"}


def keep_awake() -> None:
    """Ask Windows not to sleep from idleness while this process runs. The request
    ends with the process, and no power setting is changed."""
    if sys.platform == "win32":
        es_continuous, es_system_required = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | es_system_required)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git_commit() -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              check=True).stdout.strip()
    try:
        return git("rev-parse", "--short", "HEAD") + ("-dirty" if git("status", "--porcelain") else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def load_model(precision: str, threads: int):
    from fastembed import TextEmbedding

    name = MODEL_ID
    if precision != "fp32":
        from fastembed.common.model_description import ModelSource, PoolingType
        name = f"arctic-embed-s/{precision}"
        if name not in {m["model"] for m in TextEmbedding.list_supported_models()}:
            TextEmbedding.add_custom_model(
                model=name, pooling=PoolingType.CLS, normalization=True, dim=DIM,
                sources=ModelSource(hf="Snowflake/snowflake-arctic-embed-s"),
                model_file=MODEL_FILES[precision])
    return TextEmbedding(name, cache_dir=str(MODELS), threads=threads)


def load_chunks(limit: int) -> tuple[list[str], list[int], list[str]]:
    """Every chunk, shortest first. With --limit, an even spread across all
    lengths rather than the shortest few, so a smoke test's speed is honest."""
    rows = duckdb.execute(f"""
        SELECT chunk_id, n_tokens, text, generic_name, brand_name, section
        FROM '{CHUNKS.as_posix()}'
        ORDER BY n_tokens, chunk_id
    """).fetchall()
    if limit:
        rows = rows[::max(1, len(rows) // limit)][:limit]
    count = token_counter()
    ids = [row[0] for row in rows]
    tokens = [row[1] for row in rows]
    texts = [passage_text(text, generic, brand, section, count)
             for _, _, text, generic, brand, section in rows]
    return ids, tokens, texts


def build(name: str, precision: str, threads: int, limit: int, out_root: Path) -> Path:
    out = out_root / name
    shards = out / "shards"
    shards.mkdir(parents=True, exist_ok=True)

    started = time.time()
    print("reading chunks and preparing what the model will read ...", flush=True)
    ids, tokens, texts = load_chunks(limit)
    print(f"  {len(ids):,} chunks ready in {time.time() - started:.0f}s", flush=True)

    plan = {
        "model": MODEL_ID, "precision": precision, "model_file": MODEL_FILES[precision],
        "dim": DIM, "normalized": True,
        "query_prefix": QUERY_PREFIX, "passage_prefix": "",
        "header": HEADER_VERSION, "token_limit": TOKEN_LIMIT,
        "chunks_file": CHUNKS.as_posix(), "chunks_sha256": sha256(CHUNKS),
        "n_chunks": len(ids), "limit": limit, "shard_size": SHARD,
        "order": "n_tokens, chunk_id",
    }
    plan_file = out / "plan.json"
    if plan_file.exists():
        if json.loads(plan_file.read_text(encoding="utf-8")) != plan:
            raise SystemExit(f"{out} was started with different settings. "
                             "Delete that folder, or pass another --name.")
        print("  resuming a build started earlier", flush=True)
    else:
        plan_file.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    keep_awake()
    model = load_model(precision, threads)
    timings_file = shards / "timings.json"
    timings = json.loads(timings_file.read_text(encoding="utf-8")) if timings_file.exists() else {}

    n_shards = -(-len(ids) // SHARD)
    all_tokens = sum(tokens)
    for s in range(n_shards):
        path = shards / f"shard-{s:04d}.npy"
        if path.exists():
            continue
        lo, hi = s * SHARD, min((s + 1) * SHARD, len(ids))
        began = time.time()
        vectors = np.asarray(list(model.embed(texts[lo:hi], batch_size=BATCH)), dtype=np.float32)
        if vectors.shape != (hi - lo, DIM):
            raise SystemExit(f"shard {s}: got {vectors.shape}, expected {(hi - lo, DIM)}")
        tmp = shards / f"shard-{s:04d}.tmp.npy"
        np.save(tmp, vectors)
        os.replace(tmp, path)           # a shard file exists only once it is complete
        timings[str(s)] = {"seconds": round(time.time() - began, 1), "chunks": hi - lo,
                           "tokens": sum(tokens[lo:hi])}
        timings_file.write_text(json.dumps(timings, indent=1), encoding="utf-8")
        # Shortest chunks come first, so a rate per token predicts the rest far
        # better than a rate per chunk.
        done_tokens = sum(t["tokens"] for t in timings.values())
        per_token = sum(t["seconds"] for t in timings.values()) / done_tokens
        hours_left = (all_tokens - done_tokens) * per_token / 3600
        print(f"shard {s + 1:>3}/{n_shards}  {hi - lo:>6,} chunks in {timings[str(s)]['seconds']:>6.0f}s"
              f"  |  about {hours_left:.1f} h left", flush=True)

    vectors = np.concatenate([np.load(shards / f"shard-{s:04d}.npy") for s in range(n_shards)])
    np.save(out / "vectors.npy", vectors)
    (out / "chunk_ids.txt").write_text("\n".join(ids) + "\n", encoding="utf-8")

    import fastembed
    import onnxruntime
    embed_seconds = sum(t["seconds"] for t in timings.values())
    manifest = {
        "index": name, **plan, "n_vectors": int(vectors.shape[0]),
        "threads": threads, "batch_size": BATCH,
        "embed_seconds": round(embed_seconds),
        "chunks_per_second": round(len(ids) / embed_seconds, 2),
        "fastembed": fastembed.__version__, "onnxruntime": onnxruntime.__version__,
        "git_commit": git_commit(),
        "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\n{len(ids):,} vectors written to {out}")
    print(f"embedding took {embed_seconds / 3600:.2f} h at {manifest['chunks_per_second']} chunks per second")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed every chunk into a versioned index.")
    parser.add_argument("--precision", choices=sorted(MODEL_FILES), default="fp32")
    parser.add_argument("--threads", type=int, default=THREADS)
    parser.add_argument("--limit", type=int, default=0,
                        help="embed only this many chunks, spread across all lengths: a smoke test")
    parser.add_argument("--name", help="index folder; default arctic-s-<precision>, plus -smoke with --limit")
    parser.add_argument("--out", type=Path, default=INDEXES, help="parent folder for index folders")
    args = parser.parse_args()
    name = args.name or f"arctic-s-{args.precision}" + ("-smoke" if args.limit else "")
    build(name, args.precision, args.threads, args.limit, args.out)


if __name__ == "__main__":
    main()
