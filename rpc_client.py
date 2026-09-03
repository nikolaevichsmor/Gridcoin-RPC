import json
from typing import Any, List, Optional
import requests
from requests.auth import HTTPBasicAuth


class GridcoinRPC:
    """Client for communicating with a Gridcoin node via JSON-RPC."""

    def __init__(self, host: str, port: int, user: str, password: str, timeout: int = 5):
        self.url = f"http://{host}:{port}"
        self.auth = HTTPBasicAuth(user, password)
        self.headers = {"Content-Type": "application/json"}
        self.timeout = timeout
        self.session = requests.Session()

    def call(self, method: str, params: Optional[List[Any]] = None) -> Any:
        """Execute a JSON-RPC method call on the Gridcoin node."""
        payload = {
            "jsonrpc": "1.0",
            "id": "grc-rpc",
            "method": method,
            "params": params if params is not None else [],
        }
        try:
            response = self.session.post(
                self.url,
                data=json.dumps(payload),
                headers=self.headers,
                auth=self.auth,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("error"):
                raise RuntimeError(f"RPC Error ({method}): {data['error']}")
            return data.get("result")
        except (requests.exceptions.RequestException, ValueError) as err:
            raise ConnectionError(f"Gridcoin RPC connection error ({method}): {err}") from err
