#!/usr/bin/env bash
# Sends traffic to the prediction API from INSIDE the cluster.
#
# A port-forward is not enough for this: it connects to one single pod, so a
# canary would either get all of the traffic or none of it. A pod inside the
# cluster talks to the Service, and the Service spreads the requests over all
# pods, the old version and the new one.
#
# The pod is a plain python image that only sleeps. The traffic script and the
# dataset are copied into it, so no extra image has to be built. It is a test
# tool and not part of the platform, which is why it is not in the GitOps tree.
#
# Usage:
#   scripts/cluster_traffic.sh production --mode normal --count 3000 --rate 10
#   scripts/cluster_traffic.sh staging    --mode drift  --count 600  --rate 20
#   scripts/cluster_traffic.sh clean
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
namespace="default"
pod="traffic-generator"
image="python:3.13-slim"

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <staging|production|clean> [send_traffic.py options]" >&2
  exit 2
fi

target="$1"
shift

if [[ "$target" == "clean" ]]; then
  kubectl -n "$namespace" delete pod "$pod" --ignore-not-found
  exit 0
fi

if [[ "$target" != "staging" && "$target" != "production" ]]; then
  echo "the first argument must be staging, production or clean" >&2
  exit 2
fi

if ! kubectl -n "$namespace" get pod "$pod" >/dev/null 2>&1; then
  kubectl -n "$namespace" run "$pod" --image="$image" --restart=Never \
    --labels="app.kubernetes.io/name=traffic-generator" \
    --command -- sleep 14400 >/dev/null
fi
kubectl -n "$namespace" wait --for=condition=Ready "pod/$pod" --timeout=120s >/dev/null

kubectl -n "$namespace" cp "$here/send_traffic.py" "$pod:/tmp/send_traffic.py" >/dev/null
kubectl -n "$namespace" cp "$here/../data/california_housing.csv" "$pod:/tmp/california_housing.csv" >/dev/null

kubectl -n "$namespace" exec "$pod" -- python /tmp/send_traffic.py \
  --url "http://inference.${target}.svc.cluster.local" \
  --data /tmp/california_housing.csv "$@"
