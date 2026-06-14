class AlertStore:
    def __init__(self):
        self.active_alerts = []
        self.alert_history = []

    def add_alerts(self, payload: dict):
        status = payload.get("status", "firing")
        for alert in payload.get("alerts", []):
            alert_name = alert.get("labels", {}).get("alertname", "UnknownAlert")
            namespace = alert.get("labels", {}).get("namespace", "N/A")
            pod = alert.get("labels", {}).get("pod", "N/A")
            severity = alert.get("labels", {}).get("severity", "warning")
            summary = alert.get("annotations", {}).get("summary", "")
            description = alert.get("annotations", {}).get("description", "")
            starts_at = alert.get("startsAt")
            ends_at = alert.get("endsAt")
            
            alert_data = {
                "name": alert_name,
                "namespace": namespace,
                "pod": pod,
                "severity": severity,
                "summary": summary,
                "description": description,
                "status": alert.get("status", status),
                "starts_at": starts_at,
                "ends_at": ends_at
            }
            
            # If resolved, remove from active alerts and add to history
            if alert.get("status") == "resolved" or status == "resolved":
                # Find matching active alert and remove it
                self.active_alerts = [a for a in self.active_alerts if not (a["name"] == alert_name and a["namespace"] == namespace and a["pod"] == pod)]
                alert_data["status"] = "resolved"
                self.alert_history.append(alert_data)
            else:
                # Add to active alerts if not already present
                exists = any(a["name"] == alert_name and a["namespace"] == namespace and a["pod"] == pod for a in self.active_alerts)
                if not exists:
                    self.active_alerts.append(alert_data)
                    self.alert_history.append(alert_data)
            
            # Keep history capped at 100 items
            if len(self.alert_history) > 100:
                self.alert_history.pop(0)

    def get_active(self):
        return self.active_alerts

    def get_history(self):
        return self.alert_history

alert_store = AlertStore()
