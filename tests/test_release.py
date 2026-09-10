import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_release.py"
spec = importlib.util.spec_from_file_location("check_release", SCRIPT)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_release_rejects_wrong_tag():
    version = release.validate_versions(release.ROOT)
    assert release.validate_versions(release.ROOT, f"v{version}") == version
    with pytest.raises(ValueError, match="Tag must"):
        release.validate_versions(release.ROOT, "v99.0.0")


def test_release_rejects_version_drift(tmp_path):
    for name in (
        "pyproject.toml",
        "uv.lock",
        "CHANGELOG.md",
        "src/mysql_ai/__init__.py",
        "plugins/mysql-ai-tools/.codex-plugin/plugin.json",
    ):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(release.ROOT / name, target)
    plugin = tmp_path / "plugins/mysql-ai-tools/.codex-plugin/plugin.json"
    data = json.loads(plugin.read_text(encoding="utf-8"))
    data["version"] = "99.0.0"
    plugin.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="versions must match"):
        release.validate_versions(tmp_path)


def test_release_requires_complete_untampered_archives(tmp_path):
    version = "1.2.3"
    archives = []
    for kind in ("source", "windows-x64"):
        path = tmp_path / f"mysql-ai-tools-{version}-{kind}.zip"
        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr("LICENSE", "fixture")
            if kind == "windows-x64":
                bundle.writestr(
                    "release.json",
                    json.dumps(
                        {
                            "version": version,
                            "files": [
                                {
                                    "path": "LICENSE",
                                    "sha256": hashlib.sha256(b"fixture").hexdigest(),
                                }
                            ],
                        }
                    ),
                )
        path.with_suffix(".zip.sha256").write_text(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n", encoding="ascii"
        )
        archives.append(path)
    release.verify_artifacts(tmp_path, version)
    archives[0].write_bytes(b"tampered")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        release.verify_artifacts(tmp_path, version)
    archives[0].unlink()
    with pytest.raises(ValueError, match="exactly four"):
        release.verify_artifacts(tmp_path, version)
