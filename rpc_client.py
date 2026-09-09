import base64
import json
import urllib.error
import urllib.request
from typing import Any, List, Optional


class GridcoinRPC:
    """Client for communicating with a Gridcoin node via JSON-RPC using standard library."""

    def __init__(self, host: str, port: int, user: str, password: str, timeout: int = 5):
        formatted_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        self.url = f"http://{formatted_host}:{port}"
        self.user = user
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
        except urllib.error.HTTPError as err:
            if err.code == 401:
                raise PermissionError(
                    f"Gridcoin RPC authentication failed (401 Unauthorized) for user '{self.user}'"
                ) from err
            raise ConnectionError(
                f"Gridcoin RPC HTTP error {err.code} ({method}): {err.reason}"
            ) from err
        except (urllib.error.URLError, OSError, ValueError) as err:
            raise ConnectionError(f"Gridcoin RPC connection error ({method}): {err}") from err
