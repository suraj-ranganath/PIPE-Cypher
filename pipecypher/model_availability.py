from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests


def cache_dir_for_model(model: str, cache_root: str | Path) -> Path:
    return Path(cache_root).expanduser() / ("models--" + model.replace("/", "--"))


def local_model_cache_info(model: str, cache_root: str | Path) -> dict[str, Any]:
    model_dir = cache_dir_for_model(model, cache_root)
    refs = sorted(str(path.relative_to(model_dir)) for path in model_dir.glob("refs/*")) if model_dir.exists() else []
    snapshots = (
        sorted(path.name for path in (model_dir / "snapshots").iterdir() if path.is_dir())
        if (model_dir / "snapshots").exists()
        else []
    )
    return {
        "model": model,
        "cache_dir": str(model_dir),
        "cached": model_dir.exists(),
        "refs": refs,
        "snapshots": snapshots,
    }


def huggingface_model_info(model: str, *, timeout_sec: int = 20) -> dict[str, Any]:
    url = f"https://huggingface.co/api/models/{model}"
    response = requests.get(url, timeout=timeout_sec)
    if response.status_code == 404:
        return {"model": model, "remote_exists": False, "status_code": 404, "url": url}
    response.raise_for_status()
    payload = response.json()
    siblings = payload.get("siblings") or []
    file_names = [item.get("rfilename", "") for item in siblings if item.get("rfilename")]
    return {
        "model": model,
        "remote_exists": True,
        "status_code": response.status_code,
        "url": url,
        "private": bool(payload.get("private", False)),
        "gated": payload.get("gated", False),
        "sha": payload.get("sha"),
        "last_modified": payload.get("lastModified"),
        "file_count": len(file_names),
        "safetensor_count": sum(1 for name in file_names if name.endswith(".safetensors")),
    }


def check_models(
    models: list[str],
    *,
    cache_root: str | Path,
    check_remote: bool = False,
    timeout_sec: int = 20,
) -> list[dict[str, Any]]:
    results = []
    for model in models:
        row = local_model_cache_info(model, cache_root)
        if check_remote:
            try:
                row["remote"] = huggingface_model_info(model, timeout_sec=timeout_sec)
            except Exception as exc:
                row["remote"] = {"model": model, "remote_error": str(exc)}
        results.append(row)
    return results


def format_model_availability_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| Model | Cached | Snapshots | Remote | Gated/private | Safetensors |",
        "|---|---:|---:|---|---|---:|",
    ]
    for row in rows:
        remote = row.get("remote", {})
        if "remote_error" in remote:
            remote_status = "error"
            gated = remote["remote_error"]
            safetensors = ""
        elif remote:
            remote_status = "yes" if remote.get("remote_exists") else "no"
            gated = str(remote.get("gated") or remote.get("private") or "")
            safetensors = str(remote.get("safetensor_count", ""))
        else:
            remote_status = "not checked"
            gated = ""
            safetensors = ""
        lines.append(
            "| {model} | {cached} | {snapshots} | {remote_status} | {gated} | {safetensors} |".format(
                model=row["model"],
                cached="yes" if row["cached"] else "no",
                snapshots=len(row.get("snapshots", [])),
                remote_status=remote_status,
                gated=gated,
                safetensors=safetensors,
            )
        )
    return "\n".join(lines)


def format_model_availability_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, indent=2, sort_keys=True)
