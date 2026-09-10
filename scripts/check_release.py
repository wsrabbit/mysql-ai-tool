"""Validate versions, release tags and archives without installing project dependencies."""

import argparse
import ast
import hashlib
import json
import os
import re
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate_versions(root: Path, tag: str | None = None) -> str:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Release version must be X.Y.Z")
    tree = ast.parse((root / "src/mysql_ai/__init__.py").read_text(encoding="utf-8"))
    module_version = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)
    )
    plugin = json.loads(
        (root / "plugins/mysql-ai-tools/.codex-plugin/plugin.json").read_text(encoding="utf-8-sig")
    )
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    locked_version = next(p["version"] for p in lock["package"] if p["name"] == "mysql-ai-tools")
    if {module_version, plugin["version"], locked_version} != {version}:
        raise ValueError("pyproject, Python module, plugin and lock versions must match")
    if tag is not None and tag != f"v{version}":
        raise ValueError(f"Tag must be v{version}, got {tag}")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"^## {re.escape(version)}\s*$", changelog, re.MULTILINE):
        raise ValueError("Missing changelog section")
    return version


def verify_artifacts(directory: Path, version: str) -> None:
    stems = [f"mysql-ai-tools-{version}-{kind}" for kind in ("windows-x64", "source")]
    expected = {f"{stem}{suffix}" for stem in stems for suffix in (".zip", ".zip.sha256")}
    actual = {p.name for p in directory.iterdir() if p.suffix in (".zip", ".sha256")}
    if actual != expected:
        raise ValueError(f"Expected exactly four release files: {sorted(expected)}")
    for stem in stems:
        archive = directory / f"{stem}.zip"
        expected_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        checksum = archive.with_suffix(".zip.sha256").read_text(encoding="ascii").split()
        if checksum != [expected_digest, archive.name]:
            raise ValueError(f"Checksum mismatch: {archive.name}")
        with zipfile.ZipFile(archive) as bundle:
            if bundle.testzip() is not None:
                raise ValueError(f"Invalid ZIP: {archive.name}")
            if "LICENSE" not in bundle.namelist():
                raise ValueError(f"License missing: {archive.name}")
            if stem.endswith("windows-x64"):
                manifest = json.loads(bundle.read("release.json"))
                if manifest["version"] != version:
                    raise ValueError("Bundled version mismatch")
                for item in manifest["files"]:
                    if hashlib.sha256(bundle.read(item["path"])).hexdigest() != item["sha256"]:
                        raise ValueError(f"Bundled file checksum mismatch: {item['path']}")


def release_notes(root: Path, version: str) -> str:
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    section = re.split(rf"^## {re.escape(version)}\s*$", changelog, flags=re.MULTILINE)[1]
    section = re.split(r"^## ", section, maxsplit=1, flags=re.MULTILINE)[0].strip()
    base = f"https://github.com/wsrabbit/mysql-ai-tool/releases/download/v{version}"
    stem = f"mysql-ai-tools-{version}"
    return f"""## 下载与安装

- [Windows x64 安装包]({base}/{stem}-windows-x64.zip)：包含 Python 运行时，无需另装 Python。
- [Windows SHA-256]({base}/{stem}-windows-x64.zip.sha256)
- [源码包]({base}/{stem}-source.zip) · [源码 SHA-256]({base}/{stem}-source.zip.sha256)

完整解压 Windows ZIP，保留 app/_internal，在解压目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\\install.ps1
```

[配置数据库与升级说明](https://github.com/wsrabbit/mysql-ai-tool/blob/v{version}/INSTALL.md)

## 本次更新

{section}

## 自动验证与适用范围

发布前必须通过 Windows Python 3.12/3.13 单元与协议测试、Linux 上的 MySQL 8.0/8.4
集成测试，以及 Windows 冻结程序握手、凭据自检、隔离安装和卸载验证。
发布流程核对全部附件 SHA-256。具体记录见本版本标签对应的 Release 工作流。

提供 7 个只读工具，不支持数据写入、DDL、CTE、UNION 或窗口函数。
Windows x64 是当前二进制发布目标。自动测试不代表已对接你的业务库；
请在本机配置专用只读账号并新建 Codex 会话。安装包暂未进行代码签名。

已有旧版用户请解压新版后运行新版 install.ps1；不要覆盖旧版程序目录。
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag")
    parser.add_argument("--notes", type=Path)
    parser.add_argument("--artifacts", type=Path)
    args = parser.parse_args()
    tag = args.tag
    if tag is None and os.environ.get("GITHUB_REF_TYPE") == "tag":
        tag = os.environ["GITHUB_REF_NAME"]
    version = validate_versions(ROOT, tag)
    if args.artifacts:
        verify_artifacts(args.artifacts, version)
    if args.notes:
        args.notes.parent.mkdir(parents=True, exist_ok=True)
        args.notes.write_text(release_notes(ROOT, version), encoding="utf-8")
    print(f"Release metadata verified: {version}")


if __name__ == "__main__":
    main()
