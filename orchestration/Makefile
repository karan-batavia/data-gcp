# orchestration/Makefile

SHELL        := /bin/bash
.DEFAULT_GOAL := help
REPO_ROOT    := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)


.PHONY: help cluster cluster-down airflow airflow-reset airflow-stop helm-upgrade \
        build-base build-jobs build-job \
        dags-pvc logs-pvc cluster-addons \
        logs-scheduler logs-webserver logs-worker open \
        nodes-metrics pods-metrics \
        _check-kind _check-helm _check-docker

# ── Local overrides ───────────────────────────────────────────────────────────
# .env.build  — Makefile/Docker build vars (REGISTRY, TAG, NETWORK_MODE...)
# Never injected into pods.
-include .env.build
-include .env.secrets
export

# Guard against empty NETWORK_MODE
NETWORK_MODE := $(or $(strip $(NETWORK_MODE)),default)

# ── Config ────────────────────────────────────────────────────────────────────
REGISTRY           ?= localhost:5001
TAG                ?= dev
KIND_CLUSTER       ?= airflow
NAMESPACE          := airflow
HELM_RELEASE       := airflow
HELM_CHART         := apache-airflow/airflow
HELM_CHART_VERSION := 1.16.0
HELM_VALUES_BASE   := ""
HELM_VALUES_LOCAL  := helm/values-local.yaml
HELM_VALUES_FLAGS  := --values $(HELM_VALUES_LOCAL)
ifneq ($(HELM_VALUES_BASE),"")
  HELM_VALUES_FLAGS := --values $(HELM_VALUES_BASE) $(HELM_VALUES_FLAGS)
endif
KUBE_CONTEXT := kind-$(KIND_CLUSTER)
KUBECTL      := kubectl --context $(KUBE_CONTEXT)

DAGS_DIR          := $(abspath ./dags)
JOBS_DIR          := $(abspath ../jobs)
LOGS_DIR          := $(abspath ./airflow/logs)
GCLOUD_CONFIG     := $(HOME)/.config/gcloud

# ── Help ──────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "  Cluster"
	@echo "  ──────────────────────────────────────────────────────"
	@echo "  make cluster                  Create KinD cluster + local registry"
	@echo "  make cluster-down             Destroy cluster + registry (full teardown)"
	@echo "  make cluster-addons           Install metrics-server"
	@echo ""
	@echo "  Airflow"
	@echo "  ──────────────────────────────────────────────────────"
	@echo "  make airflow                  Build image + helm install/upgrade (idempotent)"
	@echo "  make helm-upgrade             Helm upgrade only (no image rebuild)"
	@echo "  make airflow-reset            Uninstall + reinstall Airflow (keeps cluster)"
	@echo "  make airflow-stop             Helm uninstall only (keeps cluster + images)"
	@echo ""
	@echo "  Images"
	@echo "  ──────────────────────────────────────────────────────"
	@echo "  make build-base               Build + push airflow-base to local registry"
	@echo "  make build-jobs               Build + push all job images"
	@echo "  make build-job JOB=etl_jobs/external/tiktok"
	@echo "                                Build + push a single job image"
	@echo ""
	@echo "  Metrics"
	@echo "  ──────────────────────────────────────────────────────"
	@echo "  make nodes-metrics            Node + pod memory usage"
	@echo "  make pods-metrics             Pod + container + requests/limits"
	@echo ""
	@echo "  Logs"
	@echo "  ──────────────────────────────────────────────────────"
	@echo "  make logs-scheduler"
	@echo "  make logs-webserver"
	@echo "  make logs-worker"
	@echo "  make open                     Port-forward + open Airflow UI in browser"
	@echo ""

# ── Cluster ───────────────────────────────────────────────────────────────────

