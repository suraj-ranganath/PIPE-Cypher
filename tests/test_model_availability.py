from pipecypher.model_availability import (
    cache_dir_for_model,
    format_model_availability_markdown,
    local_model_cache_info,
)


def test_cache_dir_for_model_uses_hf_cache_naming(tmp_path):
    assert cache_dir_for_model("Qwen/Qwen3.5-9B", tmp_path).name == "models--Qwen--Qwen3.5-9B"


def test_local_model_cache_info_detects_snapshots(tmp_path):
    model_dir = tmp_path / "models--Qwen--Qwen3.5-9B"
    (model_dir / "snapshots" / "abc").mkdir(parents=True)
    (model_dir / "refs").mkdir()
    (model_dir / "refs" / "main").write_text("abc", encoding="utf-8")

    info = local_model_cache_info("Qwen/Qwen3.5-9B", tmp_path)

    assert info["cached"] is True
    assert info["snapshots"] == ["abc"]
    assert info["refs"] == ["refs/main"]


def test_format_model_availability_markdown_handles_remote_missing():
    text = format_model_availability_markdown(
        [
            {
                "model": "Qwen/Qwen3.5-35B-A3B",
                "cached": False,
                "snapshots": [],
                "remote": {"remote_exists": False},
            }
        ]
    )
    assert "Qwen/Qwen3.5-35B-A3B" in text
    assert "| Qwen/Qwen3.5-35B-A3B | no | 0 | no |" in text
