#!/usr/bin/env sh
set -eu

PREFIX="${1:-${MEMWING_INSTALL_PREFIX:-$HOME/.local}}"
SMOKE_HOME="${MEMWING_SMOKE_HOME:-$(mktemp -d)}"
FAKE_BIN="$SMOKE_HOME/bin"
SMOKE_PORT="${MEMWING_SMOKE_PORT:-$(python3 - <<'PY'
import socket

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)}"
CONTROL_PLANE_PORT="${MEMWING_CONTROL_PLANE_SMOKE_PORT:-$(python3 - <<'PY'
import socket

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)}"

cleanup_runtime() {
  if [ -f "$SMOKE_HOME/control-plane.pid" ]; then
    control_plane_pid="$(cat "$SMOKE_HOME/control-plane.pid")"
    if [ -n "$control_plane_pid" ]; then
      kill "$control_plane_pid" >/dev/null 2>&1 || true
    fi
  fi
  if [ -f "$SMOKE_HOME/runtime.pid" ]; then
    runtime_pid="$(cat "$SMOKE_HOME/runtime.pid")"
    if [ -n "$runtime_pid" ]; then
      kill "$runtime_pid" >/dev/null 2>&1 || true
    fi
  fi
}

trap cleanup_runtime EXIT INT TERM

mkdir -p "$FAKE_BIN"
cat > "$FAKE_BIN/openclaw" <<'EOF'
#!/usr/bin/env sh
set -eu

command="${1:-}"
subcommand="${2:-}"
key="${3:-}"

if [ "$command" = "plugins" ] && [ "$subcommand" = "install" ]; then
  exit 0
fi

if [ "$command" = "config" ] && [ "$subcommand" = "set" ]; then
  exit 0
fi

if [ "$command" = "plugins" ] && [ "$subcommand" = "inspect" ]; then
  printf '{"capabilities":[{"kind":"context-engine","ids":["memwing"]}]}\n'
  exit 0
fi

if [ "$command" = "config" ] && [ "$subcommand" = "get" ] && [ "$key" = "plugins.slots.contextEngine" ]; then
  printf '"memwing"\n'
  exit 0
fi

if [ "$command" = "config" ] && [ "$subcommand" = "get" ] && [ "$key" = "plugins.entries.memwing" ]; then
  printf '{"enabled":true,"hooks":{"allowConversationAccess":true}}\n'
  exit 0
fi

echo "unexpected fake openclaw command: $*" >&2
exit 1
EOF
chmod +x "$FAKE_BIN/openclaw"

PATH="$PREFIX/bin:$PATH"
export PATH

PATH="$FAKE_BIN:$PATH" \
MEMWING_HOME="$SMOKE_HOME" \
MEMWING_API_PORT="$SMOKE_PORT" \
OPENCLAW_CLI="$FAKE_BIN/openclaw" \
  memwing quickstart --profile lite

MEMWING_HOME="$SMOKE_HOME" python3 - <<PY
import urllib.request

urllib.request.urlopen("http://127.0.0.1:$SMOKE_PORT/healthz", timeout=5).read()
PY

MEMWING_HOME="$SMOKE_HOME" \
  memwing control-plane \
    --host 127.0.0.1 \
    --port "$CONTROL_PLANE_PORT" \
    --api-base-url "http://127.0.0.1:$SMOKE_PORT" \
    > "$SMOKE_HOME/control-plane.log" 2>&1 &
echo "$!" > "$SMOKE_HOME/control-plane.pid"

MEMWING_HOME="$SMOKE_HOME" python3 - <<PY
import time
import urllib.request

deadline = time.monotonic() + 5
last_error = None
while time.monotonic() < deadline:
    try:
        body = urllib.request.urlopen(
            "http://127.0.0.1:$CONTROL_PLANE_PORT/",
            timeout=1,
        ).read().decode("utf-8")
        if "MemWing" in body:
            break
        last_error = "Control Plane index did not contain MemWing"
    except Exception as exc:  # noqa: BLE001
        last_error = exc
    time.sleep(0.1)
else:
    raise SystemExit(f"Control Plane smoke failed: {last_error}")
PY
