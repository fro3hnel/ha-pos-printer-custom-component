"""Local setup portal for Wi-Fi onboarding and bridge configuration."""

from __future__ import annotations

import html
import logging
import threading
from http import HTTPStatus
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

try:
    from .device_setup_models import DeviceStatus, SetupConfig, WifiNetwork
    from .device_setup_network import ACCESS_POINT_GATEWAY, NetworkManager
    from .device_setup_service import apply_configuration, parse_setup_form
    from .device_setup_store import load_setup_config, save_setup_config
except ImportError:  # pragma: no cover - script execution on target image
    from device_setup_models import DeviceStatus, SetupConfig, WifiNetwork
    from device_setup_network import ACCESS_POINT_GATEWAY, NetworkManager
    from device_setup_service import apply_configuration, parse_setup_form
    from device_setup_store import load_setup_config, save_setup_config

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger("device_setup_portal")
APPLY_LOCK = threading.Lock()

CAPTIVE_PATHS = {
    "/generate_204",
    "/gen_204",
    "/hotspot-detect.html",
    "/ncsi.txt",
    "/connecttest.txt",
    "/success.txt",
    "/canonical.html",
}


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def _status_message(status: DeviceStatus) -> str:
    if status.mode == "wifi":
        return (
            f"Mit WLAN verbunden: <strong>{_escape(status.client_ssid)}</strong> "
            f"unter <strong>{_escape(status.ip_address)}</strong>."
        )
    if status.mode == "access-point":
        return (
            f"Setup-Access-Point aktiv: <strong>{_escape(status.access_point_ssid)}</strong>. "
            f"Portal-Adresse: <strong>http://{_escape(ACCESS_POINT_GATEWAY)}/</strong>."
        )
    return "Keine aktive WLAN-Verbindung erkannt. Das Portal bleibt lokal verfuegbar."


def _render_network_buttons(networks: list[WifiNetwork]) -> str:
    buttons = []
    for network in networks[:12]:
        ssid = _escape(network.ssid)
        security = _escape(network.security)
        buttons.append(
            "<button type=\"button\" class=\"ssid-button\" "
            f"onclick=\"selectSsid('{ssid}')\">{ssid} "
            f"<span>{network.signal}% · {security}</span></button>"
        )
    return "\n".join(buttons) or "<p class=\"muted\">Keine Netzwerke gefunden. SSID manuell eintragen.</p>"


