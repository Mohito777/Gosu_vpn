import json
import uuid as uuid_lib
from typing import Optional
import requests
from requests import Session
import config
from logger import get_logger

log = get_logger("xui_api")


class XUIClient:
    """Async-friendly wrapper around 3x-ui REST API using requests.Session."""

    def __init__(self):
        self.base_url = config.XUI_URL.rstrip("/")
        self.inbound_id = config.XUI_INBOUND_ID
        self.session: Optional[Session] = None
        self._logged_in = False

    # ── Auth ─────────────────────────────────────────────────────────────────

    def login(self) -> bool:
        try:
            self.session = requests.Session()
            self.session.headers.update({"Content-Type": "application/json"})
            resp = self.session.post(
                f"{self.base_url}/login",
                json={"username": config.XUI_USERNAME, "password": config.XUI_PASSWORD},
                timeout=10,
            )
            data = resp.json()
            if data.get("success"):
                self._logged_in = True
                log.info("3x-ui login successful")
                return True
            log.error(f"3x-ui login failed: {data}")
            return False
        except Exception as e:
            log.error(f"3x-ui login exception: {e}")
            return False

    def _ensure_session(self) -> bool:
        if not self._logged_in or self.session is None:
            return self.login()
        return True

    # ── Inbound helpers ───────────────────────────────────────────────────────

    def _get_inbound(self) -> Optional[dict]:
        try:
            resp = self.session.get(
                f"{self.base_url}/panel/api/inbounds/get/{self.inbound_id}",
                timeout=10,
            )
            data = resp.json()
            if data.get("success"):
                return data["obj"]
            log.error(f"Failed to get inbound {self.inbound_id}: {data}")
            return None
        except Exception as e:
            log.error(f"_get_inbound exception: {e}")
            return None

    # ── Client management ─────────────────────────────────────────────────────

    def add_client(self, client_uuid: str, email: str, days: int) -> bool:
        """Add a VLESS client to the inbound. Returns True on success."""
        if not self._ensure_session():
            return False
        try:
            settings = {
                "clients": [
                    {
                        "id": client_uuid,
                        "alterId": 0,
                        "email": email,
                        "limitIp": 3,
                        "totalGB": 0,
                        "expiryTime": self._days_to_ms(days),
                        "enable": True,
                        "tgId": "",
                        "subId": "",
                        "comment": f"bot_user_{email}",
                    }
                ]
            }
            payload = {
                "id": self.inbound_id,
                "settings": json.dumps(settings),
            }
            resp = self.session.post(
                f"{self.base_url}/panel/api/inbounds/addClient",
                json=payload,
                timeout=10,
            )
            data = resp.json()
            if data.get("success"):
                log.info(f"Client added: uuid={client_uuid} email={email} days={days}")
                return True
            log.error(f"add_client failed: {data}")
            return False
        except Exception as e:
            log.error(f"add_client exception: {e}")
            return False

    def delete_client(self, client_uuid: str) -> bool:
        """Delete a client from the inbound by UUID. Returns True on success."""
        if not self._ensure_session():
            return False
        try:
            resp = self.session.post(
                f"{self.base_url}/panel/api/inbounds/{self.inbound_id}/delClient/{client_uuid}",
                timeout=10,
            )
            data = resp.json()
            if data.get("success"):
                log.info(f"Client deleted: uuid={client_uuid}")
                return True
            log.error(f"delete_client failed: {data}")
            return False
        except Exception as e:
            log.error(f"delete_client exception: {e}")
            return False

    def client_exists(self, client_uuid: str) -> bool:
        """Check whether a client UUID is present in the inbound."""
        if not self._ensure_session():
            return False
        try:
            inbound = self._get_inbound()
            if not inbound:
                return False
            settings = json.loads(inbound.get("settings", "{}"))
            clients = settings.get("clients", [])
            return any(c.get("id") == client_uuid for c in clients)
        except Exception as e:
            log.error(f"client_exists exception: {e}")
            return False

    def get_client_config_link(self, client_uuid: str, remark: str = "VPN") -> Optional[str]:
        """
        Build a VLESS connection link.
        Requires XUI_VLESS_DOMAIN and XUI_VLESS_PORT in .env (optional extras).
        """
        import os
        domain = os.getenv("XUI_VLESS_DOMAIN", "")
        port = os.getenv("XUI_VLESS_PORT", "443")
        sni = os.getenv("XUI_VLESS_SNI", domain)
        fp = os.getenv("XUI_VLESS_FP", "chrome")
        network = os.getenv("XUI_VLESS_NETWORK", "ws")
        path = os.getenv("XUI_VLESS_PATH", "/vless")
        security = os.getenv("XUI_VLESS_SECURITY", "tls")

        if not domain:
            return None

        link = (
            f"vless://{client_uuid}@{domain}:{port}"
            f"?type={network}&security={security}"
            f"&sni={sni}&fp={fp}&path={path}"
            f"#{remark}"
        )
        return link

    # ── Traffic Statistics ────────────────────────────────────────────────────

    def get_client_traffic(self, client_uuid: str) -> Optional[dict]:
        """
        Get traffic statistics for a client.
        Returns: {"upload": int, "download": int, "total": int, "remaining_gb": float}
        """
        if not self._ensure_session():
            return None
        
        try:
            inbound = self._get_inbound()
            if not inbound:
                return None
            
            settings = json.loads(inbound.get("settings", "{}"))
            clients = settings.get("clients", [])
            
            for client in clients:
                if client.get("id") == client_uuid:
                    # Трафик в байтах
                    upload = client.get("up", 0)
                    download = client.get("down", 0)
                    total = upload + download
                    
                    # Лимит трафика (в байтах)
                    total_gb = client.get("totalGB", 0)
                    
                    # Остаток
                    if total_gb > 0:
                        remaining = total_gb - total
                        remaining_gb = max(0, remaining / (1024 ** 3))
                    else:
                        remaining_gb = 0  # Безлимит
                    
                    return {
                        "upload": upload,
                        "download": download,
                        "total": total,
                        "upload_gb": upload / (1024 ** 3),
                        "download_gb": download / (1024 ** 3),
                        "total_gb": total / (1024 ** 3),
                        "remaining_gb": remaining_gb,
                        "limit_gb": total_gb / (1024 ** 3) if total_gb > 0 else "∞",
                    }
            
            return None
        except Exception as e:
            log.error(f"get_client_traffic exception: {e}")
            return None

    def get_all_clients_traffic(self) -> list[dict]:
        """
        Get traffic statistics for all clients.
        Returns list of dicts with email, uuid, and traffic info.
        """
        if not self._ensure_session():
            return []
        
        try:
            inbound = self._get_inbound()
            if not inbound:
                return []
            
            settings = json.loads(inbound.get("settings", "{}"))
            clients = settings.get("clients", [])
            
            result = []
            for client in clients:
                upload = client.get("up", 0)
                download = client.get("down", 0)
                total = upload + download
                total_gb = client.get("totalGB", 0)
                
                result.append({
                    "email": client.get("email", ""),
                    "uuid": client.get("id", ""),
                    "enable": client.get("enable", True),
                    "upload_gb": upload / (1024 ** 3),
                    "download_gb": download / (1024 ** 3),
                    "total_gb": total / (1024 ** 3),
                    "limit_gb": total_gb / (1024 ** 3) if total_gb > 0 else "∞",
                    "expiry_time": client.get("expiryTime", 0),
                })
            
            return result
        except Exception as e:
            log.error(f"get_all_clients_traffic exception: {e}")
            return []

    def reset_client_traffic(self, client_uuid: str) -> bool:
        """Reset traffic counter for a client."""
        if not self._ensure_session():
            return False
        
        try:
            resp = self.session.post(
                f"{self.base_url}/panel/api/inbounds/{self.inbound_id}/resetClientTraffic/{client_uuid}",
                timeout=10,
            )
            data = resp.json()
            if data.get("success"):
                log.info(f"Traffic reset for client: uuid={client_uuid}")
                return True
            log.error(f"reset_client_traffic failed: {data}")
            return False
        except Exception as e:
            log.error(f"reset_client_traffic exception: {e}")
            return False

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def generate_uuid() -> str:
        return str(uuid_lib.uuid4())

    @staticmethod
    def _days_to_ms(days: int) -> int:
        """Convert days from now to epoch milliseconds (3x-ui expiryTime format)."""
        from datetime import datetime, timedelta
        dt = datetime.utcnow() + timedelta(days=days)
        return int(dt.timestamp() * 1000)


# Singleton
xui = XUIClient()
