# Local dev — KinD cluster

Local development environment for the Airflow multi-executor setup.
Runs `CeleryExecutor + KubernetesExecutor` on a KinD cluster with a local image registry,
mirroring the GKE prod topology.

---

## Requirements

| Tool | Min version | Install |
|---|---|---|
| Docker Desktop | 4.x | https://docs.docker.com/desktop/ |
| kind | 0.20+ | `brew install kind` |
| kubectl | 1.27+ | `brew install kubectl` |
| helm | 3.12+ | `brew install helm` |
| uv | 0.4+ | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| envsubst | any | `brew install gettext && brew link gettext` |

Verify all tools are available:

```bash
docker info
kind version
kubectl version --client
helm version
uv --version
envsubst --version
```

---

## Repo structure (relevant to local dev)

```
.
├── jobs/                          # Isolated task code — each is a self-contained CLI app
│   └── etl_jobs/external/tiktok/
│       ├── main.py                # typer CLI (subcommands: extract, load, transform…)
│       ├── pyproject.toml         # [project.scripts] tiktok = "main:app"
│       └── uv.lock
├── orchestration/
│   ├── dags/                      # DAG files — hot-reloaded via hostPath PVC
│   ├── docker/
│   │   ├── base/                  # airflow-base image
│   │   ├── celery-worker/         # airflow-celery-worker image
│   │   └── templates/
│   │       └── job.Dockerfile     # shared template for all job images
│   ├── helm/
│   │   ├── values-base.yaml       # shared config (local + prod)
│   │   └── values-local.yaml      # local overrides (registry, PVC, node selectors)
│   ├── k8s/
│   │   └── dags-pvc.yaml          # hostPath PersistentVolume + PVC
│   ├── scripts/
│   │   └── build_jobs.sh          # image factory — auto-discovers and builds all jobs
│   ├── kind-config.yaml           # KinD cluster definition (rendered via envsubst)
│   ├── .env.local.kind.example    # local overrides template
│   └── Makefile                   # all dev commands
└── Makefile                       # root — delegates to orchestration/Makefile
```

---

## First-time setup

### 1. Clone and install dev tooling

```bash
git clone <repo>
cd <repo>
uv sync   # installs root dev tooling (ruff, mypy, pre-commit)
```

### 2. Optional — local overrides

If you need to override defaults (e.g. registry port 5001 is already taken):

```bash
cp orchestration/.env.local.kind.example orchestration/.env.local.kind
# edit as needed — this file is gitignored
```

Available overrides:

```bash
# orchestration/.env.local.kind
REGISTRY=localhost:5001    # change if port 5001 is taken on your machine
TAG=dev
KIND_CLUSTER=airflow       # change if you run multiple KinD clusters
```

### 3. Create the cluster

```bash
make cluster
```

This runs four steps, each idempotent:

1. Start `registry:2` container on `localhost:5001`
2. Create KinD cluster from `kind-config.yaml` (rendered via `envsubst` — paths are injected automatically)
3. Connect registry container to the KinD Docker network
4. Apply `local-registry-hosting` ConfigMap so KinD nodes can resolve `localhost:5001`

### 4. Verify the cluster

```bash
# All three nodes should be Ready
kubectl get nodes

# Verify labels
kubectl get nodes -l role=airflow-core          # → 1 node
kubectl get nodes -l role=airflow-kube-worker   # → 1 node

# Verify taint on kube-worker (keeps Airflow infra pods off it)
kubectl describe node -l role=airflow-kube-worker | grep -A3 Taints
# Expected: role=airflow-kube-worker:NoSchedule

# Verify registry mirror is configured on nodes
docker exec airflow-worker \
  cat /etc/containerd/config.toml | grep -A3 "localhost:5001"
```

Expected node layout:

```
NAME                    STATUS   ROLE
airflow-control-plane   Ready    control-plane
airflow-worker          Ready    <none>     ← role=airflow-core
airflow-worker2         Ready    <none>     ← role=airflow-kube-worker (tainted)
```

