from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen
import webbrowser

from memwing.config_store import get_config_value
from memwing.runtime_env import build_runtime_env


DEFAULT_CONTROL_PLANE_HOST = "127.0.0.1"
DEFAULT_CONTROL_PLANE_PORT = 5173


class ControlPlaneLauncherError(ValueError):
    pass


def run_control_plane_command(args: argparse.Namespace, config: dict[str, Any]) -> int:
    host = str(args.host)
    port = int(args.port)
    ui_url = f"http://{_browser_host(host)}:{port}/"
    api_base_url = _api_base_url(config, args.api_base_url)

    if _ui_responds(ui_url):
        print(f"Control Plane: opening existing UI at {ui_url}")
        _open_browser(ui_url, enabled=bool(args.open))
        return 0

    if args.mock:
        return _start_vite_frontend(host, port, api_base_url, open_browser=bool(args.open), mock=True)

    static_dir = _find_static_assets_dir()
    if static_dir is not None:
        print(f"Control Plane: starting bundled UI at {ui_url}")
        print(f"Control Plane API: {api_base_url}")
        _open_browser(ui_url, enabled=bool(args.open))
        _serve_static_control_plane(static_dir, host, port, api_base_url)
        return 0

    return _start_vite_frontend(host, port, api_base_url, open_browser=bool(args.open), mock=False)


def _start_vite_frontend(
    host: str,
    port: int,
    api_base_url: str,
    *,
    open_browser: bool,
    mock: bool,
) -> int:
    frontend_dir = _find_frontend_source_dir()
    if frontend_dir is None:
        raise ControlPlaneLauncherError(
            "Control Plane frontend assets are unavailable. "
            "Install an artifact that includes control-plane assets, or run from a checkout "
            "with frontend/package.json and build assets with `cd frontend && npm run build`."
        )
    npm = shutil.which("npm")
    if npm is None:
        raise ControlPlaneLauncherError(
            "Control Plane frontend source is present, but npm is unavailable. "
            "Install npm or use a release artifact with bundled frontend assets."
        )

    script = "dev:mock" if mock else "dev"
    env = dict(os.environ)
    env["VITE_MEMWING_API_PROXY_TARGET"] = api_base_url
    if mock:
        env["VITE_MEMWING_USE_MOCK_API"] = "1"
    ui_url = f"http://{_browser_host(host)}:{port}/"
    print(f"Control Plane: starting local frontend server at {ui_url}")
    print(f"Control Plane API: {'mock' if mock else api_base_url}")
    _open_browser(ui_url, enabled=open_browser)
    process = subprocess.Popen(
        [npm, "run", script, "--", "--host", host, "--port", str(port)],
        cwd=frontend_dir,
        env=env,
    )
    return int(process.wait())


def _serve_static_control_plane(
    static_dir: Path,
    host: str,
    port: int,
    api_base_url: str,
) -> None:
    handler = _control_plane_handler(static_dir, api_base_url)
    try:
        server = ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        raise ControlPlaneLauncherError(
            f"Control Plane could not bind {host}:{port}: {exc}. "
            "Choose another port with `memwing control-plane --port <port>`."
        ) from exc
    with server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nControl Plane: stopped")


def _control_plane_handler(static_dir: Path, api_base_url: str) -> type[SimpleHTTPRequestHandler]:
    class ControlPlaneHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(static_dir), **kwargs)

        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            if self.path.startswith("/v1/"):
                self._proxy()
                return
            super().do_GET()

        def do_POST(self) -> None:
            self._proxy()

        def do_PATCH(self) -> None:
            self._proxy()

        def do_DELETE(self) -> None:
            self._proxy()

        def send_head(self) -> object:
            path = self.translate_path(self.path)
            if not Path(path).exists() and not self.path.startswith("/assets/"):
                self.path = "/index.html"
            return super().send_head()

        def _proxy(self) -> None:
            target = urljoin(f"{api_base_url}/", self.path.lstrip("/"))
            body = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
            headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() not in {"host", "content-length", "accept-encoding"}
            }
            request = Request(target, data=body or None, headers=headers, method=self.command)
            try:
                response = urlopen(request, timeout=30)
                payload = response.read()
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() not in {"transfer-encoding", "connection"}:
                        self.send_header(key, value)
                self.end_headers()
                self.wfile.write(payload)
            except HTTPError as exc:
                payload = exc.read()
                self.send_response(exc.code)
                for key, value in exc.headers.items():
                    if key.lower() not in {"transfer-encoding", "connection"}:
                        self.send_header(key, value)
                self.end_headers()
                self.wfile.write(payload)
            except (OSError, TimeoutError, URLError) as exc:
                payload = f"MemWing API proxy failed: {exc}".encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

    return ControlPlaneHandler


def _api_base_url(config: dict[str, Any], explicit: str | None) -> str:
    if explicit is not None and explicit.strip():
        return explicit.rstrip("/")
    runtime_env = build_runtime_env(config)
    host = runtime_env.env.get("MEMWING_API_HOST") or str(get_config_value(config, "api.host"))
    port = runtime_env.env.get("MEMWING_API_PORT") or str(get_config_value(config, "api.port"))
    return f"http://{_browser_host(host)}:{port}"


def _browser_host(host: str) -> str:
    return "127.0.0.1" if host in {"0.0.0.0", "::"} else host


def _ui_responds(ui_url: str) -> bool:
    try:
        response = urlopen(ui_url, timeout=0.5)
        close = getattr(response, "close", None)
        if callable(close):
            close()
        return True
    except (OSError, TimeoutError, URLError):
        return False


def _open_browser(url: str, *, enabled: bool) -> None:
    if enabled:
        webbrowser.open(url)


def _find_static_assets_dir() -> Path | None:
    configured = os.environ.get("MEMWING_CONTROL_PLANE_DIST")
    candidates: list[Path] = []
    if configured is not None and configured.strip():
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        (
            _artifact_prefix() / "control-plane",
            _repo_root() / "frontend" / "dist",
        )
    )
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


def _find_frontend_source_dir() -> Path | None:
    candidate = _repo_root() / "frontend"
    if (candidate / "package.json").is_file():
        return candidate
    return None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _artifact_prefix() -> Path:
    executable = Path(sys.argv[0]).expanduser()
    if len(executable.parts) >= 2 and executable.parent.name == "bin":
        return executable.resolve().parent.parent
    module_path = Path(__file__).resolve()
    if len(module_path.parents) > 3:
        return module_path.parents[3]
    return _repo_root()
