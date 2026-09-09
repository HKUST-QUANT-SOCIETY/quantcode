"""Best-effort native notifications for background Pop updates."""
from __future__ import annotations

import os
import platform
import subprocess
import html
import json


def notify(title: str, body: str) -> bool:
    """Send a generic summary notification without including repo details."""
    if os.environ.get("QUANTCODE_SYSTEM_NOTIFICATIONS", "1").strip().lower() in {"0", "false", "off"}:
        return False
    system = platform.system()
    try:
        if system == "Darwin":
            # AppleScript arguments are quoted as literals, so update text is
            # never interpreted as code.
            script = f"display notification {json.dumps(body, ensure_ascii=False)} with title {json.dumps(title, ensure_ascii=False)}"
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=5)
        elif system == "Linux":
            subprocess.run(["notify-send", title, body], check=True, capture_output=True, timeout=5)
        elif system == "Windows":
            escaped_title = html.escape(title, quote=True)
            escaped_body = html.escape(body, quote=True)
            command = f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null; " \
                      f"$xml = [Windows.Data.Xml.Dom.XmlDocument]::new(); $xml.LoadXml(\"<toast><visual><binding template='ToastText02'><text>{escaped_title}</text><text>{escaped_body}</text></binding></visual></toast>\"); " \
                      "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('QuantCode').Show([Windows.UI.Notifications.ToastNotification]::new($xml))"
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], check=True, capture_output=True, timeout=5)
        else:
            return False
    except (OSError, subprocess.SubprocessError):
        return False
    return True