### 5. Install Airflow

```bash
make airflow
```

This runs in order:

1. `make dags-pvc` — applies the hostPath PVC pointing to `orchestration/dags/`
2. `make build-base` — builds `airflow-base` image
3. `make build-worker` — builds `airflow-celery-worker` image
4. `make kind-load-base` + `make kind-load-worker` — loads images into KinD nodes
5. `helm upgrade --install` with `values-base.yaml` + `values-local.yaml`

Airflow is ready when all pods are Running:

```bash
kubectl get pods -n airflow

# Expected pods:
# airflow-scheduler-*      Running   (on airflow-core node)
# airflow-webserver-*      Running   (on airflow-core node)
# airflow-worker-*         Running   (on airflow-core node)
# airflow-redis-*          Running   (on airflow-core node)
# airflow-postgresql-*     Running   (on airflow-core node)
```

Open the UI:

```bash
make open
# → http://localhost:8080   admin / admin
```

---

## Node topology

```
control-plane
└── k8s control plane only

airflow-core                        (label: role=airflow-core)
├── scheduler
├── webserver
├── celery-worker
├── redis
└── postgresql

airflow-kube-worker                 (label: role=airflow-kube-worker)
│                                   (taint: role=airflow-kube-worker:NoSchedule)
└── KubernetesExecutor task pods    (ephemeral — created per task, deleted on completion)
```

Task pods land on `airflow-kube-worker` because:
- They carry a matching `toleration` in the pod template
- They carry a matching `nodeSelector: role: airflow-kube-worker`

Airflow infrastructure pods land on `airflow-core` because:
- They carry `nodeSelector: role: airflow-core` in `values-local.yaml`
- They do not tolerate the `airflow-kube-worker` taint

---

## Executor routing

Tasks are routed by the `executor=` parameter on the operator — not by queue name.

```python
# Runs on CeleryExecutor (default — no parameter needed)
@task()
def standard_task():
    ...

# Runs on KubernetesExecutor — ephemeral pod, isolated image
KubernetesPodOperator(
    task_id="extract",
    executor="KubernetesExecutor",
    image=Variable.get("image_etl_external_tiktok", "localhost:5001/etl-external-tiktok:dev"),
    cmds=["tiktok"],
    arguments=["extract", "--date", "{{ ds }}"],
    is_delete_operator_pod=True,
    get_logs=True,
)
```

---

## Daily dev loops

### Fastest — iterate on job code without Docker

```bash
cd jobs/etl_jobs/external/tiktok
uv run tiktok extract --date 2024-01-01
uv run tiktok load --date 2024-01-01
```

No Docker, no Airflow, no restart. Test the CLI directly.

### Iterate on a job image

```bash
# From repo root or orchestration/
make build-job JOB=etl_jobs/external/tiktok

# Re-trigger the task in the Airflow UI — no Airflow restart needed.
# KubernetesExecutor pulls a fresh pod image on every task run.
```

### Iterate on DAG code

```bash
# Edit orchestration/dags/my_dag.py
# Change is immediately visible in the scheduler — no restart needed.
# The dags/ directory is mounted via hostPath PVC with hot reload.
```

### Iterate on Celery worker deps

```bash
make build-worker
kubectl rollout restart deployment/airflow-worker -n airflow
# Wait for the new pod to be Running before triggering tasks.
```

### Build all job images at once

```bash
make build-jobs
# Builds every job found under jobs/ and kind-loads them all.
```

---

## Cluster lifecycle

| Command | Effect | Keeps |
|---|---|---|
| `make cluster` | Create cluster + registry | — |
| `make airflow` | Helm install/upgrade | cluster, registry, images |
| `make airflow-stop` | Helm uninstall | cluster, registry, images |
| `make airflow-reset` | Uninstall → reinstall | cluster, registry, images |
| `make cluster-down` | Full teardown | Docker image cache on host |

`make airflow` is idempotent — safe to run whether Airflow is already installed or not.

