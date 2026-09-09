"""Build and smoke-test an onedir archive using the current locked Python environment."""

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path

from mysql_ai import __version__

ROOT = Path(__file__).resolve().parents[1]


def run(*args, env=None):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, env=env, check=True)


def main():
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise SystemExit("This release target is Windows x64.")
    work = ROOT / "work" / f"build-{time.time_ns()}"
    output = ROOT / "outputs"
    work.mkdir(parents=True)
    output.mkdir(exist_ok=True)
    # Keep PyInstaller's cache inside the workspace as well.
    env = dict(
        os.environ,
        PYINSTALLER_CONFIG_DIR=str(work / "pyinstaller-cache"),
        MYSQL_AI_HOME=str(work / "smoke-config"),
        PYTHONUTF8="1",
    )
    run(
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--distpath",
        work / "dist",
        "--workpath",
        work / "intermediate",
        ROOT / "packaging/mysql-ai.spec",
        env=env,
    )
    app = work / "dist/mysql-ai"
    run(app / "mysql-ai.exe", "doctor", "--credential-check", env=env)
    run(
        sys.executable, ROOT / "scripts/smoke_mcp.py", "--executable", app / "mysql-ai.exe", env=env
    )
    release = work / f"mysql-ai-tools-{__version__}-windows-x64"
    release.mkdir()
    shutil.copytree(app, release / "app")
    shutil.copytree(ROOT / "plugins", release / "plugins")
    for name in ("install.ps1", "uninstall.ps1"):
        shutil.copy2(ROOT / "packaging/windows" / name, release / name)
    for name in ("README.md", "INSTALL.md", "CHANGELOG.md", "uv.lock"):
        shutil.copy2(ROOT / name, release / name)
    shutil.copytree(ROOT / "docs", release / "docs")
    shutil.copytree(ROOT / "examples", release / "examples")
    # Resolve plugin launch path at installation; the raw plugin defaults to the CLI on PATH.
    files = [
        {
            "path": path.relative_to(release).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(release.rglob("*"))
        if path.is_file()
    ]
    manifest = {
        "version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "files": files,
        "dependencies": {dist.metadata["Name"]: dist.version for dist in metadata.distributions()},
    }
    (release / "release.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    archive = Path(shutil.make_archive(str(output / release.name), "zip", release))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(
        json.dumps(
            {"archive": str(archive), "release_directory": str(release), "sha256": digest}, indent=2
        )
    )


if __name__ == "__main__":
    main()
