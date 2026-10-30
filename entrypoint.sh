
#!/bin/bash

set -Eeuo pipefail

cd /home/team

uvicorn app.main:app \
    --app-dir /home/team \
    --host 0.0.0.0 \
    --port 8000 &

UVICORN_PID=$!

ttyd -W -p 7681 -b /terminal /bin/bash &

TTYD_PID=$!

shutdown() {
    kill -TERM "$UVICORN_PID" "$TTYD_PID" 2>/dev/null || true

    wait "$UVICORN_PID" 2>/dev/null || true
    wait "$TTYD_PID" 2>/dev/null || true
}

trap shutdown SIGTERM SIGINT

if wait -n "$UVICORN_PID" "$TTYD_PID"; then
    STATUS=0
else
    STATUS=$?
fi

shutdown

exit "$STATUS"
