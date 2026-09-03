import base64
import json
from typing import Any, List, Optional
import urllib.error
import urllib.request


class GridcoinRPC:
    """Client for communicating with a Gridcoin node via JSON-RPC using standard library."""

    def __init__(self, host: str, port: int, user: str, password: str, timeout: int = 5):
        self.url = f"http://{host}:{port}"
        creds = f"{user}:{password}".encode("utf-8")
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {base64.b64encode(creds).decode('ascii')}",
        }
        self.timeout = timeout

    def call(self, method: str, params: Optional[List[Any]] = None) -> Any:
        """Execute a JSON-RPC method call on the Gridcoin node."""
        payload = {
            "jsonrpc": "1.0",
            "id": "grc-rpc",
            "method": method,
            "params": params if params is not None else [],
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.url, data=data, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result_data = json.loads(resp.read().decode("utf-8"))
                if result_data.get("error"):
                    raise RuntimeError(f"RPC Error ({method}): {result_data['error']}")
                return result_data.get("result")
        except (urllib.error.URLError, OSError, ValueError) as err:
            raise ConnectionError(f"Gridcoin RPC connection error ({method}): {err}") from err
