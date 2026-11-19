from karaoke import config


def test_data_dir_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("KARAOKE_DATA_DIR", str(tmp_path))
    assert config.data_dir() == tmp_path
    assert config.library_dir() == tmp_path / "library"
    assert config.models_dir() == tmp_path / "models"


def test_default_data_dir(monkeypatch):
    monkeypatch.delenv("KARAOKE_DATA_DIR", raising=False)
    assert config.data_dir() == config.REPO_ROOT / "data"
