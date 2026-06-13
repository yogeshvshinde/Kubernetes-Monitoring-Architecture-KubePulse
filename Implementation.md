Below is a clean phase-wise version of project, converted into a practical MVP architecture.

The project name is KubePulse.

RKE2 Kubernetes Cluster
        |
        v
Python Health Check Service
        |
        v
Streamlit Dashboard

The key design decision: Streamlit should not directly talk to Kubernetes. Instead, Streamlit talks to a Python health-check API. That keeps the dashboard clean, secure, and easier to extend later.

Phase 1: RKE2 Kubernetes Installation and Cluster Validation
Goal

Install an RKE2 Kubernetes cluster and verify that Kubernetes is healthy before building your own services on top of it.

RKE2’s official quickstart installs the rke2-server service using the installer script, then enables and starts the systemd service. The RKE2 kubeconfig is stored at /etc/rancher/rke2/rke2.yaml.

1.1 Recommended Machine Layout

For MVP:

Node	Purpose
rke2-server-1	Control plane + etcd
rke2-worker-1	Worker node
rke2-worker-2	Optional worker node

For first development, you can also start with one single node.

1.2 Install RKE2 Server Node

Run on the control-plane node.

sudo mkdir -p /etc/rancher/rke2

Create config:

cat <<EOF | sudo tee /etc/rancher/rke2/config.yaml
write-kubeconfig-mode: "0644"
node-name: rke2-server-1
tls-san:
  - <CONTROL_PLANE_IP>
EOF

Install RKE2:

curl -sfL https://get.rke2.io | sudo sh -

Enable and start:

sudo systemctl enable rke2-server.service
sudo systemctl start rke2-server.service

Check logs:

sudo journalctl -u rke2-server -f

Configure kubectl access:

export KUBECONFIG=/etc/rancher/rke2/rke2.yaml
export PATH=$PATH:/var/lib/rancher/rke2/bin

Check cluster:

kubectl get nodes -o wide
kubectl get pods -A
kubectl get componentstatuses
1.3 Add Worker Node

Get the server token from the control-plane node:

sudo cat /var/lib/rancher/rke2/server/node-token

On the worker node:

curl -sfL https://get.rke2.io | INSTALL_RKE2_TYPE="agent" sudo sh -

Create worker config:

sudo mkdir -p /etc/rancher/rke2

cat <<EOF | sudo tee /etc/rancher/rke2/config.yaml
server: https://<CONTROL_PLANE_IP>:9345
token: <SERVER_NODE_TOKEN>
node-name: rke2-worker-1
EOF

Start worker:

sudo systemctl enable rke2-agent.service
sudo systemctl start rke2-agent.service

Back on the server:

kubectl get nodes -o wide

Expected result:

rke2-server-1   Ready
rke2-worker-1   Ready
1.4 Cluster Health Validation Checklist

Run these commands before moving to Phase 2.

kubectl get nodes
kubectl get pods -A
kubectl get namespaces
kubectl get deployments -A
kubectl get services -A
kubectl get events -A --sort-by=.lastTimestamp

You should confirm:

All nodes are Ready
CoreDNS pods are Running
No system pods are CrashLoopBackOff
No worker node is NotReady
Kubernetes API is reachable
kubectl commands are working
Phase 2: Python Health Check Service
Goal

Build a Python service that connects to Kubernetes standard APIs and returns health information for:

Nodes
Pods
Deployments
Services
PVCs
Warning events
Namespaces

This service uses the official Kubernetes Python client library.

2.1 Health Check Service Responsibilities

The service will expose these APIs:

API	Purpose
/healthz	Health check for the service itself
/api/namespaces	List namespaces
/api/cluster/health	Full cluster health
/api/cluster/health?namespace=default	Namespace-specific health
2.2 Project Structure
kubepulse/
  health-service/
    main.py
    requirements.txt
    Dockerfile
    k8s/
      rbac.yaml
      deployment.yaml

  dashboard/
    app.py
    requirements.txt
