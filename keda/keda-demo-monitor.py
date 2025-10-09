#!/usr/bin/env python3

"""
KEDA Demo Monitor for Event-Driven Autoscaling Analysis

This script monitors and analyzes KEDA components, ScaledObjects, HPAs, external metrics,
and Azure Service Bus queues to provide comprehensive insights into event-driven autoscaling
behavior during KEDA demonstrations.

Features:
- KEDA component health monitoring
- ScaledObject status and configuration analysis
- HPA comparison (standard vs KEDA-generated)
- External metrics monitoring
- Service Bus queue depth tracking
- Scaling prediction and efficiency analysis
- Real-time scaling event detection

Author: Generated for KEDA Demonstration
Usage: python3 keda-demo-monitor.py [namespace] [scaledobject-name]
"""

import subprocess
import json
import sys
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

def run_kubectl(command: str) -> Tuple[bool, str]:
    """Execute kubectl command and return success status and output."""
    try:
        result = subprocess.run(
            f"kubectl {command}",
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "Command timeout"
    except Exception as e:
        return False, f"Error: {str(e)}"

def run_az_command(command: str) -> Tuple[bool, str]:
    """Execute Azure CLI command and return success status and output."""
    try:
        result = subprocess.run(
            f"az {command}",
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "Command timeout"
    except Exception as e:
        return False, f"Error: {str(e)}"

def parse_resource_unit(value: str, resource_type: str) -> float:
    """Parse Kubernetes resource units (CPU: cores/millicores, Memory: bytes)."""
    if not value or value == "<unknown>":
        return 0.0
    
    value = value.strip()
    
    if resource_type == "cpu":
        if value.endswith('m'):
            return float(value[:-1]) / 1000  # millicores to cores
        elif value.endswith('n'):
            return float(value[:-1]) / 1000000000  # nanocores to cores
        else:
            return float(value)  # already in cores
    
    elif resource_type == "memory":
        # Convert to bytes
        if value.endswith('Ki'):
            return float(value[:-2]) * 1024
        elif value.endswith('Mi'):
            return float(value[:-2]) * 1024 * 1024
        elif value.endswith('Gi'):
            return float(value[:-2]) * 1024 * 1024 * 1024
        elif value.endswith('Ti'):
            return float(value[:-2]) * 1024 * 1024 * 1024 * 1024
        else:
            return float(value)  # already in bytes
    
    return 0.0

def format_cpu(cores: float) -> str:
    """Format CPU cores with appropriate unit."""
    if cores >= 1:
        return f"{cores:.2f} cores"
    else:
        return f"{int(cores * 1000)}m"

def format_memory(bytes_val: float) -> str:
    """Format memory bytes with appropriate unit."""
    if bytes_val >= 1024**3:
        return f"{bytes_val / (1024**3):.2f}Gi"
    elif bytes_val >= 1024**2:
        return f"{bytes_val / (1024**2):.2f}Mi"
    elif bytes_val >= 1024:
        return f"{bytes_val / 1024:.2f}Ki"
    else:
        return f"{int(bytes_val)}B"

def check_keda_health() -> Dict:
    """Check KEDA component health and status."""
    health = {
        "keda_installed": False,
        "components": {},
        "external_metrics_api": False,
        "keda_version": "unknown"
    }
    
    # Check KEDA pods
    success, output = run_kubectl("get pods -n kube-system -l app.kubernetes.io/name=keda-operator -o json")
    if success:
        try:
            pods_data = json.loads(output)
            health["keda_installed"] = len(pods_data.get("items", [])) > 0
            
            for pod in pods_data.get("items", []):
                component_name = pod["metadata"]["labels"].get("app.kubernetes.io/component", "unknown")
                pod_name = pod["metadata"]["name"]
                status = pod["status"]["phase"]
                
                health["components"][component_name] = {
                    "name": pod_name,
                    "status": status,
                    "ready": status == "Running"
                }
        except json.JSONDecodeError:
            pass
    
    # Check external metrics API
    success, output = run_kubectl("get apiservices v1beta1.external.metrics.k8s.io -o json")
    if success:
        try:
            api_data = json.loads(output)
            conditions = api_data.get("status", {}).get("conditions", [])
            for condition in conditions:
                if condition.get("type") == "Available" and condition.get("status") == "True":
                    health["external_metrics_api"] = True
                    break
        except json.JSONDecodeError:
            pass
    
    # Get KEDA version
    success, output = run_kubectl("get deployment keda-operator -n kube-system -o json")
    if success:
        try:
            deployment_data = json.loads(output)
            containers = deployment_data.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
            for container in containers:
                if container.get("name") == "keda-operator":
                    image = container.get("image", "")
                    if ":" in image:
                        health["keda_version"] = image.split(":")[-1]
                    break
        except json.JSONDecodeError:
            pass
    
    return health

def get_scaledobjects_info(namespace: str = "default") -> List[Dict]:
    """Get information about ScaledObjects in the namespace."""
    scaledobjects = []
    
    success, output = run_kubectl(f"get scaledobjects -n {namespace} -o json")
    if not success:
        return scaledobjects
    
    try:
        data = json.loads(output)
        for so in data.get("items", []):
            name = so["metadata"]["name"]
            spec = so.get("spec", {})
            status = so.get("status", {})
            
            scaledobject_info = {
                "name": name,
                "namespace": namespace,
                "target_deployment": spec.get("scaleTargetRef", {}).get("name", "unknown"),
                "min_replicas": spec.get("minReplicaCount", 0),
                "max_replicas": spec.get("maxReplicaCount", 10),
                "triggers": [],
                "current_replicas": status.get("externalMetricNames", []),
                "conditions": status.get("conditions", []),
                "hpa_name": status.get("hpaName", ""),
                "last_active_time": status.get("lastActiveTime", "")
            }
            
            # Parse triggers
            for trigger in spec.get("triggers", []):
                trigger_info = {
                    "type": trigger.get("type", "unknown"),
                    "metadata": trigger.get("metadata", {}),
                    "auth_ref": trigger.get("authenticationRef", {}).get("name", "")
                }
                scaledobject_info["triggers"].append(trigger_info)
            
            scaledobjects.append(scaledobject_info)
    
    except json.JSONDecodeError:
        pass
    
    return scaledobjects

def get_hpa_comparison(namespace: str = "default") -> Dict:
    """Compare different types of HPAs in the cluster."""
    hpa_comparison = {
        "standard_hpas": [],
        "keda_hpas": [],
        "system_hpas": []
    }
    
    # Get all HPAs
    success, output = run_kubectl(f"get hpa -A -o json")
    if not success:
        return hpa_comparison
    
    try:
        data = json.loads(output)
        for hpa in data.get("items", []):
            hpa_name = hpa["metadata"]["name"]
            hpa_namespace = hpa["metadata"]["namespace"]
            labels = hpa["metadata"].get("labels", {})
            
            hpa_info = {
                "name": hpa_name,
                "namespace": hpa_namespace,
                "min_replicas": hpa["spec"].get("minReplicas", 1),
                "max_replicas": hpa["spec"].get("maxReplicas", 10),
                "current_replicas": hpa.get("status", {}).get("currentReplicas", 0),
                "desired_replicas": hpa.get("status", {}).get("desiredReplicas", 0),
                "metrics": hpa["spec"].get("metrics", []),
                "target_deployment": hpa["spec"].get("scaleTargetRef", {}).get("name", ""),
                "managed_by": labels.get("app.kubernetes.io/managed-by", "unknown")
            }
            
            # Categorize HPA
            if "keda" in hpa_info["managed_by"]:
                hpa_comparison["keda_hpas"].append(hpa_info)
            elif hpa_namespace == "kube-system":
                hpa_comparison["system_hpas"].append(hpa_info)
            else:
                hpa_comparison["standard_hpas"].append(hpa_info)
    
    except json.JSONDecodeError:
        pass
    
    return hpa_comparison

def get_external_metrics(namespace: str = "default") -> List[Dict]:
    """Get available external metrics from KEDA."""
    metrics = []
    
    success, output = run_kubectl('get --raw "/apis/external.metrics.k8s.io/v1beta1" | jq -r \'.resources[]?.name // empty\'')
    if not success:
        return metrics
    
    metric_names = output.split('\n') if output else []
    
    for metric_name in metric_names:
        if metric_name.strip():
            # Try to get metric value
            success, metric_output = run_kubectl(f'get --raw "/apis/external.metrics.k8s.io/v1beta1/namespaces/{namespace}/{metric_name.strip()}" | jq -r \'.items[]?.value // "0"\'')
            
            metric_info = {
                "name": metric_name.strip(),
                "namespace": namespace,
                "value": metric_output.strip() if success else "unavailable"
            }
            metrics.append(metric_info)
    
    return metrics

def get_service_bus_info() -> Dict:
    """Get Azure Service Bus queue information if available."""
    sb_info = {
        "available": False,
        "queues": []
    }
    
    # Try to get Service Bus namespaces
    success, output = run_az_command("servicebus namespace list --query '[].{name:name,resourceGroup:resourceGroup}' -o json")
    if not success:
        return sb_info
    
    try:
        namespaces = json.loads(output)
        sb_info["available"] = True
        
        for ns in namespaces:
            ns_name = ns.get("name", "")
            rg_name = ns.get("resourceGroup", "")
            
            # Get queues in this namespace
            queue_success, queue_output = run_az_command(f"servicebus queue list --namespace-name {ns_name} --resource-group {rg_name} --query '[].{{name:name,messageCount:messageCount}}' -o json")
            if queue_success:
                try:
                    queues = json.loads(queue_output)
                    for queue in queues:
                        queue_info = {
                            "namespace": ns_name,
                            "name": queue.get("name", ""),
                            "message_count": queue.get("messageCount", 0),
                            "resource_group": rg_name
                        }
                        sb_info["queues"].append(queue_info)
                except json.JSONDecodeError:
                    pass
    
    except json.JSONDecodeError:
        pass
    
    return sb_info

def analyze_scaling_behavior(scaledobjects: List[Dict], hpa_comparison: Dict) -> Dict:
    """Analyze current scaling behavior and provide insights."""
    analysis = {
        "scale_to_zero_active": False,
        "scaling_events": [],
        "efficiency_metrics": {},
        "predictions": []
    }
    
    # Check for scale-to-zero scenarios
    for so in scaledobjects:
        if so["min_replicas"] == 0:
            analysis["scale_to_zero_active"] = True
            
            # Find corresponding HPA
            for keda_hpa in hpa_comparison["keda_hpas"]:
                if so["target_deployment"] == keda_hpa["target_deployment"]:
                    current_replicas = keda_hpa["current_replicas"]
                    
                    prediction = {
                        "scaledobject": so["name"],
                        "deployment": so["target_deployment"],
                        "current_replicas": current_replicas,
                        "status": "scaled-to-zero" if current_replicas == 0 else "active"
                    }
                    
                    # Add trigger-specific predictions
                    for trigger in so["triggers"]:
                        if trigger["type"] == "azure-servicebus":
                            message_count = trigger["metadata"].get("messageCount", "5")
                            prediction["trigger_type"] = "Service Bus"
                            prediction["scaling_threshold"] = f"{message_count} messages per pod"
                    
                    analysis["predictions"].append(prediction)
    
    return analysis

def print_keda_analysis(namespace: str = "default", scaledobject_name: str = None):
    """Print comprehensive KEDA analysis for demonstrations."""
    print("=" * 80)
    print("KEDA EVENT-DRIVEN AUTOSCALING MONITOR")
    print("=" * 80)
    print(f"Namespace: {namespace}")
    print(f"Analysis Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # KEDA Health Check
    print("KEDA COMPONENT HEALTH")
    print("-" * 60)
    keda_health = check_keda_health()
    
    if keda_health["keda_installed"]:
        print(f"✅ KEDA Installed: Version {keda_health['keda_version']}")
        print(f"✅ External Metrics API: {'Available' if keda_health['external_metrics_api'] else 'Unavailable'}")
        
        for component, info in keda_health["components"].items():
            status_icon = "✅" if info["ready"] else "❌"
            print(f"{status_icon} {component}: {info['status']}")
    else:
        print("❌ KEDA not installed or not running")
        return
    
    print()
    
    # ScaledObjects Analysis
    print("SCALEDOBJECTS ANALYSIS")
    print("-" * 60)
    scaledobjects = get_scaledobjects_info(namespace)
    
    if not scaledobjects:
        print("❌ No ScaledObjects found in namespace")
    else:
        for so in scaledobjects:
            if scaledobject_name and so["name"] != scaledobject_name:
                continue
                
            print(f"\nScaledObject: {so['name']}")
            print(f"  Target Deployment: {so['target_deployment']}")
            print(f"  Scaling Range: {so['min_replicas']}-{so['max_replicas']} replicas")
            print(f"  Scale-to-Zero: {'✅ Enabled' if so['min_replicas'] == 0 else '❌ Disabled'}")
            print(f"  Generated HPA: {so['hpa_name']}")
            
            print("  Triggers:")
            for trigger in so["triggers"]:
                print(f"    • Type: {trigger['type']}")
                print(f"      Auth: {trigger['auth_ref']}")
                for key, value in trigger["metadata"].items():
                    print(f"      {key}: {value}")
            
            print("  Conditions:")
            for condition in so["conditions"]:
                status = condition.get("status", "Unknown")
                reason = condition.get("reason", "")
                message = condition.get("message", "")
                condition_type = condition.get("type", "")
                status_icon = "✅" if status == "True" else "❌"
                print(f"    {status_icon} {condition_type}: {reason}")
                if message:
                    print(f"       {message}")
    
    print()
    
    # HPA Comparison
    print("HPA COMPARISON: STANDARD vs KEDA")
    print("-" * 60)
    hpa_comparison = get_hpa_comparison(namespace)
    
    print(f"Standard HPAs: {len(hpa_comparison['standard_hpas'])}")
    for hpa in hpa_comparison['standard_hpas']:
        if namespace == "default" or hpa['namespace'] == namespace:
            metric_types = [m.get('type', 'unknown') for m in hpa['metrics']]
            print(f"  • {hpa['name']}: {hpa['current_replicas']}/{hpa['desired_replicas']} replicas, metrics: {', '.join(metric_types)}")
    
    print(f"\nKEDA HPAs: {len(hpa_comparison['keda_hpas'])}")
    for hpa in hpa_comparison['keda_hpas']:
        if namespace == "default" or hpa['namespace'] == namespace:
            metric_types = [m.get('type', 'unknown') for m in hpa['metrics']]
            print(f"  • {hpa['name']}: {hpa['current_replicas']}/{hpa['desired_replicas']} replicas")
            print(f"    Metrics: {', '.join(metric_types)}")
            
            # Show external metric details
            for metric in hpa['metrics']:
                if metric.get('type') == 'External':
                    external = metric.get('external', {})
                    metric_name = external.get('metric', {}).get('name', 'unknown')
                    target_value = external.get('target', {}).get('averageValue', 'unknown')
                    print(f"    External Metric: {metric_name} (target: {target_value})")
    
    print()
    
    # External Metrics
    print("EXTERNAL METRICS STATUS")
    print("-" * 60)
    external_metrics = get_external_metrics(namespace)
    
    if not external_metrics:
        print("❌ No external metrics available")
    else:
        for metric in external_metrics:
            print(f"• {metric['name']}: {metric['value']}")
    
    print()
    
    # Service Bus Information
    print("AZURE SERVICE BUS STATUS")
    print("-" * 60)
    sb_info = get_service_bus_info()
    
    if not sb_info["available"]:
        print("❌ Azure Service Bus not accessible or no queues found")
        print("   (Azure CLI not configured or no Service Bus resources)")
    else:
        print("✅ Azure Service Bus accessible")
        for queue in sb_info["queues"]:
            message_count = queue["message_count"]
            status_icon = "🔥" if message_count > 10 else "⚠️" if message_count > 0 else "✅"
            print(f"  {status_icon} Queue: {queue['namespace']}/{queue['name']} - {message_count} messages")
    
    print()
    
    # Scaling Analysis
    print("SCALING BEHAVIOR ANALYSIS")
    print("-" * 60)
    scaling_analysis = analyze_scaling_behavior(scaledobjects, hpa_comparison)
    
    if scaling_analysis["scale_to_zero_active"]:
        print("✅ Scale-to-Zero enabled and monitored")
    else:
        print("❌ No scale-to-zero configurations detected")
    
    print("\nCurrent Scaling Status:")
    for prediction in scaling_analysis["predictions"]:
        status_icon = "💤" if prediction["status"] == "scaled-to-zero" else "🏃"
        print(f"  {status_icon} {prediction['deployment']}: {prediction['current_replicas']} replicas ({prediction['status']})")
        if "trigger_type" in prediction:
            print(f"      Trigger: {prediction['trigger_type']} - {prediction['scaling_threshold']}")
    
    print()
    
    # Demo Insights
    print("KEDA DEMO INSIGHTS")
    print("-" * 60)
    
    if scaledobjects and hpa_comparison["keda_hpas"]:
        print("🎯 KEDA Architecture Working:")
        print("  • ScaledObject created → KEDA generates HPA")
        print("  • External metrics exposed → HPA uses for scaling decisions")
        print("  • Scale-to-zero managed → KEDA handles deployment scaling")
        
        # Check if there's active scaling
        active_scaling = any(p["status"] == "active" for p in scaling_analysis["predictions"])
        if active_scaling:
            print("\n📈 Active Scaling Detected:")
            print("  • Messages in queue → KEDA detecting load")
            print("  • HPA calculating desired replicas")
            print("  • Pods scaling based on external metrics")
        else:
            print("\n💤 Scale-to-Zero State:")
            print("  • No messages in queue → KEDA scaled to zero")
            print("  • Resource efficient → No unnecessary pods running")
            print("  • Event-driven → Will scale up when work arrives")
    else:
        print("❌ KEDA demonstration not properly configured")
        print("   Check ScaledObject and TriggerAuthentication setup")
    
    print("\n" + "=" * 80)

def main():
    """Main function to run KEDA monitoring analysis."""
    namespace = "default"
    scaledobject_name = None
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        namespace = sys.argv[1]
    if len(sys.argv) > 2:
        scaledobject_name = sys.argv[2]
    
    # Check if kubectl is available
    success, _ = run_kubectl("version --client=true")
    if not success:
        print("❌ kubectl is not available or not configured")
        print("Please ensure kubectl is installed and configured to access your cluster")
        sys.exit(1)
    
    # Run the analysis
    print_keda_analysis(namespace, scaledobject_name)

if __name__ == "__main__":
    main()