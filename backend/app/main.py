from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from app.k8s_client import K8sClient
from app.alerts import alert_store

app = FastAPI(title="KubePulse Backend API", version="1.0.0")

# Configure CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize K8s Client lazily
k8s_client = None

def get_k8s_client():
    global k8s_client
    if k8s_client is None:
        try:
            k8s_client = K8sClient()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to connect to Kubernetes API: {str(e)}")
    return k8s_client

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "kubepulse-backend"}

@app.post("/api/alerts/webhook")
async def alert_webhook(request: Request):
    try:
        payload = await request.json()
        alert_store.add_alerts(payload)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")

@app.get("/api/cluster/alerts")
def get_alerts(history: bool = False):
    if history:
        return alert_store.get_history()
    return alert_store.get_active()

@app.get("/api/cluster/summary")
def get_summary():
    client = get_k8s_client()
    try:
        summary = client.get_summary()
        # Enrich summary with active alerts count
        summary["active_alerts"] = len(alert_store.get_active())
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/cluster/nodes")
def get_nodes():
    client = get_k8s_client()
    try:
        return client.get_nodes()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/cluster/namespaces")
def get_namespaces():
    client = get_k8s_client()
    try:
        return client.get_namespaces()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/cluster/pods")
def get_pods(namespace: str = None):
    client = get_k8s_client()
    try:
        return client.get_pods(namespace)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/cluster/deployments")
def get_deployments(namespace: str = None):
    client = get_k8s_client()
    try:
        return client.get_deployments(namespace)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/cluster/events")
def get_events():
    client = get_k8s_client()
    try:
        return client.get_events()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
