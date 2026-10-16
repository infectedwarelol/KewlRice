#!/usr/bin/env python3
import os
import socket
import subprocess
import sys

SOCKET_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "kewl-ui.sock")


def main(arguments):
    if len(arguments) != 1:
        return 2
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.3)
            connection.connect(SOCKET_PATH)
            connection.sendall(f"popup {arguments[0]}".encode())
        return 0
    except OSError:
        popups = os.path.join(os.path.dirname(os.path.abspath(__file__)), "popups.py")
        subprocess.Popen([sys.executable, popups, arguments[0]], start_new_session=True)
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
