import json
import pathlib
import pytest

from datasette.app import Datasette
from datasette.cli import cli
from datasette.utils.sqlite import sqlite3
from .fixtures import TestClient as _TestClient
from click.testing import CliRunner

PLUGIN = """
from datasette import hookimpl

@hookimpl
def extra_template_vars():
    return {
        "from_plugin": "hooray"
    }
"""
METADATA = {"title": "This is from metadata"}
SETTINGS = {
    "default_cache_ttl": 60,
}
CSS = """
body { margin-top: 3em}
"""


@pytest.fixture(scope="session")
def config_dir_client(tmp_path_factory):
    config_dir = tmp_path_factory.mktemp("config-dir")

    plugins_dir = config_dir / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "hooray.py").write_text(PLUGIN, "utf-8")
    (plugins_dir / "non_py_file.txt").write_text(PLUGIN, "utf-8")
    (plugins_dir / ".mypy_cache").mkdir()

    templates_dir = config_dir / "templates"
    templates_dir.mkdir()
    (templates_dir / "row.html").write_text(
        "Show row here. Plugin says {{ from_plugin }}", "utf-8"
    )

    static_dir = config_dir / "static"
    static_dir.mkdir()
    (static_dir / "hello.css").write_text(CSS, "utf-8")

    (config_dir / "metadata.json").write_text(json.dumps(METADATA), "utf-8")
    (config_dir / "settings.json").write_text(json.dumps(SETTINGS), "utf-8")

    for dbname in ("demo.db", "immutable.db"):
        db = sqlite3.connect(str(config_dir / dbname))
        db.executescript(
            """
        CREATE TABLE cities (
            id integer primary key,
            name text
        );
        INSERT INTO cities (id, name) VALUES
            (1, 'San Francisco')
        ;
        """
        )

    # Mark "immutable.db" as immutable
    (config_dir / "inspect-data.json").write_text(
        json.dumps(
            {
                "immutable": {
                    "hash": "hash",
                    "size": 8192,
                    "file": "immutable.db",
                    "tables": {"cities": {"count": 1}},
                }
            }
        ),
        "utf-8",
    )

    ds = Datasette([], config_dir=config_dir)
    yield _TestClient(ds)


def test_metadata(config_dir_client):
    response = config_dir_client.get("/-/metadata.json")
    assert 200 == response.status
    assert METADATA == response.json


def test_settings(config_dir_client):
    response = config_dir_client.get("/-/settings.json")
    assert 200 == response.status
    assert 60 == response.json["default_cache_ttl"]


def test_error_on_config_json(tmp_path_factory):
    config_dir = tmp_path_factory.mktemp("config-dir")
    (config_dir / "config.json").write_text(json.dumps(SETTINGS), "utf-8")
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(cli, [str(config_dir), "--get", "/-/settings.json"])
    assert result.exit_code == 1
    assert "config.json should be renamed to settings.json" in result.stderr


def test_plugins(config_dir_client):
    response = config_dir_client.get("/-/plugins.json")
    assert 200 == response.status
    assert "hooray.py" in {p["name"] for p in response.json}
    assert "non_py_file.txt" not in {p["name"] for p in response.json}
    assert "mypy_cache" not in {p["name"] for p in response.json}


def test_templates_and_plugin(config_dir_client):
    response = config_dir_client.get("/demo/cities/1")
    assert 200 == response.status
    assert "Show row here. Plugin says hooray" == response.text


def test_static(config_dir_client):
    response = config_dir_client.get("/static/hello.css")
    assert 200 == response.status
    assert CSS == response.text
    assert "text/css" == response.headers["content-type"]


def test_static_directory_browsing_not_allowed(config_dir_client):
    response = config_dir_client.get("/static/")
    assert 403 == response.status
    assert "403: Directory listing is not allowed" == response.text


def test_databases(config_dir_client):
    response = config_dir_client.get("/-/databases.json")
    assert 200 == response.status
    databases = response.json
    assert 2 == len(databases)
    databases.sort(key=lambda d: d["name"])
    assert "demo" == databases[0]["name"]
    assert databases[0]["is_mutable"]
    assert "immutable" == databases[1]["name"]
    assert not databases[1]["is_mutable"]


@pytest.mark.parametrize("filename", ("metadata.yml", "metadata.yaml"))
def test_metadata_yaml(tmp_path_factory, filename):
    config_dir = tmp_path_factory.mktemp("yaml-config-dir")
    (config_dir / filename).write_text("title: Title from metadata", "utf-8")
    ds = Datasette([], config_dir=config_dir)
    client = _TestClient(ds)
    response = client.get("/-/metadata.json")
    assert 200 == response.status
    assert {"title": "Title from metadata"} == response.json


def test_store_config_dir(config_dir_client):
    ds = config_dir_client.ds

    assert hasattr(ds, "config_dir")
    assert ds.config_dir is not None
    assert isinstance(ds.config_dir, pathlib.Path)
