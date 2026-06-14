import os
from kubernetes import client, config
from kubernetes.client.rest import ApiException

class K8sClient:
    def __init__(self):
        # Determine whether to load in-cluster config or local kubeconfig
        if os.getenv("IN_CLUSTER") == "true":
            try:
                config.load_incluster_config()
            except config.config_exception.ConfigException:
                # Fallback to local config if loading fails (e.g. running locally for tests)
                config.load_kube_config()
        else:
            config.load_kube_config()
            
        self.v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()

    def get_summary(self):
        try:
            nodes = self.v1.list_node().items
            namespaces = self.v1.list_namespace().items
            pods = self.v1.list_pod_for_all_namespaces().items
            deployments = self.apps_v1.list_deployment_for_all_namespaces().items
            
            # Count statuses
            running_pods = sum(1 for p in pods if p.status.phase == "Running")
            failed_pods = sum(1 for p in pods if p.status.phase in ["Failed", "Unknown"])
            pending_pods = sum(1 for p in pods if p.status.phase == "Pending")
            
            ready_nodes = sum(1 for n in nodes if any(c.type == "Ready" and c.status == "True" for c in n.status.conditions))
            
            return {
                "nodes": {
                    "total": len(nodes),
                    "ready": ready_nodes,
                    "unready": len(nodes) - ready_nodes
                },
                "namespaces": len(namespaces),
                "pods": {
                    "total": len(pods),
                    "running": running_pods,
                    "failed": failed_pods,
                    "pending": pending_pods
                },
                "deployments": len(deployments)
            }
        except ApiException as e:
            raise Exception(f"Kubernetes API error: {e}")

    def get_nodes(self):
        try:
            nodes = self.v1.list_node().items
            node_list = []
            for node in nodes:
                # Get conditions
                ready_status = "Unknown"
                for condition in node.status.conditions:
                    if condition.type == "Ready":
                        ready_status = "Ready" if condition.status == "True" else "NotReady"
                        break
                
                # Get resource capacity
                cpu = node.status.capacity.get("cpu", "N/A")
                memory = node.status.capacity.get("memory", "N/A")
                
                # Get labels/roles
                roles = []
                for label in node.metadata.labels:
                    if label.startswith("node-role.kubernetes.io/"):
                        roles.append(label.split("/")[-1])
                if not roles:
                    roles = ["worker"]
                
                node_list.append({
                    "name": node.metadata.name,
                    "status": ready_status,
                    "roles": roles,
                    "cpu_capacity": cpu,
                    "memory_capacity": memory,
                    "kubelet_version": node.status.node_info.kubelet_version,
                    "os_image": node.status.node_info.os_image,
                    "kernel_version": node.status.node_info.kernel_version
                })
            return node_list
        except ApiException as e:
            raise Exception(f"Kubernetes API error: {e}")

    def get_namespaces(self):
        try:
            ns_list = self.v1.list_namespace().items
            return [ns.metadata.name for ns in ns_list]
        except ApiException as e:
            raise Exception(f"Kubernetes API error: {e}")

    def get_pods(self, namespace: str = None):
        try:
            if namespace:
                pods = self.v1.list_namespaced_pod(namespace).items
            else:
                pods = self.v1.list_pod_for_all_namespaces().items
                
            pod_list = []
            for pod in pods:
                # Count restarts
                restarts = 0
                container_states = {}
                if pod.status.container_statuses:
                    for status in pod.status.container_statuses:
                        restarts += status.restart_count
                        # Determine container state
                        if status.state.waiting:
                            container_states[status.name] = {
                                "state": "Waiting",
                                "reason": status.state.waiting.reason,
                                "message": status.state.waiting.message
                            }
                        elif status.state.running:
                            container_states[status.name] = {"state": "Running"}
                        elif status.state.terminated:
                            container_states[status.name] = {
                                "state": "Terminated",
                                "reason": status.state.terminated.reason
                            }
                
                pod_list.append({
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "status": pod.status.phase,
                    "ip": pod.status.pod_ip or "N/A",
                    "node": pod.spec.node_name or "N/A",
                    "restarts": restarts,
                    "container_states": container_states,
                    "created_at": pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else None
                })
            return pod_list
        except ApiException as e:
            raise Exception(f"Kubernetes API error: {e}")

    def get_deployments(self, namespace: str = None):
        try:
            if namespace:
                deployments = self.apps_v1.list_namespaced_deployment(namespace).items
            else:
                deployments = self.apps_v1.list_deployment_for_all_namespaces().items
                
            deploy_list = []
            for deploy in deployments:
                replicas = deploy.status.replicas or 0
                ready_replicas = deploy.status.ready_replicas or 0
                available_replicas = deploy.status.available_replicas or 0
                
                # Check status
                status = "Healthy"
                if replicas != available_replicas:
                    status = "Degraded"
                
                deploy_list.append({
                    "name": deploy.metadata.name,
                    "namespace": deploy.metadata.namespace,
                    "status": status,
                    "replicas": {
                        "desired": deploy.spec.replicas,
                        "updated": deploy.status.updated_replicas or 0,
                        "ready": ready_replicas,
                        "available": available_replicas
                    },
                    "created_at": deploy.metadata.creation_timestamp.isoformat() if deploy.metadata.creation_timestamp else None
                })
            return deploy_list
        except ApiException as e:
            raise Exception(f"Kubernetes API error: {e}")

    def get_events(self):
        try:
            # Get latest 25 events
            events = self.v1.list_event_for_all_namespaces(limit=25).items
            # Sort by last timestamp or creation timestamp
            events.sort(key=lambda x: x.last_timestamp or x.event_time or x.metadata.creation_timestamp or '', reverse=True)
            
            event_list = []
            for event in events[:25]:
                # Format timestamps safely
                t = event.last_timestamp or event.event_time or event.metadata.creation_timestamp
                t_str = t.isoformat() if t else "N/A"
                
                event_list.append({
                    "namespace": event.metadata.namespace,
                    "type": event.type,
                    "reason": event.reason,
                    "message": event.message,
                    "source": event.source.component or "N/A",
                    "object": f"{event.involved_object.kind}/{event.involved_object.name}",
                    "timestamp": t_str
                })
            return event_list
        except ApiException as e:
            raise Exception(f"Kubernetes API error: {e}")
