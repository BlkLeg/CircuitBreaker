
import requests
import urllib3

urllib3.disable_warnings()


class ILOClient:
    """
    Redfish-based iLO4/iLO5/iLO6 client.
    Uses basic auth over HTTPS (LAN-only; uses CA bundle for SSL verification).
    """
    def __init__(self, host: str, username: str, password: str, ca_bundle: str = None):
        self.base = f"https://{host}"
        self.auth = (username, password)
        self.ca_bundle = ca_bundle or self._get_default_ca_bundle()

    def _get_default_ca_bundle(self) -> str | None:
        """Returns path to system CA bundle or None to use default."""
        return None  # Use requests' default CA bundle

    def _get(self, path: str) -> dict:
        r = requests.get(
            f"{self.base}{path}",
            auth=self.auth,
            verify=self.ca_bundle,
            timeout=5,
        )
        r.raise_for_status()
        return r.json()

    def poll(self) -> dict:
        try:
            thermal = self._get("/redfish/v1/Chassis/1/Thermal")
            power   = self._get("/redfish/v1/Chassis/1/Power")
            return {
                "cpu_temp":    thermal["Temperatures"][0]["ReadingCelsius"],
                "fan_rpm":     thermal["Fans"][0]["Reading"],
                "psu1_load_w": power["PowerControl"][0]["PowerConsumedWatts"],
                "health":      thermal["Status"]["Health"],
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
