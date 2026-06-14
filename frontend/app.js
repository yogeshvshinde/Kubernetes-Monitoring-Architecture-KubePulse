// KubePulse Client Application Logic

const getApiUrl = (endpoint) => {
    // If opened via file protocol, fallback to standard localhost port 80 (Ingress)
    if (window.location.protocol === "file:") {
        return `http://localhost/api${endpoint}`;
    }
    // Relative route when deployed inside the cluster
    return `/api${endpoint}`;
};

// UI Elements
const nsSelect = document.getElementById("namespace-select");
const refreshBtn = document.getElementById("refresh-btn");
const valNodes = document.getElementById("val-nodes");
const valNamespaces = document.getElementById("val-namespaces");
const valDeployments = document.getElementById("val-deployments");
const valPods = document.getElementById("val-pods");
const subPods = document.getElementById("sub-pods");
const podsTableBody = document.getElementById("pods-table-body");
const deploymentsTableBody = document.getElementById("deployments-table-body");
const nodesContainer = document.getElementById("nodes-container");
const eventsContainer = document.getElementById("events-container");
const podCountBadge = document.getElementById("pod-count-badge");
const alertsContainer = document.getElementById("alerts-container");
const alertCountBadge = document.getElementById("alert-count-badge");

// State
let namespaces = [];
let selectedNamespace = "all";

// Fetch and render everything
async function updateDashboard() {
    console.log("Updating dashboard metrics...");
    try {
        await Promise.all([
            fetchSummary(),
            fetchNamespaces(),
            fetchPods(),
            fetchDeployments(),
            fetchNodes(),
            fetchEvents(),
            fetchAlerts()
        ]);
    } catch (err) {
        console.error("Dashboard update error:", err);
    }
}

// Fetch general cluster summary stats
async function fetchSummary() {
    try {
        const res = await fetch(getApiUrl("/cluster/summary"));
        if (!res.ok) throw new Error("Summary request failed");
        const data = await res.json();
        
        valNodes.textContent = `${data.nodes.ready} / ${data.nodes.total}`;
        valDeployments.textContent = data.deployments;
        valPods.textContent = data.pods.total;
        subPods.textContent = `Running: ${data.pods.running} | Failed: ${data.pods.failed} | Pending: ${data.pods.pending}`;
    } catch (err) {
        valNodes.textContent = "Error";
        valDeployments.textContent = "Error";
        valPods.textContent = "Error";
        console.error(err);
    }
}

// Fetch active namespaces
async function fetchNamespaces() {
    try {
        const res = await fetch(getApiUrl("/cluster/namespaces"));
        if (!res.ok) throw new Error("Namespaces request failed");
        const data = await res.json();
        namespaces = data;
        
        valNamespaces.textContent = namespaces.length;
        
        // Update select options if options count doesn't match namespaces
        const currentOptions = Array.from(nsSelect.options).map(o => o.value);
        namespaces.forEach(ns => {
            if (!currentOptions.includes(ns)) {
                const opt = document.createElement("option");
                opt.value = ns;
                opt.textContent = ns;
                nsSelect.appendChild(opt);
            }
        });
    } catch (err) {
        valNamespaces.textContent = "Error";
        console.error(err);
    }
}

// Fetch Pods
async function fetchPods() {
    try {
        const url = selectedNamespace === "all" 
            ? getApiUrl("/cluster/pods")
            : getApiUrl(`/cluster/pods?namespace=${selectedNamespace}`);
            
        const res = await fetch(url);
        if (!res.ok) throw new Error("Pods request failed");
        const data = await res.json();
        
        podCountBadge.textContent = `${data.length} Pods`;
        
        if (data.length === 0) {
            podsTableBody.innerHTML = `<tr><td colspan="6" class="table-placeholder">No pods running in namespace: ${selectedNamespace}</td></tr>`;
            return;
        }
        
        podsTableBody.innerHTML = data.map(pod => {
            let statusClass = "status-pending";
            if (pod.status === "Running") statusClass = "status-running";
            if (pod.status === "Failed" || pod.status === "Unknown") statusClass = "status-failed";
            
            return `
                <tr>
                    <td class="mono" style="font-weight: 500;">${pod.name}</td>
                    <td><span class="badge" style="background: rgba(255,255,255,0.05); color: #cbd5e1;">${pod.namespace}</span></td>
                    <td><span class="status-pill ${statusClass}">${pod.status}</span></td>
                    <td class="mono">${pod.restarts}</td>
                    <td class="mono">${pod.ip}</td>
                    <td>${pod.node}</td>
                </tr>
            `;
        }).join("");
    } catch (err) {
        podsTableBody.innerHTML = `<tr><td colspan="6" class="table-placeholder" style="color: var(--accent-red)">Error loading pods data: ${err.message}</td></tr>`;
    }
}