def _render_page(
    config: SetupConfig,
    status: DeviceStatus,
    *,
    banner: str = "",
    errors: list[str] | None = None,
) -> str:
    error_list = "".join(f"<li>{_escape(item)}</li>" for item in (errors or []))
    error_block = (
        f"<div class=\"card error\"><ul>{error_list}</ul></div>" if error_list else ""
    )
    banner_block = (
        f"<div class=\"card banner\"><p>{_escape(banner)}</p></div>" if banner else ""
    )
    current_wifi_ssid = _escape(config.wifi.ssid)
    mqtt_password_hint = (
        "Leer lassen, um das gespeicherte Passwort beizubehalten."
        if config.bridge.mqtt_password
        else ""
    )
    wifi_password_hint = (
        "Leer lassen, um das gespeicherte Passwort beizubehalten."
        if config.wifi.password
        else ""
    )
    selected_level = config.bridge.log_level.upper()

    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>POS Printer Setup</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #102130;
      --muted: #5f7687;
      --line: #d7e0e7;
      --panel: #ffffff;
      --accent: #0f766e;
      --accent-soft: #d9f4ef;
      --error: #a11b2b;
      --error-soft: #fde8ea;
      --bg: linear-gradient(180deg, #eff6f7 0%, #f8fafb 100%);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--bg);
    }}
    main {{
      max-width: 980px;
      margin: 0 auto;
      padding: 24px 16px 48px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: clamp(2rem, 3vw, 3rem);
      letter-spacing: -0.04em;
    }}
    .lead {{
      margin: 0 0 24px;
      color: var(--muted);
      max-width: 58ch;
    }}
    .layout {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px;
      box-shadow: 0 18px 40px rgba(16, 33, 48, 0.05);
    }}
    .banner {{
      background: var(--accent-soft);
      border-color: rgba(15, 118, 110, 0.25);
      margin-bottom: 16px;
    }}
    .error {{
      background: var(--error-soft);
      border-color: rgba(161, 27, 43, 0.2);
      margin-bottom: 16px;
      color: var(--error);
    }}
    h2 {{
      margin: 0 0 14px;
      font-size: 1.15rem;
    }}
    h3 {{
      margin: 0 0 10px;
      font-size: 0.95rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
    }}
    form {{
      display: grid;
      gap: 12px;
    }}
    label {{
      display: grid;
      gap: 6px;
      font-size: 0.92rem;
    }}
    input, select {{
      width: 100%;
      border-radius: 12px;
      border: 1px solid var(--line);
      padding: 11px 12px;
      font: inherit;
      background: #fff;
      color: var(--ink);
    }}
    .grid {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    }}
    .checkbox {{
      display: flex;
      gap: 8px;
      align-items: center;
      font-size: 0.92rem;
    }}
    .checkbox input {{
      width: auto;
      margin: 0;
    }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 4px;
    }}
    button {{
      border: 0;
      border-radius: 999px;
      padding: 11px 16px;
      font: inherit;
      cursor: pointer;
    }}
    .primary {{
      background: var(--accent);
      color: #fff;
    }}
    .secondary {{
      background: transparent;
      color: var(--ink);
      border: 1px solid var(--line);
    }}
    .ssid-list {{
      display: grid;
      gap: 8px;
    }}
    .ssid-button {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      width: 100%;
      background: #f5f8fa;
      border: 1px solid var(--line);
      border-radius: 12px;
      text-align: left;
    }}
    .ssid-button span {{
      color: var(--muted);
      font-size: 0.85rem;
    }}
    .muted {{
      color: var(--muted);
      margin: 0;
    }}
    .hint {{
      margin: 0;
      color: var(--muted);
      font-size: 0.83rem;
    }}
    code {{
      font-family: "SFMono-Regular", "Menlo", monospace;
    }}
  </style>
  <script>
    function selectSsid(ssid) {{
      document.getElementById("wifi_ssid").value = ssid;
      document.getElementById("wifi_hidden").checked = false;
      window.scrollTo({{ top: 0, behavior: "smooth" }});
    }}
  </script>
</head>
<body>
  <main>
    <h1>POS Printer Setup</h1>
    <p class="lead">Verbinde den Raspberry Pi mit deinem WLAN und hinterlege die Bridge-Konfiguration direkt ueber das lokale Portal.</p>
    {banner_block}
    {error_block}
    <div class="layout">
      <section class="card">
        <h2>Status</h2>
        <p>{_status_message(status)}</p>
        <div class="grid">
          <div>
            <h3>Hostname</h3>
            <p class="muted"><code>{_escape(status.hostname)}</code></p>
          </div>
          <div>
            <h3>IP-Adresse</h3>
            <p class="muted"><code>{_escape(status.ip_address)}</code></p>
          </div>
          <div>
            <h3>Gespeichertes WLAN</h3>
            <p class="muted"><code>{_escape(status.saved_wifi_ssid or "-")}</code></p>
          </div>
        </div>
      </section>
      <section class="card">
        <h2>Verfuegbare WLANs</h2>
        <div class="ssid-list">
          {_render_network_buttons(status.networks)}
        </div>
      </section>
    </div>
    <section class="card" style="margin-top: 16px;">
      <h2>Konfiguration</h2>
      <form method="post" action="/configure">
        <div class="layout">
          <div>
            <h3>WLAN</h3>
            <label>
              SSID
              <input id="wifi_ssid" name="wifi_ssid" value="{current_wifi_ssid}" autocomplete="organization">
            </label>
            <label>
              WLAN-Passwort
              <input type="password" name="wifi_password" autocomplete="current-password">
            </label>
            <p class="hint">{_escape(wifi_password_hint)}</p>
            <label class="checkbox">
              <input id="wifi_hidden" type="checkbox" name="wifi_hidden" {"checked" if config.wifi.hidden else ""}>
              Verstecktes Netzwerk
            </label>
          </div>
          <div>
            <h3>Bridge</h3>
            <div class="grid">
              <label>
                MQTT Host
                <input name="mqtt_broker" value="{_escape(config.bridge.mqtt_broker)}">
              </label>
              <label>
                MQTT Port
                <input name="mqtt_port" value="{config.bridge.mqtt_port}" inputmode="numeric">
              </label>
              <label>
                MQTT Benutzer
                <input name="mqtt_username" value="{_escape(config.bridge.mqtt_username)}">
              </label>
              <label>
                MQTT Passwort
                <input type="password" name="mqtt_password">
              </label>
              <label>
                Redis URL
                <input name="redis_url" value="{_escape(config.bridge.redis_url)}">
              </label>
              <label>
                Printer Port
                <input name="printer_port" value="{_escape(config.bridge.printer_port)}">
              </label>
              <label>
                Printer Name
                <input name="printer_name" value="{_escape(config.bridge.printer_name)}">
              </label>
              <label>
                Log Level
                <select name="log_level">
                  <option value="DEBUG" {"selected" if selected_level == "DEBUG" else ""}>DEBUG</option>
                  <option value="INFO" {"selected" if selected_level == "INFO" else ""}>INFO</option>
                  <option value="WARNING" {"selected" if selected_level == "WARNING" else ""}>WARNING</option>
                  <option value="ERROR" {"selected" if selected_level == "ERROR" else ""}>ERROR</option>
                </select>
              </label>
              <label>
                Heartbeat (s)
                <input name="heartbeat_interval" value="{config.bridge.heartbeat_interval}" inputmode="numeric">
              </label>
              <label>
                Left Margin
                <input name="left_margin" value="{config.bridge.left_margin}" inputmode="numeric">
              </label>
              <label>
                Default Width
                <input name="default_width" value="{config.bridge.default_width}" inputmode="numeric">
              </label>
              <label>
                Image Timeout
                <input name="image_fetch_timeout" value="{config.bridge.image_fetch_timeout}" inputmode="numeric">
              </label>
            </div>
            <p class="hint">{_escape(mqtt_password_hint)}</p>
          </div>
        </div>
        <div class="actions">
          <button class="primary" type="submit">Speichern und anwenden</button>
          <button class="secondary" type="submit" name="action" value="clear_wifi">WLAN entfernen und Setup-AP aktiv lassen</button>
        </div>
      </form>
    </section>
  </main>