2.3 health-service/requirements.txt
fastapi==0.115.6
uvicorn[standard]==0.34.0
kubernetes==32.0.1
2.4 health-service/main.py
import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from kubernetes import client, config
from kubernetes.client.rest import ApiException


CRITICAL_WAITING_REASONS = {
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "CreateContainerConfigError",
    "CreateContainerError",
    "RunContainerError",
}

WARNING_WAITING_REASONS = {
    "ContainerCreating",
    "PodInitializing",
}


app = FastAPI(
    title="KubePulse Health Service",
    description="Reads Kubernetes standard APIs and returns cluster/application health.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_kubernetes_config() -> None:
    """
    Load in-cluster config when running inside Kubernetes.
    Fall back to local kubeconfig for development.
    """
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config(config_file=os.getenv("KUBECONFIG"))


@lru_cache(maxsize=1)
def k8s_clients() -> Dict[str, Any]:
    load_kubernetes_config()
    return {
        "core": client.CoreV1Api(),
        "apps": client.AppsV1Api(),
        "discovery": client.DiscoveryV1Api(),
    }


def safe_name(obj: Any) -> str:
    return getattr(getattr(obj, "metadata", None), "name", "")


def safe_namespace(obj: Any) -> str:
    return getattr(getattr(obj, "metadata", None), "namespace", "cluster")


def status_priority(status: str) -> int:
    return {
        "healthy": 0,
        "warning": 1,
        "unknown": 1,
        "critical": 2,
    }.get(status, 1)


def rollup_status(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "unknown"

    worst = max(status_priority(item.get("status", "unknown")) for item in items)

    if worst == 2:
        return "critical"
    if worst == 1:
        return "warning"
    return "healthy"


def count_by_status(items: List[Dict[str, Any]]) -> Dict[str, int]:
    result = {"healthy": 0, "warning": 0, "critical": 0, "unknown": 0}

    for item in items:
        status = item.get("status", "unknown")
        result[status] = result.get(status, 0) + 1

    return result


def node_health() -> List[Dict[str, Any]]:
    core = k8s_clients()["core"]
    nodes = core.list_node().items
    results = []

    for node in nodes:
        conditions = {c.type: c.status for c in node.status.conditions or []}
        ready = conditions.get("Ready") == "True"

        pressure_reasons = []

        for pressure in ["MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable"]:
            if conditions.get(pressure) == "True":
                pressure_reasons.append(pressure)

        if not ready:
            status = "critical"
            reason = "Node is NotReady"
        elif pressure_reasons:
            status = "warning"
            reason = f"Node has pressure: {', '.join(pressure_reasons)}"
        else:
            status = "healthy"
            reason = "Node is Ready"

        results.append(
            {
                "name": safe_name(node),
                "namespace": "cluster",
                "status": status,
                "reason": reason,
                "kubelet_version": getattr(node.status.node_info, "kubelet_version", None),
                "os_image": getattr(node.status.node_info, "os_image", None),
                "internal_ip": next(
                    (addr.address for addr in node.status.addresses or [] if addr.type == "InternalIP"),
                    None,
                ),
            }
        )

    return results


def pod_health(namespace: Optional[str] = None) -> List[Dict[str, Any]]:
    core = k8s_clients()["core"]

    if namespace:
        pods = core.list_namespaced_pod(namespace=namespace).items
    else:
        pods = core.list_pod_for_all_namespaces().items

    results = []

    for pod in pods:
        reasons = []
        status = "healthy"
        phase = pod.status.phase or "Unknown"
        restart_count = 0
        ready_containers = 0
        total_containers = len(pod.status.container_statuses or [])

        if phase in {"Failed", "Unknown"}:
            status = "critical"
            reasons.append(f"Pod phase is {phase}")
        elif phase == "Pending":
            status = "warning"
            reasons.append("Pod is Pending")

        for cs in pod.status.container_statuses or []:
            restart_count += cs.restart_count or 0

            if cs.ready:
                ready_containers += 1

            waiting = getattr(cs.state, "waiting", None)
            terminated = getattr(cs.state, "terminated", None)

            if waiting:
                waiting_reason = waiting.reason or "Waiting"
                reasons.append(f"{cs.name}: {waiting_reason}")

                if waiting_reason in CRITICAL_WAITING_REASONS:
                    status = "critical"
                elif status != "critical":
                    status = "warning"

            if terminated and terminated.exit_code not in (0, None):
                reasons.append(f"{cs.name}: terminated exit code {terminated.exit_code}")

                if status != "critical":
                    status = "warning"

        if restart_count >= 5 and status != "critical":
            status = "warning"
            reasons.append(f"High restart count: {restart_count}")

        ready_condition = next(
            (condition.status for condition in pod.status.conditions or [] if condition.type == "Ready"),
            None,
        )

        if phase == "Running" and ready_condition != "True":
            if status != "critical":
                status = "warning"
            reasons.append("Pod is running but not Ready")

        if not reasons:
            reasons.append("Pod is healthy")

        results.append(
            {
                "name": safe_name(pod),
                "namespace": safe_namespace(pod),
                "status": status,
                "reason": "; ".join(reasons),
                "phase": phase,
                "node": pod.spec.node_name,
                "pod_ip": pod.status.pod_ip,
                "ready_containers": f"{ready_containers}/{total_containers}",
                "restart_count": restart_count,
                "created_at": pod.metadata.creation_timestamp.isoformat()
                if pod.metadata.creation_timestamp
                else None,
            }
        )

    return results


def deployment_health(namespace: Optional[str] = None) -> List[Dict[str, Any]]:
    apps = k8s_clients()["apps"]

    if namespace:
        deployments = apps.list_namespaced_deployment(namespace=namespace).items
    else:
        deployments = apps.list_deployment_for_all_namespaces().items

    results = []

    for dep in deployments:
        desired = dep.spec.replicas or 0
        available = dep.status.available_replicas or 0
        ready = dep.status.ready_replicas or 0
        updated = dep.status.updated_replicas or 0

        if desired == 0:
            status = "warning"
            reason = "Deployment is scaled to zero"
        elif available == 0:
            status = "critical"
            reason = f"No replicas available. desired={desired}, available={available}"
        elif available < desired:
            status = "warning"
            reason = f"Replica mismatch. desired={desired}, available={available}"
        elif updated < desired:
            status = "warning"
            reason = f"Rollout may be incomplete. desired={desired}, updated={updated}"
        else:
            status = "healthy"
            reason = "Deployment replicas are available"

        results.append(
            {
                "name": safe_name(dep),
                "namespace": safe_namespace(dep),
                "status": status,
                "reason": reason,
                "desired": desired,
                "ready": ready,
                "available": available,
                "updated": updated,
            }
        )

    return results


def service_has_ready_endpoints(namespace: str, service_name: str) -> Optional[bool]:
    """
    Returns:
      True  -> service has at least one ready endpoint
      False -> service is expected to have endpoints but has none
      None  -> endpoint check not available
    """
    clients = k8s_clients()
    discovery = clients["discovery"]
    core = clients["core"]

    try:
        slices = discovery.list_namespaced_endpoint_slice(
            namespace=namespace,
            label_selector=f"kubernetes.io/service-name={service_name}",
        ).items

        for slice_obj in slices:
            for endpoint in slice_obj.endpoints or []:
                conditions = endpoint.conditions
                ready = getattr(conditions, "ready", None)

                if ready is True or ready is None:
                    return True

        if slices:
            return False

    except ApiException:
        pass

    try:
        endpoints = core.read_namespaced_endpoints(name=service_name, namespace=namespace)

        for subset in endpoints.subsets or []:
            if subset.addresses:
                return True

        return False

    except ApiException:
        return None


def service_health(namespace: Optional[str] = None) -> List[Dict[str, Any]]:
    core = k8s_clients()["core"]

    if namespace:
        services = core.list_namespaced_service(namespace=namespace).items
    else:
        services = core.list_service_for_all_namespaces().items

    results = []

    for svc in services:
        svc_type = svc.spec.type
        has_selector = bool(svc.spec.selector)

        if svc_type == "ExternalName":
            status = "healthy"
            reason = "ExternalName service"
            endpoints_ok = None
        elif not has_selector:
            status = "unknown"
            reason = "Service has no selector; skipping endpoint check"
            endpoints_ok = None
        else:
            endpoints_ok = service_has_ready_endpoints(safe_namespace(svc), safe_name(svc))

            if endpoints_ok is True:
                status = "healthy"
                reason = "Service has ready endpoints"
            elif endpoints_ok is False:
                status = "critical"
                reason = "Service has no ready endpoints"
            else:
                status = "unknown"
                reason = "Could not verify service endpoints"

        ports = []

        for port in svc.spec.ports or []:
            ports.append(f"{port.port}->{port.target_port}/{port.protocol}")

        results.append(
            {
                "name": safe_name(svc),
                "namespace": safe_namespace(svc),
                "status": status,
                "reason": reason,
                "type": svc_type,
                "cluster_ip": svc.spec.cluster_ip,
                "ports": ", ".join(ports),
                "endpoints_ready": endpoints_ok,
            }
        )

    return results


def pvc_health(namespace: Optional[str] = None) -> List[Dict[str, Any]]:
    core = k8s_clients()["core"]

    if namespace:
        pvcs = core.list_namespaced_persistent_volume_claim(namespace=namespace).items
    else:
        pvcs = core.list_persistent_volume_claim_for_all_namespaces().items

    results = []

    for pvc in pvcs:
        phase = pvc.status.phase or "Unknown"

        if phase == "Bound":
            status = "healthy"
            reason = "PVC is Bound"
        elif phase == "Pending":
            status = "warning"
            reason = "PVC is Pending"
        else:
            status = "critical"
            reason = f"PVC phase is {phase}"

        results.append(
            {
                "name": safe_name(pvc),
                "namespace": safe_namespace(pvc),
                "status": status,
                "reason": reason,
                "phase": phase,
                "storage_class": pvc.spec.storage_class_name,
                "volume": pvc.spec.volume_name,
            }
        )

    return results


def warning_events(namespace: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    core = k8s_clients()["core"]

    try:
        if namespace:
            events = core.list_namespaced_event(
                namespace=namespace,
                field_selector="type=Warning",
            ).items
        else:
            events = core.list_event_for_all_namespaces(
                field_selector="type=Warning",
            ).items

    except ApiException:
        return []

    def event_time(event: Any):
        return (
            event.last_timestamp
            or event.event_time
            or event.first_timestamp
            or event.metadata.creation_timestamp
            or datetime.min.replace(tzinfo=timezone.utc)
        )

    events = sorted(events, key=event_time, reverse=True)[:limit]

    return [
        {
            "namespace": safe_namespace(event),
            "involved_object": f"{event.involved_object.kind}/{event.involved_object.name}",
            "reason": event.reason,
            "message": event.message,
            "count": event.count,
            "last_seen": event_time(event).isoformat() if event_time(event) else None,
        }
        for event in events
    ]


@app.get("/healthz")
def healthz() -> Dict[str, str]:
    return {"status": "ok", "time": utc_now()}


@app.get("/api/namespaces")
def namespaces() -> Dict[str, Any]:
    core = k8s_clients()["core"]
    items = core.list_namespace().items

    return {
        "generated_at": utc_now(),
        "namespaces": sorted([ns.metadata.name for ns in items]),
    }


@app.get("/api/cluster/health")
def cluster_health(namespace: Optional[str] = Query(default=None)) -> Dict[str, Any]:
    nodes = node_health()
    pods = pod_health(namespace)
    deployments = deployment_health(namespace)
    services = service_health(namespace)
    pvcs = pvc_health(namespace)
    events = warning_events(namespace)

    all_items = nodes + pods + deployments + services + pvcs
    overall = rollup_status(all_items)

    return {
        "generated_at": utc_now(),
        "namespace": namespace or "all",
        "summary": {
            "overall_status": overall,
            "nodes": count_by_status(nodes),
            "pods": count_by_status(pods),
            "deployments": count_by_status(deployments),
            "services": count_by_status(services),
            "pvcs": count_by_status(pvcs),
            "totals": {
                "nodes": len(nodes),
                "pods": len(pods),
                "deployments": len(deployments),
                "services": len(services),
                "pvcs": len(pvcs),
                "warning_events": len(events),
            },
        },
        "nodes": nodes,
        "pods": pods,
        "deployments": deployments,
        "services": services,
        "pvcs": pvcs,
        "warning_events": events,
    }
2.5 Run Health Service Locally
cd kubepulse/health-service

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

Point it to RKE2 kubeconfig:

export KUBECONFIG=/etc/rancher/rke2/rke2.yaml

Run:

uvicorn main:app --host 0.0.0.0 --port 8000 --reload

Test:

curl http://localhost:8000/healthz
curl http://localhost:8000/api/namespaces
curl http://localhost:8000/api/cluster/health
curl "http://localhost:8000/api/cluster/health?namespace=default"
2.6 Dockerfile

Create health-service/Dockerfile.

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

Build:

docker build -t kubepulse-health-service:0.1.0 .
2.7 Kubernetes RBAC for Health Service

Create health-service/k8s/rbac.yaml.

apiVersion: v1
kind: Namespace
metadata:
  name: kubepulse
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: kubepulse-health-sa
  namespace: kubepulse
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kubepulse-health-reader
rules:
  - apiGroups: [""]
    resources:
      - nodes
      - namespaces
      - pods
      - services
      - endpoints
      - persistentvolumeclaims
      - events
    verbs:
      - get
      - list
      - watch

  - apiGroups: ["apps"]
    resources:
      - deployments
      - replicasets
      - statefulsets
      - daemonsets
    verbs:
      - get
      - list
      - watch

  - apiGroups: ["discovery.k8s.io"]
    resources:
      - endpointslices
    verbs:
      - get
      - list
      - watch

  - apiGroups: ["networking.k8s.io"]
    resources:
      - ingresses
    verbs:
      - get
      - list
      - watch
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: kubepulse-health-reader-binding
subjects:
  - kind: ServiceAccount
    name: kubepulse-health-sa
    namespace: kubepulse
roleRef:
  kind: ClusterRole
  name: kubepulse-health-reader
  apiGroup: rbac.authorization.k8s.io

Apply:

kubectl apply -f k8s/rbac.yaml
2.8 Kubernetes Deployment for Health Service

Create health-service/k8s/deployment.yaml.

apiVersion: apps/v1
kind: Deployment
metadata:
  name: kubepulse-health-service
  namespace: kubepulse
spec:
  replicas: 1
  selector:
    matchLabels:
      app: kubepulse-health-service
  template:
    metadata:
      labels:
        app: kubepulse-health-service
    spec:
      serviceAccountName: kubepulse-health-sa
      containers:
        - name: health-service
          image: kubepulse-health-service:0.1.0
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: 8000
          env:
            - name: CORS_ALLOW_ORIGINS
              value: "*"
          readinessProbe:
            httpGet:
              path: /healthz
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8000
            initialDelaySeconds: 15
            periodSeconds: 20
---
apiVersion: v1
kind: Service
metadata:
  name: kubepulse-health-service
  namespace: kubepulse
spec:
  type: ClusterIP
  selector:
    app: kubepulse-health-service
  ports:
    - name: http
      port: 8000
      targetPort: 8000

Apply:

kubectl apply -f k8s/deployment.yaml

Check:

kubectl get pods -n kubepulse
kubectl get svc -n kubepulse

Port forward:

kubectl port-forward -n kubepulse svc/kubepulse-health-service 8000:8000

Test:

curl http://localhost:8000/api/cluster/health
Phase 3: Streamlit Dashboard
Goal

Build a user-friendly dashboard using Streamlit that connects to the Python Health Check Service and displays cluster health. Streamlit is a Python framework for quickly building data apps, and its caching features help avoid unnecessary repeated computation during reruns.

3.1 Dashboard Features

The dashboard will show:

Overall cluster health
Node status
Pod health
Deployment health
Service health
PVC health
Warning events
Namespace filtering
Status filtering
Problem summary
Raw JSON view for debugging
3.2 dashboard/requirements.txt
streamlit==1.41.1
requests==2.32.3
pandas==2.2.3
3.3 dashboard/app.py
import os
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
import streamlit as st


STATUS_EMOJI = {
    "healthy": "🟢",
    "warning": "🟠",
    "critical": "🔴",
    "unknown": "⚪",
}


st.set_page_config(
    page_title="KubePulse Dashboard",
    page_icon="🩺",
    layout="wide",
)


def status_label(status: str) -> str:
    return f"{STATUS_EMOJI.get(status, '⚪')} {status.upper()}"


@st.cache_data(ttl=10, show_spinner=False)
def fetch_json(url: str) -> Dict[str, Any]:
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.json()


def api_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def fetch_namespaces(base_url: str) -> List[str]:
    try:
        data = fetch_json(api_url(base_url, "/api/namespaces"))
        return data.get("namespaces", [])
    except Exception:
        return []


def fetch_health(base_url: str, namespace: Optional[str]) -> Dict[str, Any]:
    path = "/api/cluster/health"

    if namespace and namespace != "all":
        path += f"?namespace={namespace}"

    return fetch_json(api_url(base_url, path))


def render_status_counts(title: str, counts: Dict[str, int]) -> None:
    st.markdown(f"#### {title}")

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Healthy", counts.get("healthy", 0))
    c2.metric("Warning", counts.get("warning", 0))
    c3.metric("Critical", counts.get("critical", 0))
    c4.metric("Unknown", counts.get("unknown", 0))


def as_dataframe(items: List[Dict[str, Any]]) -> pd.DataFrame:
    if not items:
        return pd.DataFrame()

    df = pd.DataFrame(items)

    if "status" in df.columns:
        df.insert(0, "health", df["status"].map(status_label))

    return df


def filter_by_status(df: pd.DataFrame, status_filter: str) -> pd.DataFrame:
    if df.empty or status_filter == "all" or "status" not in df.columns:
        return df

    return df[df["status"] == status_filter]


st.title("🩺 KubePulse Kubernetes Health Dashboard")
st.caption("User-friendly health view for RKE2/Kubernetes objects using the Python Health Check Service.")

with st.sidebar:
    st.header("Connection")

    base_url = st.text_input(
        "Health Service URL",
        value=os.getenv("HEALTH_SERVICE_URL", "http://localhost:8000"),
        help="Example: http://localhost:8000 or http://kubepulse-health-service.kubepulse.svc.cluster.local:8000",
    )

    if st.button("Refresh now"):
        st.cache_data.clear()

    st.divider()

    namespaces = ["all"] + fetch_namespaces(base_url)
    namespace = st.selectbox("Namespace", namespaces, index=0)

    status_filter = st.selectbox(
        "Status filter",
        ["all", "critical", "warning", "healthy", "unknown"],
        index=0,
    )

    st.info("Data is cached for 10 seconds to avoid overloading the Kubernetes API.")

try:
    data = fetch_health(base_url, namespace)
except Exception as exc:
    st.error(f"Could not connect to Health Service: {exc}")
    st.stop()


summary = data.get("summary", {})
overall_status = summary.get("overall_status", "unknown")
totals = summary.get("totals", {})

top1, top2, top3, top4, top5 = st.columns(5)

top1.metric("Overall Health", status_label(overall_status))
top2.metric("Nodes", totals.get("nodes", 0))
top3.metric("Pods", totals.get("pods", 0))
top4.metric("Deployments", totals.get("deployments", 0))
top5.metric("Warning Events", totals.get("warning_events", 0))

st.caption(f"Generated at: {data.get('generated_at')} | Namespace: {data.get('namespace')}")

if overall_status == "critical":
    st.error("Critical issues detected. Start with the Critical Pods, Deployments, Services, and Events tabs.")
elif overall_status == "warning":
    st.warning("Warnings detected. Review degraded resources before they become outages.")
elif overall_status == "healthy":
    st.success("Cluster looks healthy based on the configured checks.")
else:
    st.info("Some resources are unknown. Check RBAC permissions or unsupported resource types.")


overview_tab, pods_tab, deployments_tab, services_tab, nodes_tab, pvc_tab, events_tab, raw_tab = st.tabs(
    ["Overview", "Pods", "Deployments", "Services", "Nodes", "PVCs", "Events", "Raw JSON"]
)


with overview_tab:
    c1, c2 = st.columns(2)

    with c1:
        render_status_counts("Pods", summary.get("pods", {}))
        render_status_counts("Deployments", summary.get("deployments", {}))

    with c2:
        render_status_counts("Services", summary.get("services", {}))
        render_status_counts("Nodes", summary.get("nodes", {}))

    st.subheader("Top problems")

    problem_rows = []

    for section in ["pods", "deployments", "services", "nodes", "pvcs"]:
        for item in data.get(section, []):
            if item.get("status") in {"critical", "warning"}:
                problem_rows.append(
                    {
                        "type": section[:-1],
                        "namespace": item.get("namespace"),
                        "name": item.get("name"),
                        "status": item.get("status"),
                        "reason": item.get("reason"),
                    }
                )

    problems_df = as_dataframe(problem_rows)

    if problems_df.empty:
        st.success("No critical or warning resources found.")
    else:
        st.dataframe(problems_df, use_container_width=True, hide_index=True)


with pods_tab:
    df = filter_by_status(as_dataframe(data.get("pods", [])), status_filter)
    st.dataframe(df, use_container_width=True, hide_index=True)


with deployments_tab:
    df = filter_by_status(as_dataframe(data.get("deployments", [])), status_filter)
    st.dataframe(df, use_container_width=True, hide_index=True)


with services_tab:
    df = filter_by_status(as_dataframe(data.get("services", [])), status_filter)
    st.dataframe(df, use_container_width=True, hide_index=True)


with nodes_tab:
    df = filter_by_status(as_dataframe(data.get("nodes", [])), status_filter)
    st.dataframe(df, use_container_width=True, hide_index=True)


with pvc_tab:
    df = filter_by_status(as_dataframe(data.get("pvcs", [])), status_filter)
    st.dataframe(df, use_container_width=True, hide_index=True)


with events_tab:
    events_df = as_dataframe(data.get("warning_events", []))

    if events_df.empty:
        st.success("No recent warning events returned.")
    else:
        st.dataframe(events_df, use_container_width=True, hide_index=True)


with raw_tab:
    st.json(data)
3.4 Run Streamlit Dashboard Locally
cd kubepulse/dashboard

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

Run:

export HEALTH_SERVICE_URL=http://localhost:8000
streamlit run app.py

Open the Streamlit URL shown in your terminal.

Final MVP Flow
1. Install RKE2
2. Validate cluster with kubectl
3. Run Python Health Check Service
4. Health service reads Kubernetes API
5. Streamlit calls Health Check Service
6. Dashboard displays health status