kind_cluster: _check-kind _check-docker
	@echo "▶ Starting local registry..."
	@if [ "$$(docker inspect -f '{{.State.Running}}' kind-registry 2>/dev/null)" != "true" ]; then \
	  docker run -d --restart=always \
	    -p "127.0.0.1:5001:5000" \
	    --network bridge \
	    --name kind-registry \
	    registry:2; \
	  echo "  ✓ Registry started on localhost:5001"; \
	else \
	  echo "  ✓ Registry already running"; \
	fi

	@echo "▶ Creating KinD cluster '$(KIND_CLUSTER)'..."
	@if kind get clusters 2>/dev/null | grep -q "^$(KIND_CLUSTER)$$"; then \
	  echo "  ✓ Cluster '$(KIND_CLUSTER)' already exists — skipping"; \
	else \
	  DAGS_PATH=$(DAGS_DIR) \
	  JOBS_ROOT=$(JOBS_DIR) \
	  GCLOUD_CONFIG=$(GCLOUD_CONFIG) \
	  LOGS_PATH=$(LOGS_DIR) \
	    envsubst < kind-config.yaml | \
	    kind create cluster --name $(KIND_CLUSTER) --config -; \
	fi

	@echo "▶ Exporting kubeconfig..."
	@kind export kubeconfig --name $(KIND_CLUSTER)
	@echo "  ✓ kubeconfig updated — context: kind-$(KIND_CLUSTER)"

	@echo "▶ Connecting registry to KinD network..."
	@docker network connect kind kind-registry 2>/dev/null || true
	@echo "  ✓ Registry connected"

	@echo "▶ Registering local registry with cluster..."
	@$(KUBECTL) apply -f k8s/registry-configmap.yaml
	@echo "  ✓ Registry registered"

	@echo ""
	@echo "  ✅ Cluster ready."
	@echo "     Verify:  kubectl --context kind-$(KIND_CLUSTER) get nodes"
	@echo "     Next:    make cluster-addons"

cluster-addons:
	@echo "▶ Installing metrics-server..."
	@$(KUBECTL) apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
	@$(KUBECTL) patch deployment metrics-server \
	  -n kube-system \
	  --type=json \
	  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
	@$(KUBECTL) rollout status deployment/metrics-server -n kube-system --timeout=90s
	@echo "  ✓ metrics-server ready"

cluster: kind_cluster cluster-addons
	@echo ""
	@echo "  ✅ Cluster and addons ready."
	@echo "     Next: make airflow"

cluster-down: _check-kind
	@echo "▶ Deleting KinD cluster '$(KIND_CLUSTER)'..."
	@kind delete cluster --name $(KIND_CLUSTER) 2>/dev/null \
	  && echo "  ✓ Cluster deleted" \
	  || echo "  ✓ Cluster was not running"

	@echo "▶ Stopping local registry..."
	@docker stop kind-registry 2>/dev/null || true
	@docker rm   kind-registry 2>/dev/null || true
	@echo "  ✓ Registry stopped"
	@echo ""
	@echo "  ✅ Full teardown complete."
	@echo "     Note: Docker images are still cached locally — no rebuild needed."

# ── Metrics ───────────────────────────────────────────────────────────────────

nodes-metrics:
	@echo "▶ Node metrics..."
	@$(KUBECTL) top nodes
	@echo ""
	@echo "▶ Pod metrics (namespace: $(NAMESPACE))..."
	@$(KUBECTL) top pods -n $(NAMESPACE) --sort-by=memory

pods-metrics:
	@echo "▶ Pod metrics (namespace: $(NAMESPACE))..."
	@$(KUBECTL) top pods -n $(NAMESPACE) --sort-by=memory
	@echo ""
	@echo "▶ Container metrics (namespace: $(NAMESPACE))..."
	@$(KUBECTL) top pods -n $(NAMESPACE) --containers --sort-by=memory
	@echo ""
	@echo "▶ Pod resource requests/limits..."
	@$(KUBECTL) get pods -n $(NAMESPACE) -o custom-columns=\
"NAME:.metadata.name,\
CPU_REQ:.spec.containers[*].resources.requests.cpu,\
CPU_LIM:.spec.containers[*].resources.limits.cpu,\
MEM_REQ:.spec.containers[*].resources.requests.memory,\
MEM_LIM:.spec.containers[*].resources.limits.memory"

# ── Airflow ───────────────────────────────────────────────────────────────────

airflow-env:
	@echo "▶ Applying Airflow ConfigMap..."
	@$(KUBECTL) create namespace $(NAMESPACE) 2>/dev/null || true
	@$(KUBECTL) apply -f k8s/airflow-variables.yaml
	@echo "  ✓ ConfigMap applied"
	@echo "▶ Creating Airflow secrets..."
	@$(KUBECTL) delete secret airflow-env-secrets -n $(NAMESPACE) 2>/dev/null || true
	@$(KUBECTL) create secret generic airflow-env-secrets \
	  --from-env-file=.env.secrets \
	  --namespace $(NAMESPACE)
	@$(KUBECTL) delete secret airflow-env-local -n $(NAMESPACE) 2>/dev/null || true
	@envsubst < .env.local > /tmp/.env.local.expanded
	@$(KUBECTL) create secret generic airflow-env-local \
	  --from-env-file=/tmp/.env.local.expanded \
	  --namespace $(NAMESPACE)
	@rm -f /tmp/.env.local.expanded
	@echo "  ✓ Secrets created"