// Fetch Deployments
async function fetchDeployments() {
    try {
        const url = selectedNamespace === "all" 
            ? getApiUrl("/cluster/deployments")
            : getApiUrl(`/cluster/deployments?namespace=${selectedNamespace}`);
            
        const res = await fetch(url);
        if (!res.ok) throw new Error("Deployments request failed");
        const data = await res.json();
        
        if (data.length === 0) {
            deploymentsTableBody.innerHTML = `<tr><td colspan="4" class="table-placeholder">No deployments found in namespace: ${selectedNamespace}</td></tr>`;
            return;
        }
        
        deploymentsTableBody.innerHTML = data.map(dep => {
            let statusClass = "status-running";
            if (dep.status === "Degraded") statusClass = "status-failed";
            
            return `
                <tr>
                    <td class="mono" style="font-weight: 500;">${dep.name}</td>
                    <td><span class="badge" style="background: rgba(255,255,255,0.05); color: #cbd5e1;">${dep.namespace}</span></td>
                    <td><span class="status-pill ${statusClass}">${dep.status}</span></td>
                    <td class="mono">${dep.replicas.available} / ${dep.replicas.desired}</td>
                </tr>
            `;
        }).join("");
    } catch (err) {
        deploymentsTableBody.innerHTML = `<tr><td colspan="4" class="table-placeholder" style="color: var(--accent-red)">Error loading deployments: ${err.message}</td></tr>`;
    }
}

// Fetch Nodes
async function fetchNodes() {
    try {
        const res = await fetch(getApiUrl("/cluster/nodes"));
        if (!res.ok) throw new Error("Nodes request failed");
        const data = await res.json();
        
        if (data.length === 0) {
            nodesContainer.innerHTML = '<div class="card-placeholder">No nodes found in the cluster.</div>';
            return;
        }
        
        nodesContainer.innerHTML = data.map(node => {
            let statusClass = "status-pending";
            if (node.status === "Ready") statusClass = "status-running";
            if (node.status === "NotReady") statusClass = "status-failed";
            
            const rolesHtml = node.roles.map(role => `<span class="node-role-tag">${role}</span>`).join("");
            
            return `
                <div class="node-card">
                    <div class="node-card-header">
                        <span class="node-name">${node.name}</span>
                        <span class="status-pill ${statusClass}">${node.status}</span>
                    </div>
                    <div class="node-roles">${rolesHtml}</div>
                    <div class="node-card-details">
                        <span>CPU: ${node.cpu_capacity} cores</span>
                        <span>Memory: ${node.memory_capacity}</span>
                        <span style="grid-column: span 2;">Kubelet: ${node.kubelet_version}</span>
                        <span style="grid-column: span 2; font-size: 0.75rem;">OS: ${node.os_image}</span>
                    </div>
                </div>
            `;
        }).join("");
    } catch (err) {
        nodesContainer.innerHTML = `<div class="card-placeholder" style="color: var(--accent-red)">Error: ${err.message}</div>`;
    }
}

// Fetch Live Events
async function fetchEvents() {
    try {
        const res = await fetch(getApiUrl("/cluster/events"));
        if (!res.ok) throw new Error("Events request failed");
        const data = await res.json();
        
        if (data.length === 0) {
            eventsContainer.innerHTML = '<div class="card-placeholder">No recent events recorded.</div>';
            return;
        }
        
        eventsContainer.innerHTML = data.map(event => {
            const isWarning = event.type === "Warning";
            const itemClass = isWarning ? "event-item-warning" : "event-item-normal";
            const timeFormatted = new Date(event.timestamp).toLocaleTimeString();
            
            return `
                <div class="event-item ${itemClass}">
                    <div class="event-meta">
                        <span class="mono">${event.object}</span>
                        <span class="mono">${timeFormatted}</span>
                    </div>
                    <div class="event-title">${event.reason} [${event.source}]</div>
                    <div class="event-msg">${event.message}</div>
                </div>
            `;
        }).join("");
    } catch (err) {
        eventsContainer.innerHTML = `<div class="card-placeholder" style="color: var(--accent-red)">Error loading event logs: ${err.message}</div>`;
    }
}

// Fetch Active Alerts
async function fetchAlerts() {
    try {
        const res = await fetch(getApiUrl("/cluster/alerts"));
        if (!res.ok) throw new Error("Alerts request failed");
        const data = await res.json();
        
        alertCountBadge.textContent = `${data.length} Active`;
        
        if (data.length === 0) {
            alertsContainer.innerHTML = '<div class="card-placeholder">No active incidents or alerts detected.</div>';
            return;
        }
        
        alertsContainer.innerHTML = data.map(alert => {
            const severityClass = alert.severity === "critical" ? "status-failed" : "status-pending";
            return `
                <div class="node-card" style="border-left: 3px solid ${alert.severity === 'critical' ? 'var(--accent-red)' : 'var(--accent-orange)'};">
                    <div class="node-card-header">
                        <span class="node-name" style="color: ${alert.severity === 'critical' ? 'var(--accent-red)' : 'var(--accent-orange)'};">${alert.name}</span>
                        <span class="status-pill ${severityClass}">${alert.severity.toUpperCase()}</span>
                    </div>
                    <div class="node-card-details" style="grid-template-columns: 1fr; margin-top: 0.25rem;">
                        <span style="font-weight: 500; color: var(--text-primary);">${alert.summary}</span>
                        <span>${alert.description}</span>
                        <span style="font-size: 0.75rem;">Pod: ${alert.pod} | Namespace: ${alert.namespace}</span>
                    </div>
                </div>
            `;
        }).join("");
    } catch (err) {
        alertsContainer.innerHTML = `<div class="card-placeholder" style="color: var(--accent-red)">Error loading alerts: ${err.message}</div>`;
    }
}

// Event Listeners
nsSelect.addEventListener("change", (e) => {
    selectedNamespace = e.target.value;
    fetchPods();
    fetchDeployments();
});

refreshBtn.addEventListener("click", () => {
    updateDashboard();
});

// Auto Polling (every 5 seconds)
updateDashboard();
setInterval(updateDashboard, 5000);