After `make cluster-down`, Docker images are still cached locally.
Next `make cluster && make airflow` skips rebuilding unchanged layers — fast.

---

## Logs

```bash
make logs-scheduler    # tail scheduler logs (shows DAG parsing, task scheduling)
make logs-webserver    # tail webserver logs
make logs-worker       # tail celery worker logs (shows task execution)

# KubernetesExecutor task pod logs (ephemeral — grab while the pod is alive)
kubectl logs -n airflow -l component=worker --prefix -f

# Watch all pods
kubectl get pods -n airflow -w
```

---

## Troubleshooting

### Nodes not showing correct labels

Labels are set at cluster creation and cannot be patched. Full teardown required:

```bash
make cluster-down && make cluster
```

### ImagePullBackOff on task pods

Images must be kind-loaded before use. `pullPolicy: Never` is set in `values-local.yaml`
so Kubernetes never attempts to pull from the registry — it only uses what was loaded.

```bash
make build-job JOB=etl_jobs/external/tiktok
# then re-trigger the task
```

### DAGs not appearing in the UI

Check the PVC is bound and the scheduler can read the dags directory:

```bash
kubectl get pvc -n airflow
# airflow-dags-pvc should be Bound

kubectl exec -n airflow deploy/airflow-scheduler -- ls /opt/airflow/dags
# should list your dag files
```

If the PVC is Pending, the PV nodeAffinity may not match. Recreate:

```bash
kubectl delete pvc airflow-dags-pvc -n airflow
kubectl delete pv airflow-dags-pv
make dags-pvc
```

### Registry not reachable from KinD nodes

```bash
# Check registry is running
docker ps | grep kind-registry

# Check it is connected to the kind network
docker network inspect kind | grep kind-registry

# If missing, reconnect
docker network connect kind kind-registry
```

### Port 5001 already in use

Add to `orchestration/.env.local.kind`:

```bash
REGISTRY=localhost:5002
```

Then stop the existing registry and recreate:

```bash
make cluster-down && make cluster
```

### Taint not applied to kube-worker node

```bash
# Check
kubectl describe node -l role=airflow-kube-worker | grep Taints

# If missing, apply manually (one-off fix without cluster teardown)
kubectl taint nodes -l role=airflow-kube-worker \
  role=airflow-kube-worker:NoSchedule
```

---

## Environment variables

Shared infrastructure config is read from environment variables — no hardcoded values in Python.

| Variable | Used by | Set in |
|---|---|---|
| `GCP_PROJECT` | job code + DAGs | `values-local.yaml` env block / `.env` at repo root |
| `BUCKET_RAW` | job code + DAGs | same |
| `BUCKET_PROCESSED` | job code + DAGs | same |
| `REGISTRY` | Makefile | `.env.local.kind` (default: `localhost:5001`) |
| `TAG` | Makefile | `.env.local.kind` (default: `dev`) |
| `KIND_CLUSTER` | Makefile | `.env.local.kind` (default: `airflow`) |

Job code reads env vars directly — never imports from Airflow:

```python
# jobs/etl_jobs/external/tiktok/config.py
import os
GCP_PROJECT = os.environ["GCP_PROJECT"]
BUCKET_RAW  = os.environ["BUCKET_RAW"]
```

DAGs read image tags from Airflow Variables — the only value that differs between local and prod:

```python
# orchestration/dags/tiktok_dag.py
from airflow.models import Variable
TIKTOK_IMAGE = Variable.get(
    "image_etl_external_tiktok",
    default_var="localhost:5001/etl-external-tiktok:dev"
)
```

---

## Local vs prod delta

Exactly two things change between local and prod:

| | Local (KinD) | Prod (GKE) |
|---|---|---|
| Helm values | `values-local.yaml` | `values-prod.yaml` |
| Airflow Variables | `localhost:5001/...:dev` | `europe-docker.pkg.dev/...:sha` |

Everything else — DAG code, Dockerfiles, uv lockfiles, Helm chart structure, `executor=` routing — is identical.