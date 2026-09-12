import os

from mysql_ai.errors import ToolError
from mysql_ai.models import ConnectionProfile

SERVICE = "mysql-ai-tools"


def backend():
    if os.name != "nt":
        raise ToolError(
            "CREDENTIAL_BACKEND", "首版凭据存储支持 Windows；其他平台可显式使用环境变量。"
        )
    try:
        from keyring.backends.Windows import WinVaultKeyring

        return WinVaultKeyring()
    except Exception as exc:
        raise ToolError(
            "CREDENTIAL_BACKEND", "Windows 凭据存储不可用；请以当前用户在本机配置。"
        ) from exc


def set_password(credential_id: str, password: str) -> None:
    try:
        backend().set_password(SERVICE, credential_id, password)
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError("CREDENTIAL_BACKEND", "无法保存到 Windows 凭据存储。") from exc


def password_for(profile: ConnectionProfile) -> str:
    try:
        value = (
            os.environ.get(profile.password_env)
            if profile.password_env
            else backend().get_password(SERVICE, profile.credential_id)
        )
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError("CREDENTIAL_BACKEND", "无法读取本机凭据。") from exc
    if value is None:
        raise ToolError("CREDENTIAL_MISSING", "缺少密码；请在本机配置凭据或所声明的环境变量。")
    return value


def check_storage() -> None:
    """Round-trip our own short-lived test record without enumerating credentials."""
    import secrets
    import uuid

    identifier = f"self-test-{uuid.uuid4().hex}"
    value = secrets.token_urlsafe(24)
    store = backend()
    stored = False
    try:
        store.set_password(SERVICE, identifier, value)
        stored = True
        if store.get_password(SERVICE, identifier) != value:
            raise ToolError("CREDENTIAL_BACKEND", "Windows 凭据读写验证失败。")
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError("CREDENTIAL_BACKEND", "Windows 凭据读写验证失败。") from exc
    finally:
        if stored:
            try:
                store.delete_password(SERVICE, identifier)
            except Exception as exc:
                raise ToolError("CREDENTIAL_BACKEND", "无法清理本工具生成的测试凭据。") from exc


def delete_password(credential_id: str) -> None:
    try:
        store = backend()
        if store.get_password(SERVICE, credential_id) is not None:
            store.delete_password(SERVICE, credential_id)
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError("CREDENTIAL_BACKEND", "无法清理本机凭据记录。") from exc