</body>
</html>
"""


def _redirect(start_response, location: str) -> list[bytes]:
    start_response(
        f"{HTTPStatus.FOUND.value} {HTTPStatus.FOUND.phrase}",
        [("Location", location)],
    )
    return [b""]


def _schedule_apply(config: SetupConfig) -> None:
    def worker() -> None:
        with APPLY_LOCK:
            result = apply_configuration(config)
            LOGGER.info("%s", result.message)

    threading.Thread(target=worker, daemon=True).start()


def application(environ, start_response):  # type: ignore[no-untyped-def]
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()

    if path in CAPTIVE_PATHS:
        return _redirect(start_response, "/")

    config = load_setup_config()
    network = NetworkManager()

    if method == "POST" and path == "/configure":
        body_size = int(environ.get("CONTENT_LENGTH") or "0")
        body = environ["wsgi.input"].read(body_size).decode("utf-8")
        form = parse_qs(body, keep_blank_values=True)
        updated, errors = parse_setup_form(form, config)
        if errors:
            status = network.get_status(config)
            payload = _render_page(updated, status, errors=errors)
            start_response(
                f"{HTTPStatus.BAD_REQUEST.value} {HTTPStatus.BAD_REQUEST.phrase}",
                [("Content-Type", "text/html; charset=utf-8")],
            )
            return [payload.encode("utf-8")]

        save_setup_config(updated)
        _schedule_apply(updated)
        status = network.get_status(updated)
        payload = _render_page(
            updated,
            status,
            banner=(
                "Konfiguration gespeichert. Der Raspberry Pi wendet die Einstellungen jetzt an. "
                "Bei einem Wechsel vom Setup-AP ins Heimnetz kann die Verbindung kurz abbrechen."
            ),
        )
        start_response(
            f"{HTTPStatus.OK.value} {HTTPStatus.OK.phrase}",
            [("Content-Type", "text/html; charset=utf-8")],
        )
        return [payload.encode("utf-8")]

    status = network.get_status(config)
    payload = _render_page(config, status)
    start_response(
        f"{HTTPStatus.OK.value} {HTTPStatus.OK.phrase}",
        [("Content-Type", "text/html; charset=utf-8")],
    )
    return [payload.encode("utf-8")]


def main() -> None:
    """Serve the onboarding portal on the standard HTTP port."""
    with make_server("0.0.0.0", 80, application) as server:
        LOGGER.info("Setup portal listening on port 80")
        server.serve_forever()


if __name__ == "__main__":
    main()
