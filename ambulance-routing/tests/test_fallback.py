import json

from fallback import create_fallback


def test_read_fallback_speeds_missing_file_returns_empty(monkeypatch, tmp_path):
    missing_path = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(create_fallback.config, "FALLBACK_FILE", str(missing_path))
    assert create_fallback.read_fallback_speeds() == {}


def test_read_fallback_speeds_reads_existing_file(monkeypatch, tmp_path):
    path = tmp_path / "fallback_traffic.json"
    path.write_text(json.dumps({"A_B": 7.5, "B_C": 3.2}), encoding="utf-8")
    monkeypatch.setattr(create_fallback.config, "FALLBACK_FILE", str(path))

    speeds = create_fallback.read_fallback_speeds()
    assert speeds == {"A_B": 7.5, "B_C": 3.2}


def test_read_fallback_speeds_corrupt_file_returns_empty(monkeypatch, tmp_path):
    path = tmp_path / "fallback_traffic.json"
    path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(create_fallback.config, "FALLBACK_FILE", str(path))
    assert create_fallback.read_fallback_speeds() == {}


def test_save_fallback_snapshot_skips_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr(create_fallback.redis_client, "is_available", lambda client=None: False)
    assert create_fallback.save_fallback_snapshot() is False


def test_save_fallback_snapshot_writes_file(monkeypatch, tmp_path):
    path = tmp_path / "fallback_traffic.json"
    monkeypatch.setattr(create_fallback.config, "FALLBACK_FILE", str(path))
    monkeypatch.setattr(create_fallback.redis_client, "is_available", lambda client=None: True)
    monkeypatch.setattr(create_fallback.redis_client, "read_speeds", lambda client=None: {"A_B": 9.9})

    result = create_fallback.save_fallback_snapshot()
    assert result is True
    assert json.loads(path.read_text(encoding="utf-8")) == {"A_B": 9.9}