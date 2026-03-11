import requests  # type: ignore[import-untyped]
import urllib3

urllib3.disable_warnings()

# Reuse connections to the same host to avoid connection pool exhaustion (urllib3).
_DEFAULT_POOL_MAXSIZE = 20


class ILOClient:
    """
    Redfish-based iLO4/iLO5/iLO6 client.
    Uses basic auth over HTTPS (LAN-only; uses CA bundle for SSL verification).
    Reuses a requests.Session per instance so multiple _get() calls share connections.
    """

    def __init__(self, host: str, username: str, password: str, ca_bundle: str = None):
        self.base = f"https://{host}"
        self.auth = (username, password)
        self.ca_bundle = ca_bundle or self._get_default_ca_bundle()
        self._session = requests.Session()
        self._session.auth = self.auth
        self._session.verify = self.ca_bundle if self.ca_bundle else True
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=2, pool_maxsize=_DEFAULT_POOL_MAXSIZE
        )
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def _get_default_ca_bundle(self) -> str | None:
        """Returns path to system CA bundle or None to use default."""
        return None  # Use requests' default CA bundle

    def _get(self, path: str) -> dict:
        try:
            r = self._session.get(f"{self.base}{path}", timeout=10)
            r.raise_for_status()
            return r.json()
        except requests.ConnectionError as exc:
            raise ConnectionError(f"Cannot reach iLO at {self.base}: {exc}") from exc
        except requests.HTTPError:
            raise ConnectionError(f"iLO returned {r.status_code} for {path}") from None
        except ValueError as exc:
            raise ConnectionError(f"iLO returned invalid JSON for {path}") from exc

    def poll(self) -> dict:
        try:
            thermal = self._get("/redfish/v1/Chassis/1/Thermal")
            power = self._get("/redfish/v1/Chassis/1/Power")
            return {
                "cpu_temp": thermal["Temperatures"][0]["ReadingCelsius"],
                "fan_rpm": thermal["Fans"][0]["Reading"],
                "psu1_load_w": power["PowerControl"][0]["PowerConsumedWatts"],
                "health": thermal["Status"]["Health"],
            }
        except Exception as e:
            return {"error": str(e)}

    def get_status(self, data: dict) -> str:
        health = data.get("health", "")
        if health == "Critical":
            return "critical"
        if health == "Warning":
            return "degraded"
        if "error" in data:
            return "unknown"
        return "healthy"
