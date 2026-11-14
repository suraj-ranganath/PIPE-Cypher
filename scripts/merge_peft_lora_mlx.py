#!/usr/bin/env python3
"""Merge a PEFT LoRA adapter into its base model's weights with MLX (BF16, no quantization).

W' = W + (lora_alpha / r) * B @ A for every adapted linear layer. The merged
model is written as safetensors shards next to copies of the base model's
config and tokenizer files, so ``mlx_lm.server --model OUT`` can serve it.
This reproduces what vLLM's LoRA serving computes (base + adapter at released
precision), on a Mac without a GPU.

Example:
  python scripts/merge_peft_lora_mlx.py --base ~/.cache/huggingface/hub/models--google--gemma-2-9b-it/snapshots/<rev> \
      --adapter ~/.cache/huggingface/hub/models--neo4j--text2cypher-gemma-2-9b-it-finetuned-2024v1/snapshots/<rev> \
      --out ~/pipecypher-models/neo4j-text2cypher-gemma-2-9b-2024v1-merged
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import mlx.core as mx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    base = Path(args.base).expanduser()
    adapter = Path(args.adapter).expanduser()
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)

    config = json.loads((adapter / "adapter_config.json").read_text())
    if config.get("use_dora") or config.get("use_rslora"):
        raise SystemExit("DoRA/rsLoRA adapters are not supported by this merge")
    scale = float(config["lora_alpha"]) / float(config["r"])
    lora = mx.load(str(adapter / "adapter_model.safetensors"))
    pairs: dict[str, dict[str, mx.array]] = {}
    for key, value in lora.items():
        # base_model.model.model.layers.0.self_attn.q_proj.lora_A.weight -> model.layers.0.self_attn.q_proj.weight
        stem = key.replace("base_model.model.", "", 1)
        for part in ("lora_A", "lora_B"):
            marker = f".{part}.weight"
            if stem.endswith(marker):
                target = stem[: -len(marker)] + ".weight"
                pairs.setdefault(target, {})[part] = value
    merged_count = 0
    for shard in sorted(base.glob("*.safetensors")):
        weights = mx.load(str(shard))
        for name in list(weights):
            if name in pairs:
                a = pairs[name]["lora_A"].astype(mx.float32)
                b = pairs[name]["lora_B"].astype(mx.float32)
                w = weights[name]
                weights[name] = (w.astype(mx.float32) + scale * (b @ a)).astype(w.dtype)
                merged_count += 1
        mx.save_safetensors(str(out / shard.name), weights, metadata={"format": "pt"})
        del weights
    if merged_count != len(pairs):
        raise SystemExit(f"merged {merged_count} of {len(pairs)} adapted tensors; key mismatch")
    for item in base.iterdir():
        if item.suffix != ".safetensors" and item.is_file():
            shutil.copy(item, out / item.name)
    (out / "MERGE_INFO.json").write_text(json.dumps({
        "base": str(base), "adapter": str(adapter), "scale": scale, "merged_tensors": merged_count,
        "dtype": "base dtype preserved (no quantization)",
    }, indent=2))
    print(f"merged {merged_count} tensors (scale {scale}) -> {out}")


if __name__ == "__main__":
    main()
