import streamlit as st
import requests
import os
import time

# Set up page configurations
st.set_page_config(
    page_title="KubePulse | Kubernetes Dashboard",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Backend URL resolver
BACKEND_URL = os.getenv("BACKEND_URL", "http://kubepulse-backend:8000")

# Fetch helpers
def fetch_api(endpoint):
    try:
        r = requests.get(f"{BACKEND_URL}/api{endpoint}", timeout=3)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None

# Page Header
st.markdown("""
<div style="text-align: center; margin-bottom: 25px; margin-top: -30px;">
    <h1 style="font-size: 3.8rem; font-weight: 900; letter-spacing: -2px; margin: 0 0 8px 0; background: linear-gradient(135deg, #00f2fe 0%, #4facfe 35%, #ec4899 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; filter: drop-shadow(0px 4px 12px rgba(79, 172, 254, 0.25)); font-family: 'Inter', sans-serif;">
        ⚡ KubePulse
    </h1>
    <span style="background-color: rgba(16, 185, 129, 0.12); color: #10b981; padding: 6px 16px; border-radius: 9999px; font-size: 0.8rem; font-weight: 700; letter-spacing: 1px; border: 1px solid rgba(16, 185, 129, 0.25); text-transform: uppercase; font-family: 'Inter', sans-serif;">
        ACTIVE CLUSTER MONITORING
    </span>
</div>
""", unsafe_allow_html=True)

# Main Navigation Link Buttons (Centered below title using a flat layout to avoid React nested columns rendering loops)
btn_col1, btn_col2, btn_col3, btn_col4 = st.columns([2.5, 1.5, 1.5, 2.5])
with btn_col2:
    st.link_button("📊 Open Grafana", "http://localhost/grafana/", use_container_width=True)
with btn_col3:
    st.link_button("🔥 Open Prometheus", "http://localhost/prometheus/", use_container_width=True)

# Fetch current state data
summary = fetch_api("/cluster/summary")
namespaces_list = fetch_api("/cluster/namespaces") or ["all"]
nodes = fetch_api("/cluster/nodes")
alerts = fetch_api("/cluster/alerts")
events = fetch_api("/cluster/events")

# Sidebar Controls
st.sidebar.title("KubePulse Controls")
selected_ns = st.sidebar.selectbox("Filter Namespace", ["all"] + [ns for ns in namespaces_list if ns != "all"])

# Add manual refresh and auto refresh options
st.sidebar.markdown("---")
auto_refresh = st.sidebar.checkbox("Auto Refresh (5s)", value=True)

# Summary Metrics Row
if summary:
    nodes_ready = summary["nodes"]["ready"]
    nodes_total = summary["nodes"]["total"]
    pods_running = summary["pods"]["running"]
    pods_total = summary["pods"]["total"]
    active_alerts = summary["active_alerts"]
    
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Nodes (Ready/Total)", f"{nodes_ready} / {nodes_total}", delta=f"{nodes_total - nodes_ready} unready" if nodes_total != nodes_ready else None, delta_color="inverse")
    col2.metric("Namespaces", summary["namespaces"])
    col3.metric("Deployments", summary["deployments"])
    col4.metric("Pods (Running/Total)", f"{pods_running} / {pods_total}", delta=f"{pods_total - pods_running} failing" if pods_total != pods_running else None, delta_color="inverse")
    
    # Alert metric color matches severity
    if active_alerts > 0:
        col5.markdown(f"""
        <div style="background-color: rgba(239, 68, 68, 0.12); padding: 10px; border-radius: 8px; border: 1px solid rgba(239, 68, 68, 0.3); text-align: center;">
            <span style="font-size: 0.8rem; color: #94a3b8; font-weight: bold; text-transform: uppercase;">Incidents / Alerts</span>
            <div style="font-size: 1.8rem; color: #ef4444; font-weight: bold; margin-top: 5px;">🔥 {active_alerts} Active</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        col5.metric("Incidents / Alerts", "0 Active")
else:
    st.error("Could not fetch metrics summary from KubePulse backend. Check if the backend API is running.")

st.markdown("---")

# Main tabs layout
tab1, tab2, tab3, tab4, tab5 = st.tabs(["📦 Pods", "🚀 Deployments", "🖥️ Nodes", "🚨 Incidents", "📜 Event Stream"])

# Tab 1: Pods View
with tab1:
    st.subheader("Workload Pods")
    pods_url = "/cluster/pods" if selected_ns == "all" else f"/cluster/pods?namespace={selected_ns}"
    pods = fetch_api(pods_url)
    if pods:
        pods_data = []
        for p in pods:
            pods_data.append({
                "Pod Name": p["name"],
                "Namespace": p["namespace"],
                "Status": p["status"],
                "IP Address": p["ip"],
                "Node": p["node"],
                "Restarts": p["restarts"]
            })
        st.dataframe(pods_data, use_container_width=True)
    else:
        st.info("No active pods found in this namespace.")

# Tab 2: Deployments View
with tab2:
    st.subheader("Deployments Status")
    deploy_url = "/cluster/deployments" if selected_ns == "all" else f"/cluster/deployments?namespace={selected_ns}"
    deployments = fetch_api(deploy_url)
    if deployments:
        deploy_data = []
        for d in deployments:
            deploy_data.append({
                "Deployment Name": d["name"],
                "Namespace": d["namespace"],
                "Status": d["status"],
                "Desired": d["replicas"]["desired"],
                "Available": d["replicas"]["available"],
                "Ready": d["replicas"]["ready"]
            })
        st.dataframe(deploy_data, use_container_width=True)
    else:
        st.info("No deployments found in this namespace.")

# Tab 3: Nodes View
with tab3:
    st.subheader("Cluster Node Infrastructure")
    if nodes:
        for node in nodes:
            status_color = "green" if node["status"] == "Ready" else "red"
            st.markdown(f"""
            <div style="background-color: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.08); padding: 15px; border-radius: 10px; margin-bottom: 15px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-weight: bold; font-size: 1.1rem;">🖥️ {node["name"]}</span>
                    <span style="background-color: {status_color}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: bold;">{node["status"]}</span>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; font-size: 0.9rem; color: #94a3b8;">
                    <span><b>CPU Capacity:</b> {node["cpu_capacity"]} cores</span>
                    <span><b>Memory Capacity:</b> {node["memory_capacity"]}</span>
                    <span><b>Kubelet Version:</b> {node["kubelet_version"]}</span>
                    <span><b>Kernel Version:</b> {node["kernel_version"]}</span>
                    <span style="grid-column: span 2;"><b>OS Image:</b> {node["os_image"]}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No node information available.")

# Tab 4: Incidents View
with tab4:
    st.subheader("Firing Alerts & Webhook Incidents")
    if alerts and len(alerts) > 0:
        for alert in alerts:
            border_color = "#ef4444" if alert["severity"] == "critical" else "#f59e0b"
            st.markdown(f"""
            <div style="border-left: 5px solid {border_color}; background-color: rgba(255,255,255,0.02); padding: 15px; border-radius: 4px; margin-bottom: 15px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-weight: bold; font-size: 1.05rem; color: {border_color};">🚨 {alert["name"]}</span>
                    <span style="background-color: {border_color}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: bold;">{alert["severity"].upper()}</span>
                </div>
                <div style="margin-top: 8px; font-size: 0.95rem;">
                    <b>Summary:</b> {alert["summary"]}<br>
                    <b>Description:</b> {alert["description"]}
                </div>
                <div style="margin-top: 8px; font-size: 0.8rem; color: #94a3b8;">
                    Namespace: {alert["namespace"]} | Pod: {alert["pod"]} | Firing since: {alert["starts_at"]}
                </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.success("No active incidents or alerts detected. The cluster is healthy!")

# Tab 5: Event Stream View
with tab5:
    st.subheader("Live Kubernetes Resource Events")
    if events:
        for e in events:
            indicator_color = "red" if e["type"] == "Warning" else "#3b82f6"
            st.markdown(f"""
            <div style="border-left: 3px solid {indicator_color}; padding-left: 10px; margin-bottom: 15px; font-size: 0.9rem;">
                <div style="display: flex; justify-content: space-between; color: #94a3b8; font-size: 0.8rem;">
                    <span><b>{e["object"]}</b></span>
                    <span>{e["timestamp"]}</span>
                </div>
                <div style="font-weight: bold; margin-top: 2px;">{e["reason"]} [{e["source"]}]</div>
                <div style="color: #cbd5e1; margin-top: 2px;">{e["message"]}</div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No recent Kubernetes events found.")

# Trigger auto-refresh at the end of the script execution so the page actually renders first!
if auto_refresh:
    time.sleep(5)
    st.rerun()
