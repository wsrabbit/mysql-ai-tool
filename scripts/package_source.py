"""Create a source archive using an explicit allowlist (no configs, caches or credentials)."""

import zipfile
from pathlib import Path

from mysql_ai import __version__

root = Path(__file__).resolve().parents[1]
output = root / "outputs"
output.mkdir(exist_ok=True)
archive = output / f"mysql-ai-tools-{__version__}-source.zip"
files = [
    root / name
    for name in (
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        ".gitignore",
        "README.md",
        "INSTALL.md",
        "CHANGELOG.md",
    )
]
for name in ("src", "tests", "scripts", "packaging", "plugins", "docs", "examples"):
    files.extend(
        p
        for p in (root / name).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    )
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
    for path in sorted(files):
        bundle.write(path, path.relative_to(root))
print(archive)
