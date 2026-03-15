"""NetworkManager and dnsmasq helpers for Raspberry Pi onboarding."""

from __future__ import annotations

import socket
import subprocess

try:
    from .device_setup_models import DeviceStatus, SetupConfig, WifiNetwork, WifiSettings
except ImportError:  # pragma: no cover - script execution on target image
    from device_setup_models import DeviceStatus, SetupConfig, WifiNetwork, WifiSettings

WLAN_INTERFACE = "wlan0"
CLIENT_CONNECTION_NAME = "pos-printer-client"
ACCESS_POINT_CONNECTION_NAME = "pos-printer-setup-ap"
ACCESS_POINT_ADDRESS = "10.42.0.1/24"
ACCESS_POINT_GATEWAY = "10.42.0.1"


def parse_wifi_scan_output(output: str) -> list[WifiNetwork]:
    """Parse multiline nmcli Wi-Fi scan output into deduplicated entries."""
    current: dict[str, str] = {}
    deduped: dict[str, WifiNetwork] = {}
    lines = [line.rstrip() for line in output.splitlines()]

    def commit(block: dict[str, str]) -> None:
        ssid = block.get("SSID", "").strip()
        if not ssid:
            return
        signal = int(block.get("SIGNAL", "0") or 0)
        network = WifiNetwork(
            ssid=ssid,
            signal=signal,
            security=block.get("SECURITY", "").strip() or "open",
            in_use=block.get("IN-USE", "").strip() == "*",
        )
        existing = deduped.get(ssid)
        if existing is None or network.signal > existing.signal:
            deduped[ssid] = network

    for line in lines + [""]:
        if not line:
            if current:
                commit(current)
                current = {}
            continue
        key, _, value = line.partition(":")
        current[key.strip()] = value.strip()

    return sorted(deduped.values(), key=lambda item: (-item.in_use, -item.signal, item.ssid.lower()))


class NetworkManager:
    """Small wrapper around nmcli and basic interface inspection."""

    def __init__(self, runner=subprocess.run) -> None:
        self._runner = runner

    def default_access_point_ssid(self) -> str:
        """Build a stable SSID from the hostname suffix."""
        hostname = socket.gethostname().split(".", 1)[0]
        suffix = hostname[-4:].upper() if len(hostname) >= 4 else hostname.upper()
        return f"POS-Printer-Setup-{suffix}"

    def scan_networks(self) -> list[WifiNetwork]:
        """Return nearby Wi-Fi networks suitable for the setup form."""
        try:
            completed = self._run(
                [
                    "nmcli",
                    "--mode",
                    "multiline",
                    "--fields",
                    "IN-USE,SSID,SIGNAL,SECURITY",
                    "device",
                    "wifi",
                    "list",
                    "ifname",
                    WLAN_INTERFACE,
                ]
            )
        except RuntimeError:
            return []
        return parse_wifi_scan_output(completed.stdout)

    def get_status(self, config: SetupConfig) -> DeviceStatus:
        """Build a live device status snapshot for the portal UI."""
        try:
            active_names = set(
                line.strip()
                for line in self._run(
                    ["nmcli", "--terse", "--fields", "NAME", "connection", "show", "--active"]
                ).stdout.splitlines()
                if line.strip()
            )
        except RuntimeError:
            active_names = set()
        ip_address = self._read_ip_address()
        client_ssid = ""
        if CLIENT_CONNECTION_NAME in active_names:
            client_ssid = config.wifi.ssid

        access_point_ssid = self.default_access_point_ssid()
        mode = "offline"
        if ACCESS_POINT_CONNECTION_NAME in active_names:
            mode = "access-point"
        elif CLIENT_CONNECTION_NAME in active_names:
            mode = "wifi"

        return DeviceStatus(
            mode=mode,
            hostname=socket.gethostname().split(".", 1)[0],
            ip_address=ip_address,
            client_ssid=client_ssid,
            access_point_ssid=access_point_ssid,
            saved_wifi_ssid=config.wifi.ssid,
            networks=self.scan_networks(),
        )

    def apply_wifi(self, wifi: WifiSettings) -> None:
        """Replace the Wi-Fi client connection with the saved credentials."""
        self._run(["nmcli", "connection", "delete", CLIENT_CONNECTION_NAME], check=False)
        self._run(
            [
                "nmcli",
                "connection",
                "add",
                "type",
                "wifi",
                "ifname",
                WLAN_INTERFACE,
                "con-name",
                CLIENT_CONNECTION_NAME,
                "ssid",
                wifi.ssid,
            ]
        )
        self._run(
            [
                "nmcli",
                "connection",
                "modify",
                CLIENT_CONNECTION_NAME,
                "connection.autoconnect",
                "yes",
                "802-11-wireless.hidden",
                "yes" if wifi.hidden else "no",
                "ipv4.method",
                "auto",
                "ipv6.method",
                "disabled",
            ]
        )
        if wifi.password:
            self._run(
                [
                    "nmcli",
                    "connection",
                    "modify",
                    CLIENT_CONNECTION_NAME,
                    "wifi-sec.key-mgmt",
                    "wpa-psk",
                    "wifi-sec.psk",
                    wifi.password,
                ]
            )
        self._run(
            [
                "nmcli",
                "--wait",
                "25",
                "connection",
                "up",
                CLIENT_CONNECTION_NAME,
                "ifname",
                WLAN_INTERFACE,
            ]
        )

    def ensure_access_point(self) -> None:
        """Create or refresh the setup access point connection and bring it up."""
        self._run(["nmcli", "connection", "delete", ACCESS_POINT_CONNECTION_NAME], check=False)
        self._run(
            [
                "nmcli",
                "connection",
                "add",
                "type",
                "wifi",
                "ifname",
                WLAN_INTERFACE,
                "con-name",
                ACCESS_POINT_CONNECTION_NAME,
                "ssid",
                self.default_access_point_ssid(),
            ]
        )
        self._run(
            [
                "nmcli",
                "connection",
                "modify",
                ACCESS_POINT_CONNECTION_NAME,
                "connection.autoconnect",
                "no",
                "802-11-wireless.mode",
                "ap",
                "802-11-wireless.band",
                "bg",
                "ipv4.method",
                "manual",
                "ipv4.addresses",
                ACCESS_POINT_ADDRESS,
                "ipv6.method",
                "disabled",
            ]
        )
        self._run(
            [
                "nmcli",
                "--wait",
                "15",
                "connection",
                "up",
                ACCESS_POINT_CONNECTION_NAME,
                "ifname",
                WLAN_INTERFACE,
            ]
        )

    def disable_access_point(self) -> None:
        """Stop the onboarding access point if it is active."""
        self._run(["nmcli", "connection", "down", ACCESS_POINT_CONNECTION_NAME], check=False)

    def _read_ip_address(self) -> str:
        completed = self._run(
            ["ip", "-4", "-brief", "address", "show", "dev", WLAN_INTERFACE],
            check=False,
        )
        fields = completed.stdout.split()
        if len(fields) >= 3:
            return fields[2].split("/", 1)[0]
        return ACCESS_POINT_GATEWAY

    def _run(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        completed = self._runner(
            args,
            check=False,
            capture_output=True,
            text=True,
        )
        if check and completed.returncode != 0:
            stderr = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(f"{' '.join(args)} failed: {stderr}")
        return completed
