# Build on Windows x64 with the locked project environment.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).parent
datas, binaries, hiddenimports = [], [], []
for package in ("mcp", "sqlglot", "keyring", "pymysql"):
    data, binary, hidden = collect_all(
        package,
        filter_submodules=lambda name: not name.startswith(("mcp.cli", "keyring.testing", "keyring.tests")),
        exclude_datas=["**/tests/**", "**/testing/**"],
    )
    datas += data
    binaries += binary
    hiddenimports += hidden
for distribution in ("mcp", "sqlglot", "PyMySQL", "pydantic", "keyring"):
    datas += copy_metadata(distribution, recursive=True)
hiddenimports += ["keyring.backends.Windows", "cryptography", "win32ctypes.pywin32.win32cred"]
a = Analysis([str(root / "packaging/entrypoint.py")],
             pathex=[str(root / "src")], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[],
             excludes=["pytest", "hypothesis", "ruff", "mcp.cli", "keyring.testing"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="mysql-ai",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="mysql-ai")
