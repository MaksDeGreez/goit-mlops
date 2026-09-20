#!/usr/bin/env bash
#
# The whole story of the platform, on one machine, against the stack in
# docker-compose.yml:
#
#   train twice -> promote -> promote again -> roll back -> refuse bad input
#   -> hit the rate limit -> refuse a model with a wrong checksum -> send
#   normal and drifted traffic and let the drift job compare them.
#
# Start the stack first:
#
#   cp .env.example .env
#   docker compose up -d --wait
#   scripts/local_e2e.sh
#
# The script can be run as often as you like. Every run trains two new model
# versions and leaves the one it started with in production.

set -euo pipefail

cd "$(dirname "$0")/.."

STAGING_URL="http://localhost:8001"
PRODUCTION_URL="http://localhost:8002"
PUSHGATEWAY_URL="http://localhost:9091"
# 5001, because macOS uses 5000 for the AirPlay receiver.
MLFLOW_URL="http://localhost:5001"

# Name of the throw-away container of the checksum demo, so a container left
# behind by an interrupted run can be removed before the next one starts.
CHECKSUM_DEMO="final-project-checksum-demo"
CHECKSUM_DEMO_URL="http://localhost:8009"

# How many requests the traffic steps send. Below about 400 rows the PSI score
# of unchanged data is already noisy enough to report drift that is not there.
TRAFFIC_ROWS=400
TRAFFIC_RATE=15

WORK_DIR="$(mktemp -d /tmp/final-project-e2e.XXXXXX)"
TOOL_LOG="$WORK_DIR/tools.log"

cleanup() {
    docker rm -f "$CHECKSUM_DEMO" >/dev/null 2>&1 || true
    rm -rf "$WORK_DIR"
}
trap cleanup EXIT

step() {
    printf '\n\033[1m== %s ==\033[0m\n' "$*"
}

# Runs one of the tools from the "tools" profile. Its stdout is the machine
# readable output, its log goes to a file so the steps stay readable.
tool() {
    docker compose run --rm "$@" 2>>"$TOOL_LOG"
}

field() {
    python3 -c 'import json,sys; print(json.loads(sys.argv[1])[sys.argv[2]])' "$1" "$2"
}

# Waits until the pod behind a URL serves a given model version. The services
# follow an alias and only look at the registry every MODEL_RELOAD_SECONDS.
wait_for_version() {
    local url="$1" wanted="$2" waited=0 seen=""
    while [ "$waited" -lt 90 ]; do
        seen="$(curl -fsS "$url/info" 2>/dev/null |
            python3 -c 'import json,sys; print(json.load(sys.stdin).get("model_version"))' || true)"
        if [ "$seen" = "$wanted" ]; then
            echo "$url serves version $wanted (after ${waited}s)"
            return 0
        fi
        sleep 3
        waited=$((waited + 3))
    done
    echo "$url did not pick up version $wanted within ${waited}s" >&2
    return 1
}

predict() {
    curl -fsS -X POST "$1/predict" -H 'Content-Type: application/json' -d '{
      "MedInc": 8.3252, "HouseAge": 41.0, "AveRooms": 6.9841, "AveBedrms": 1.0238,
      "Population": 322.0, "AveOccup": 2.5556, "Latitude": 37.88, "Longitude": -122.23}'
    echo
}

# ---------------------------------------------------------------------------

step "the stack is up"
if ! curl -fsS "$MLFLOW_URL/health" >/dev/null; then
    echo "MLflow does not answer on $MLFLOW_URL." >&2
    echo "Start the stack first: cp .env.example .env && docker compose up -d --wait" >&2
    exit 1
fi
docker compose ps --format 'table {{.Service}}\t{{.Status}}'
echo "the log of the tools goes to $TOOL_LOG"

step "train a model"
first_json="$(tool training)"
first="$(field "$first_json" version)"
echo "$first_json"

step "train it again, which makes a second version"
second_json="$(tool training)"
second="$(field "$second_json" version)"
echo "$second_json"

step "what the registry holds now"
# The table is written to stderr on purpose: stdout of this tool carries the
# audit lines and nothing else.
docker compose run --rm registry-ops list

step "version $first becomes the production one"
tool registry-ops promote --version "$first"
wait_for_version "$PRODUCTION_URL" "$first"

step "version $second replaces it, so $first is archived"
tool registry-ops promote --version "$second"
wait_for_version "$PRODUCTION_URL" "$second"
predict "$PRODUCTION_URL"

step "roll back: production goes to version $first again"
tool registry-ops rollback
wait_for_version "$PRODUCTION_URL" "$first"
predict "$PRODUCTION_URL"

step "bad input is refused with 400"
python3 scripts/send_traffic.py --mode invalid --count 5 --rate 0 \
    --url "$PRODUCTION_URL" --expect 400

step "too many requests are refused with 429"
python3 scripts/send_traffic.py --mode burst --count 80 \
    --url "$PRODUCTION_URL" --expect 429

step "a model whose file does not match its checksum is not served"
docker rm -f "$CHECKSUM_DEMO" >/dev/null 2>&1 || true
docker compose run -d --name "$CHECKSUM_DEMO" --publish 8009:8000 \
    -e MODEL_VERSION="$second" \
    -e MODEL_SHA256=0000000000000000000000000000000000000000000000000000000000000000 \
    inference-staging >>"$TOOL_LOG" 2>&1
for _ in $(seq 20); do
    curl -fsS -o /dev/null "$CHECKSUM_DEMO_URL/health/live" 2>/dev/null && break
    sleep 2
done
echo "GET /health/ready -> $(curl -s -o "$WORK_DIR/ready.json" \
    -w '%{http_code}' "$CHECKSUM_DEMO_URL/health/ready") $(cat "$WORK_DIR/ready.json")"
docker logs "$CHECKSUM_DEMO" 2>&1 | grep '"event": "checksum_mismatch"' | head -1
docker rm -f "$CHECKSUM_DEMO" >/dev/null

step "send normal traffic to staging"
python3 scripts/send_traffic.py --mode normal --count "$TRAFFIC_ROWS" --rate "$TRAFFIC_RATE" \
    --url "$STAGING_URL" --save-csv "$WORK_DIR/normal.csv" --expect 200

step "the drift job sees no drift in it"
# In the cluster the job reads these rows back from Loki. There is no Loki on
# a laptop, so it gets the very same rows as a CSV file.
tool -v "$WORK_DIR:/work:ro" drift-monitor --current-csv /work/normal.csv |
    grep '"event": "drift_checked"'

step "send traffic with three features moved"
python3 scripts/send_traffic.py --mode drift --count "$TRAFFIC_ROWS" --rate "$TRAFFIC_RATE" \
    --url "$STAGING_URL" --save-csv "$WORK_DIR/drift.csv" --expect 200

step "the drift job finds it"
tool -v "$WORK_DIR:/work:ro" drift-monitor --current-csv /work/drift.csv |
    grep '"event": "drift_checked"'

step "the numbers the drift job pushed"
curl -fsS "$PUSHGATEWAY_URL/metrics" | grep '^data_drift'

step "done"
echo "MLflow UI: $MLFLOW_URL"
echo "staging:    $STAGING_URL/info"
echo "production: $PRODUCTION_URL/info"