airflow: _check-helm dags-pvc logs-pvc build-base airflow-env
	@echo "▶ Adding Airflow Helm repo..."
	@helm repo add apache-airflow https://airflow.apache.org 2>/dev/null || true
	@helm repo update apache-airflow
	@echo "▶ Creating namespace '$(NAMESPACE)'..."
	@$(KUBECTL) create namespace $(NAMESPACE) 2>/dev/null || true
	@echo "▶ Installing/upgrading Airflow..."
	@EXPANDED_VALUES=$$(mktemp) && \
	  envsubst < helm/values-local.yaml > $$EXPANDED_VALUES && \
	  helm upgrade --install $(HELM_RELEASE) $(HELM_CHART) \
	    --version $(HELM_CHART_VERSION) \
	    --namespace $(NAMESPACE) \
	    --values $$EXPANDED_VALUES \
	    --kube-context $(KUBE_CONTEXT) \
	    --cleanup-on-fail \
	    --timeout 3m \
	    --wait \
	    --wait-for-jobs; \
	  rm -f $$EXPANDED_VALUES
	@echo ""
	@echo "  ✅ Airflow is up."
	@echo "     UI:        make open    (admin / admin)"
	@echo "     Scheduler: make logs-scheduler"
	@echo "     Worker:    make logs-worker"

helm-upgrade: _check-helm airflow-env
	@echo "▶ Upgrading Airflow Helm release..."
	@EXPANDED_VALUES=$$(mktemp) && \
	  envsubst < helm/values-local.yaml > $$EXPANDED_VALUES && \
	  helm upgrade --install $(HELM_RELEASE) $(HELM_CHART) \
	    --version $(HELM_CHART_VERSION) \
	    --namespace $(NAMESPACE) \
	    --values $$EXPANDED_VALUES \
	    --kube-context $(KUBE_CONTEXT) \
	    --cleanup-on-fail \
	    --timeout 10m \
	    --wait \
	    --wait-for-jobs; \
	  rm -f $$EXPANDED_VALUES
	@echo "  ✓ Done"

airflow-reset: _check-helm
	@echo "▶ Uninstalling Airflow helm release..."
	@helm uninstall $(HELM_RELEASE) --namespace $(NAMESPACE) \
	  --kube-context $(KUBE_CONTEXT) 2>/dev/null || true
	@echo "▶ Force deleting all pods..."
	@$(KUBECTL) delete pod --all -n $(NAMESPACE) --force --grace-period=0 2>/dev/null || true
	@echo "▶ Deleting PVCs..."
	@$(KUBECTL) delete pvc --all -n $(NAMESPACE) --force --grace-period=0 2>/dev/null || true
	@echo "▶ Deleting Helm state secrets..."
	@$(KUBECTL) delete secret -n $(NAMESPACE) -l owner=helm --force --grace-period=0 2>/dev/null || true
	@echo "▶ Waiting for pods to be gone..."
	@$(KUBECTL) wait pod --all -n $(NAMESPACE) \
	  --for=delete --timeout=30s 2>/dev/null || true
	@echo "  ✓ Clean"
	@$(MAKE) airflow
	@echo "  ✅ Reset complete."

airflow-stop: _check-helm
	@echo "▶ Uninstalling Airflow release '$(HELM_RELEASE)'..."
	@helm uninstall $(HELM_RELEASE) --namespace $(NAMESPACE) \
	  --kube-context $(KUBE_CONTEXT) 2>/dev/null \
	  && echo "  ✓ Airflow uninstalled" \
	  || echo "  ✓ Airflow was not installed"
	@echo "▶ Force deleting remaining pods..."
	@$(KUBECTL) delete pod --all -n $(NAMESPACE) --force 2>/dev/null || true
	@echo "  Cluster and images are still alive."
	@echo "  Run 'make airflow' to reinstall."

# ── Images ────────────────────────────────────────────────────────────────────

