#!/usr/bin/env python3
import json
import os
import socket
import subprocess
import sys

REFRESH_EVENTS = {"workspace", "workspacev2", "createworkspace", "createworkspacev2", "destroyworkspace", "destroyworkspacev2", "moveworkspace", "moveworkspacev2", "focusedmon", "focusedmonv2"}


def hyprctl_json(command):
    try:
        return json.loads(subprocess.run(["hyprctl", command, "-j"], capture_output=True, text=True, timeout=2).stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return None


def render():
    workspaces = hyprctl_json("workspaces") or []
    active = hyprctl_json("activeworkspace") or {}
    ids = sorted(workspace["id"] for workspace in workspaces if workspace.get("id", 0) > 0)
    if len(ids) < 2:
        return {"text": "", "class": "single"}
    active_id = active.get("id")
    dots = " ".join("<span weight='bold'>●</span>" if workspace_id == active_id else "<span fgalpha='45%'>○</span>" for workspace_id in ids)
    position = ids.index(active_id) + 1 if active_id in ids else 0
    return {"text": dots, "class": "multiple", "tooltip": f"Workspace {position} of {len(ids)}\nCtrl + Tab to switch"}


def emit(previous):
    line = json.dumps(render())
    if line != previous:
        print(line, flush=True)
    return line


def main():
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    path = os.path.join(runtime, "hypr", signature, ".socket2.sock")
    previous = emit(None)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(path)
        buffer = b""
        while True:
            chunk = connection.recv(4096)
            if not chunk:
                sys.exit(1)
            buffer += chunk
            *lines, buffer = buffer.split(b"\n")
            if any(line.split(b">>", 1)[0].decode(errors="ignore") in REFRESH_EVENTS for line in lines):
                previous = emit(previous)


if __name__ == "__main__":
    main()
