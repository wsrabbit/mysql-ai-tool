class ToolError(Exception):
    """Only these deliberately sanitized messages may reach clients."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def payload(self) -> dict:
        return {"ok": False, "error": {"code": self.code, "message": self.message}}