build-base:
	@echo "▶ Building airflow-base:$(TAG)..."
	docker build \
	  $(if $(NETWORK_MODE),--build-arg NETWORK_MODE=$(NETWORK_MODE),) \
	  -f airflow/Dockerfile \
	  -t $(REGISTRY)/airflow-base:$(TAG) \
	  $(REPO_ROOT)
	@echo "▶ Pushing to local registry..."
	docker push $(REGISTRY)/airflow-base:$(TAG)
	@echo "  ✓ $(REGISTRY)/airflow-base:$(TAG)"

build-jobs:
	@echo "▶ Building all job images..."
	REGISTRY=$(REGISTRY) TAG=$(TAG) \
	  bash scripts/build_jobs.sh

build-job:
	@[ -n "$(JOB)" ] || \
	  { echo "❌  JOB is required."; \
	    echo "    Usage: make build-job JOB=etl_jobs/external/tiktok"; exit 1; }
	REGISTRY=$(REGISTRY) TAG=$(TAG) \
	  bash scripts/build_jobs.sh $(JOB)

# ── PVCs ──────────────────────────────────────────────────────────────────────

dags-pvc:
	@echo "▶ Applying DAGs PVC..."
	@$(KUBECTL) create namespace $(NAMESPACE) 2>/dev/null || true
	@$(KUBECTL) patch pv airflow-dags-pv --type=json \
	  -p='[{"op":"remove","path":"/spec/claimRef"}]' 2>/dev/null || true
	@DAGS_PATH=$(DAGS_DIR) envsubst < k8s/dags-pvc.yaml | \
	  $(KUBECTL) apply -f -
	@echo "▶ Waiting for DAGs PVC to bind..."
	@$(KUBECTL) wait pvc/airflow-dags-pvc -n $(NAMESPACE) \
	  --for=jsonpath='{.status.phase}'=Bound --timeout=30s \
	  || { echo "❌ DAGs PVC failed to bind — check PV"; exit 1; }
	@echo "  ✓ DAGs PVC ready"

logs-pvc:
	@echo "▶ Applying logs PVC..."
	@$(KUBECTL) create namespace $(NAMESPACE) 2>/dev/null || true
	@$(KUBECTL) patch pv airflow-logs-pv --type=json \
	  -p='[{"op":"remove","path":"/spec/claimRef"}]' 2>/dev/null || true
	@$(KUBECTL) apply -f k8s/logs-pvc.yaml
	@echo "▶ Waiting for logs PVC to bind..."
	@$(KUBECTL) wait pvc/airflow-logs -n $(NAMESPACE) \
	  --for=jsonpath='{.status.phase}'=Bound --timeout=30s \
	  || { echo "❌ Logs PVC failed to bind — check PV"; exit 1; }
	@echo "  ✓ Logs PVC ready"

# ── Logs ──────────────────────────────────────────────────────────────────────

logs-scheduler:
	$(KUBECTL) logs -n $(NAMESPACE) -l component=scheduler \
	  -f --tail=100 --prefix

logs-webserver:
	$(KUBECTL) logs -n $(NAMESPACE) -l component=webserver \
	  -f --tail=100 --prefix

logs-worker:
	$(KUBECTL) logs -n $(NAMESPACE) -l component=worker \
	  -f --tail=100 --prefix

# ── Browser ───────────────────────────────────────────────────────────────────

open:
	@echo "▶ Port-forwarding Airflow UI → http://localhost:8080"
	@$(KUBECTL) port-forward svc/$(HELM_RELEASE)-webserver 8080:8080 \
	  -n $(NAMESPACE) &>/dev/null &
	@sleep 1
	@open http://localhost:8080 2>/dev/null \
	  || xdg-open http://localhost:8080 2>/dev/null \
	  || echo "  Open http://localhost:8080 manually"
	@echo "  Credentials: admin / admin"

# ── Guards ────────────────────────────────────────────────────────────────────

_check-kind:
	@command -v kind >/dev/null 2>&1 \
	  || { echo "❌  kind not found.  Install: brew install kind"; exit 1; }

_check-helm:
	@command -v helm >/dev/null 2>&1 \
	  || { echo "❌  helm not found.  Install: brew install helm"; exit 1; }

_check-docker:
	@command -v docker >/dev/null 2>&1 \
	  || { echo "❌  docker not found."; exit 1; }
	@docker info >/dev/null 2>&1 \
	  || { echo "❌  docker daemon not running."; exit 1; }