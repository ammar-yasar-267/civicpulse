#!/usr/bin/env bash
# Bring up a local kind cluster running CivicPulse, from nothing.
#
#   scripts/k8s-up.sh          # dev overlay, locally built images
#   scripts/k8s-up.sh --vpa    # also install the VPA (adds ~1 min)
#
# This is the "second command puts it on a Kubernetes cluster" from §1.4. It installs the two
# things a bare cluster does not have but this deployment needs:
#
#   * an ingress controller — without it the Ingress object exists and routes nothing
#   * metrics-server        — without it the HPA reports <unknown>/60% forever
set -euo pipefail

CLUSTER="${CLUSTER:-civicpulse}"
OVERLAY="${OVERLAY:-dev}"
NS=civicpulse
WITH_VPA=false
[ "${1:-}" = "--vpa" ] && WITH_VPA=true

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

for tool in kind kubectl docker; do
    command -v "$tool" >/dev/null || { echo "missing required tool: $tool" >&2; exit 1; }
done

# ---------------------------------------------------------------- cluster --
if kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
    say "cluster '$CLUSTER' already exists, reusing it"
else
    say "creating kind cluster '$CLUSTER'"
    # extraPortMappings puts the ingress controller on localhost:80 so the stack is reachable at
    # http://civicpulse.local without a port-forward. The node labels are what the ingress-nginx
    # kind manifest selects on.
    cat <<EOF | kind create cluster --name "$CLUSTER" --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    image: kindest/node:v1.31.2
    kubeadmConfigPatches:
      - |
        kind: InitConfiguration
        nodeRegistration:
          kubeletExtraArgs:
            node-labels: "ingress-ready=true"
    extraPortMappings:
      - containerPort: 80
        hostPort: 80
        protocol: TCP
      - containerPort: 443
        hostPort: 443
        protocol: TCP
EOF
fi

kubectl config use-context "kind-${CLUSTER}" >/dev/null

# ------------------------------------------------------------ ingress ctl --
say "installing the ingress controller"
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.11.3/deploy/static/provider/kind/deploy.yaml
# rollout status, not `wait --for=condition=ready pod`: the latter fails with "no matching
# resources found" when it runs before the ReplicaSet has created the pod, which is a race you
# lose roughly half the time on a fresh cluster.
kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller --timeout=240s

# --------------------------------------------------------- metrics-server --
say "installing metrics-server (the HPA cannot work without it)"
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.7.2/components.yaml
# kind's kubelet uses a self-signed serving cert, which metrics-server rejects by default. Without
# this patch it never becomes ready and the HPA sits at <unknown> — the single most common cause of
# a "broken HPA".
kubectl -n kube-system patch deployment metrics-server --type=json \
    -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]' \
    >/dev/null 2>&1 || true
kubectl -n kube-system rollout status deployment/metrics-server --timeout=180s

# ------------------------------------------------------------------- VPA --
if $WITH_VPA; then
    say "installing the Vertical Pod Autoscaler (recommender mode)"
    tmp=$(mktemp -d)
    git clone --depth 1 -q https://github.com/kubernetes/autoscaler.git "$tmp/autoscaler"
    (cd "$tmp/autoscaler/vertical-pod-autoscaler" && ./hack/vpa-up.sh)
    rm -rf "$tmp"
fi

# ---------------------------------------------------------------- images --
say "building and loading images into the cluster"
docker build -q -t civicpulse-backend:dev  -f backend/Dockerfile  backend  >/dev/null
docker build -q -t civicpulse-frontend:dev -f frontend/Dockerfile frontend >/dev/null
# Loaded directly into the node, so no registry is involved for local work.
kind load docker-image --name "$CLUSTER" civicpulse-backend:dev civicpulse-frontend:dev

# --------------------------------------------------------------- secrets --
say "creating the namespace and secrets"
kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -
# Read from .env if present, otherwise generated. Never from a committed manifest.
if [ -f .env ]; then
    # shellcheck disable=SC1091
    set -a; . ./.env; set +a
fi
kubectl -n "$NS" create secret generic civicpulse-secrets \
    --from-literal=POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(openssl rand -hex 16)}" \
    --from-literal=GROQ_API_KEY="${GROQ_API_KEY:-}" \
    --dry-run=client -o yaml | kubectl apply -f -

# ---------------------------------------------------------------- deploy --
say "applying the $OVERLAY overlay"
kubectl apply -k "k8s/overlays/${OVERLAY}"

say "waiting for rollouts"
kubectl -n "$NS" rollout status statefulset/postgres --timeout=300s
kubectl -n "$NS" rollout status deployment/redis     --timeout=180s
kubectl -n "$NS" rollout status deployment/backend   --timeout=300s
kubectl -n "$NS" rollout status deployment/frontend  --timeout=180s

say "running migrations and seeding"
kubectl -n "$NS" exec deploy/backend -- alembic upgrade head
kubectl -n "$NS" exec deploy/backend -- python -m app.seed

say "cluster state"
kubectl -n "$NS" get deploy,statefulset,svc,ingress,hpa,pdb

cat <<'EOF'

Ready. The Ingress expects the host civicpulse.local, so either add it to /etc/hosts:

    echo '127.0.0.1 civicpulse.local' | sudo tee -a /etc/hosts

then open http://civicpulse.local/ — or skip that and use curl directly:

    curl -H 'Host: civicpulse.local' http://localhost/api/stats

Load test and watch the HPA scale out:

    scripts/load-test.sh

Tear down:

    kind delete cluster --name civicpulse
EOF
