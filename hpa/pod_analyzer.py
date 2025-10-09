#!/usr/bin/env python3

"""
Kubernetes Pod Analyzer for HPA Demonstrations

This script analyzes pod resource usage, allocation, and scaling behavior to help
understand HPA scaling decisions. It provides detailed insights into why and when
HPA adds or removes pods from a deployment.

Features:
- Pod resource usage vs requests/limits analysis
- HPA scaling trigger identification
- Load distribution across pods
- Scaling efficiency metrics
- Real-time scaling predictions

Author: Generated for AKS HPA Demonstration
Usage: python3 pod_analyzer.py [deployment-name] [namespace]
"""

import subprocess
import json
import sys
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

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
        elif value.endswith('K'):
            return float(value[:-1]) * 1000
        elif value.endswith('M'):
            return float(value[:-1]) * 1000000
        elif value.endswith('G'):
            return float(value[:-1]) * 1000000000
        elif value.endswith('T'):
            return float(value[:-1]) * 1000000000000
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
    if bytes_val >= 1024**4:
        return f"{bytes_val / (1024**4):.2f}Ti"
    elif bytes_val >= 1024**3:
        return f"{bytes_val / (1024**3):.2f}Gi"
    elif bytes_val >= 1024**2:
        return f"{bytes_val / (1024**2):.2f}Mi"
    elif bytes_val >= 1024:
        return f"{bytes_val / 1024:.2f}Ki"
    else:
        return f"{int(bytes_val)}B"

def get_pod_info(deployment_name: str, namespace: str = "default") -> Dict:
    """Get detailed information about pods in a deployment."""
    pod_info = {
        "pods": [],
        "total_pods": 0,
        "running_pods": 0,
        "pending_pods": 0,
        "failed_pods": 0
    }
    
    # Get pods for the deployment
    success, output = run_kubectl(f"get pods -l app={deployment_name} -n {namespace} -o json")
    if not success:
        print(f"Error getting pods: {output}")
        return pod_info
    
    try:
        pods_data = json.loads(output)
        for pod in pods_data.get("items", []):
            pod_name = pod["metadata"]["name"]
            pod_status = pod["status"]["phase"]
            node_name = pod["spec"].get("nodeName", "Not scheduled")
            
            # Get resource requests and limits
            containers = pod["spec"].get("containers", [])
            total_cpu_request = 0
            total_memory_request = 0
            total_cpu_limit = 0
            total_memory_limit = 0
            
            for container in containers:
                resources = container.get("resources", {})
                requests = resources.get("requests", {})
                limits = resources.get("limits", {})
                
                total_cpu_request += parse_resource_unit(requests.get("cpu", "0"), "cpu")
                total_memory_request += parse_resource_unit(requests.get("memory", "0"), "memory")
                total_cpu_limit += parse_resource_unit(limits.get("cpu", "0"), "cpu")
                total_memory_limit += parse_resource_unit(limits.get("memory", "0"), "memory")
            
            # Get creation time
            creation_time = pod["metadata"]["creationTimestamp"]
            
            pod_info["pods"].append({
                "name": pod_name,
                "status": pod_status,
                "node": node_name,
                "cpu_request": total_cpu_request,
                "memory_request": total_memory_request,
                "cpu_limit": total_cpu_limit,
                "memory_limit": total_memory_limit,
                "creation_time": creation_time,
                "age": calculate_age(creation_time)
            })
            
            pod_info["total_pods"] += 1
            if pod_status == "Running":
                pod_info["running_pods"] += 1
            elif pod_status == "Pending":
                pod_info["pending_pods"] += 1
            elif pod_status in ["Failed", "Error"]:
                pod_info["failed_pods"] += 1
    
    except json.JSONDecodeError:
        print("Error parsing pod JSON data")
    
    return pod_info

def get_pod_metrics(deployment_name: str, namespace: str = "default") -> Dict:
    """Get current resource usage metrics for pods."""
    metrics = {}
    
    # Get pod metrics from metrics server
    success, output = run_kubectl(f"top pods -l app={deployment_name} -n {namespace} --no-headers")
    if not success:
        print(f"Warning: Could not get pod metrics: {output}")
        return metrics
    
    for line in output.split('\n'):
        if line.strip():
            parts = line.split()
            if len(parts) >= 3:
                pod_name = parts[0]
                cpu_usage = parse_resource_unit(parts[1], "cpu")
                memory_usage = parse_resource_unit(parts[2], "memory")
                
                metrics[pod_name] = {
                    "cpu_usage": cpu_usage,
                    "memory_usage": memory_usage
                }
    
    return metrics

def get_hpa_info(deployment_name: str, namespace: str = "default") -> Dict:
    """Get HPA information for the deployment."""
    hpa_info = {
        "exists": False,
        "current_replicas": 0,
        "desired_replicas": 0,
        "min_replicas": 0,
        "max_replicas": 0,
        "target_cpu": 0,
        "current_cpu": 0,
        "conditions": [],
        "last_scale_time": None
    }
    
    # Try to find HPA for this deployment
    success, output = run_kubectl(f"get hpa -n {namespace} -o json")
    if not success:
        return hpa_info
    
    try:
        hpa_data = json.loads(output)
        for hpa in hpa_data.get("items", []):
            target_ref = hpa["spec"]["scaleTargetRef"]
            if (target_ref.get("name") == deployment_name or 
                target_ref.get("name") in [f"{deployment_name}-hpa", f"{deployment_name}_hpa"]):
                
                hpa_info["exists"] = True
                hpa_info["current_replicas"] = hpa["status"].get("currentReplicas", 0)
                hpa_info["desired_replicas"] = hpa["status"].get("desiredReplicas", 0)
                hpa_info["min_replicas"] = hpa["spec"].get("minReplicas", 0)
                hpa_info["max_replicas"] = hpa["spec"].get("maxReplicas", 0)
                
                # Get target CPU utilization
                metrics = hpa["spec"].get("metrics", [])
                for metric in metrics:
                    if metric["type"] == "Resource" and metric["resource"]["name"] == "cpu":
                        hpa_info["target_cpu"] = metric["resource"]["target"].get("averageUtilization", 0)
                
                # Get current CPU utilization
                current_metrics = hpa["status"].get("currentMetrics", [])
                for metric in current_metrics:
                    if metric["type"] == "Resource" and metric["resource"]["name"] == "cpu":
                        hpa_info["current_cpu"] = metric["resource"]["current"].get("averageUtilization", 0)
                
                # Get conditions
                hpa_info["conditions"] = hpa["status"].get("conditions", [])
                
                # Get last scale time
                hpa_info["last_scale_time"] = hpa["status"].get("lastScaleTime")
                
                break
    
    except json.JSONDecodeError:
        pass
    
    return hpa_info

def calculate_age(creation_time: str) -> str:
    """Calculate age from Kubernetes timestamp."""
    try:
        # Parse ISO format timestamp
        if creation_time.endswith('Z'):
            creation_time = creation_time[:-1] + '+00:00'
        
        from datetime import datetime, timezone
        created = datetime.fromisoformat(creation_time.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        diff = now - created
        
        days = diff.days
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60
        
        if days > 0:
            return f"{days}d{hours}h"
        elif hours > 0:
            return f"{hours}h{minutes}m"
        else:
            return f"{minutes}m"
    except:
        return "unknown"

def calculate_scaling_prediction(hpa_info: Dict, pod_metrics: Dict, pod_info: Dict) -> Dict:
    """Predict when scaling might occur based on current metrics."""
    prediction = {
        "scale_up_likely": False,
        "scale_down_likely": False,
        "recommendation": "No scaling needed",
        "reason": "",
        "confidence": "medium"
    }
    
    if not hpa_info["exists"]:
        prediction["recommendation"] = "No HPA configured"
        prediction["reason"] = "Deploy HPA to enable automatic scaling"
        return prediction
    
    current_cpu = hpa_info["current_cpu"]
    target_cpu = hpa_info["target_cpu"]
    current_replicas = hpa_info["current_replicas"]
    max_replicas = hpa_info["max_replicas"]
    min_replicas = hpa_info["min_replicas"]
    
    if current_cpu == 0:
        prediction["recommendation"] = "Waiting for metrics"
        prediction["reason"] = "CPU metrics not yet available"
        return prediction
    
    # Scale up prediction
    if current_cpu > target_cpu * 1.1:  # 10% above target
        if current_replicas < max_replicas:
            prediction["scale_up_likely"] = True
            prediction["recommendation"] = "Scale up expected"
            prediction["reason"] = f"CPU usage ({current_cpu}%) > target ({target_cpu}%) + 10%"
            if current_cpu > target_cpu * 1.5:
                prediction["confidence"] = "high"
        else:
            prediction["recommendation"] = "At max replicas"
            prediction["reason"] = f"Cannot scale beyond {max_replicas} replicas"
    
    # Scale down prediction
    elif current_cpu < target_cpu * 0.5:  # 50% below target
        if current_replicas > min_replicas:
            prediction["scale_down_likely"] = True
            prediction["recommendation"] = "Scale down possible"
            prediction["reason"] = f"CPU usage ({current_cpu}%) < 50% of target ({target_cpu}%)"
            prediction["confidence"] = "low"  # Scale down is slower
        else:
            prediction["recommendation"] = "At min replicas"
            prediction["reason"] = f"Cannot scale below {min_replicas} replicas"
    
    else:
        prediction["recommendation"] = "Stable"
        prediction["reason"] = f"CPU usage ({current_cpu}%) near target ({target_cpu}%)"
    
    return prediction

def analyze_load_distribution(pod_metrics: Dict, pod_info: Dict) -> Dict:
    """Analyze how load is distributed across pods."""
    distribution = {
        "total_pods": len(pod_info["pods"]),
        "pods_with_metrics": len(pod_metrics),
        "cpu_variance": 0,
        "memory_variance": 0,
        "load_balance_score": "good",
        "hotspots": []
    }
    
    if len(pod_metrics) < 2:
        return distribution
    
    # Calculate CPU usage variance
    cpu_usages = [metrics["cpu_usage"] for metrics in pod_metrics.values()]
    avg_cpu = sum(cpu_usages) / len(cpu_usages)
    cpu_variance = sum((x - avg_cpu) ** 2 for x in cpu_usages) / len(cpu_usages)
    distribution["cpu_variance"] = cpu_variance
    
    # Calculate memory usage variance
    memory_usages = [metrics["memory_usage"] for metrics in pod_metrics.values()]
    avg_memory = sum(memory_usages) / len(memory_usages)
    memory_variance = sum((x - avg_memory) ** 2 for x in memory_usages) / len(memory_usages)
    distribution["memory_variance"] = memory_variance
    
    # Identify hotspots (pods using significantly more resources)
    for pod_name, metrics in pod_metrics.items():
        if metrics["cpu_usage"] > avg_cpu * 1.5:
            distribution["hotspots"].append({
                "pod": pod_name,
                "type": "cpu",
                "usage": metrics["cpu_usage"],
                "average": avg_cpu
            })
        if metrics["memory_usage"] > avg_memory * 1.5:
            distribution["hotspots"].append({
                "pod": pod_name,
                "type": "memory",
                "usage": metrics["memory_usage"],
                "average": avg_memory
            })
    
    # Calculate load balance score
    if cpu_variance < 0.001 and memory_variance < (1024 * 1024 * 10):  # Low variance
        distribution["load_balance_score"] = "excellent"
    elif cpu_variance < 0.01 and memory_variance < (1024 * 1024 * 50):
        distribution["load_balance_score"] = "good"
    elif cpu_variance < 0.05 and memory_variance < (1024 * 1024 * 100):
        distribution["load_balance_score"] = "fair"
    else:
        distribution["load_balance_score"] = "poor"
    
    return distribution

def print_pod_analysis(deployment_name: str, namespace: str = "default"):
    """Print comprehensive pod analysis for HPA demonstrations."""
    print("=" * 80)
    print("KUBERNETES POD ANALYZER FOR HPA DEMONSTRATIONS")
    print("=" * 80)
    print(f"Deployment: {deployment_name}")
    print(f"Namespace: {namespace}")
    print(f"Analysis Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Get all data
    pod_info = get_pod_info(deployment_name, namespace)
    pod_metrics = get_pod_metrics(deployment_name, namespace)
    hpa_info = get_hpa_info(deployment_name, namespace)
    
    if pod_info["total_pods"] == 0:
        print(f"❌ No pods found for deployment '{deployment_name}' in namespace '{namespace}'")
        print("\nTroubleshooting:")
        print("1. Check deployment name and namespace")
        print("2. Verify deployment exists: kubectl get deployment")
        print("3. Check if pods use different labels")
        return
    
    # HPA Status Section
    print("HPA STATUS")
    print("-" * 60)
    if hpa_info["exists"]:
        print(f"✅ HPA Active: {hpa_info['current_replicas']}/{hpa_info['desired_replicas']} replicas")
        print(f"   Range: {hpa_info['min_replicas']}-{hpa_info['max_replicas']} replicas")
        print(f"   Target CPU: {hpa_info['target_cpu']}%")
        print(f"   Current CPU: {hpa_info['current_cpu']}%")
        
        if hpa_info['current_cpu'] > 0:
            cpu_status = "🔥" if hpa_info['current_cpu'] > hpa_info['target_cpu'] * 1.2 else \
                        "⚠️" if hpa_info['current_cpu'] > hpa_info['target_cpu'] else "✅"
            print(f"   CPU Status: {cpu_status}")
        
        if hpa_info["last_scale_time"]:
            print(f"   Last Scale: {hpa_info['last_scale_time']}")
    else:
        print("❌ No HPA found for this deployment")
        print("   💡 Create HPA: kubectl autoscale deployment {deployment_name} --cpu-percent=50 --min=1 --max=10")
    
    print()
    
    # Pod Overview Section
    print("POD OVERVIEW")
    print("-" * 60)
    print(f"Total Pods: {pod_info['total_pods']}")
    print(f"Running: {pod_info['running_pods']}, Pending: {pod_info['pending_pods']}, Failed: {pod_info['failed_pods']}")
    print()
    
    # Individual Pod Analysis
    print("INDIVIDUAL POD ANALYSIS")
    print("-" * 60)
    
    for pod in pod_info["pods"]:
        pod_name = pod["name"]
        print(f"\nPod: {pod_name}")
        print(f"  Status: {pod['status']} | Node: {pod['node']} | Age: {pod['age']}")
        
        # Resource requests/limits
        print(f"  CPU Request: {format_cpu(pod['cpu_request'])}")
        if pod['cpu_limit'] > 0:
            print(f"  CPU Limit: {format_cpu(pod['cpu_limit'])}")
        print(f"  Memory Request: {format_memory(pod['memory_request'])}")
        if pod['memory_limit'] > 0:
            print(f"  Memory Limit: {format_memory(pod['memory_limit'])}")
        
        # Current usage
        if pod_name in pod_metrics:
            metrics = pod_metrics[pod_name]
            cpu_usage = metrics["cpu_usage"]
            memory_usage = metrics["memory_usage"]
            
            print(f"  Current CPU: {format_cpu(cpu_usage)}", end="")
            if pod['cpu_request'] > 0:
                cpu_percent = (cpu_usage / pod['cpu_request']) * 100
                print(f" ({cpu_percent:.1f}% of request)", end="")
                if cpu_percent > 80:
                    print(" 🔥", end="")
                elif cpu_percent > 60:
                    print(" ⚠️", end="")
            print()
            
            print(f"  Current Memory: {format_memory(memory_usage)}", end="")
            if pod['memory_request'] > 0:
                memory_percent = (memory_usage / pod['memory_request']) * 100
                print(f" ({memory_percent:.1f}% of request)", end="")
                if memory_percent > 80:
                    print(" 🔥", end="")
                elif memory_percent > 60:
                    print(" ⚠️", end="")
            print()
        else:
            print("  Current Usage: No metrics available")
    
    print("\n" + "=" * 80)
    
    # Load Distribution Analysis
    if len(pod_metrics) > 1:
        distribution = analyze_load_distribution(pod_metrics, pod_info)
        print("LOAD DISTRIBUTION ANALYSIS")
        print("-" * 60)
        print(f"Load Balance Score: {distribution['load_balance_score'].upper()}")
        
        if distribution["hotspots"]:
            print("Resource Hotspots Detected:")
            for hotspot in distribution["hotspots"]:
                avg_val = hotspot["average"]
                current_val = hotspot["usage"]
                if hotspot["type"] == "cpu":
                    print(f"  🔥 {hotspot['pod']}: {format_cpu(current_val)} (avg: {format_cpu(avg_val)})")
                else:
                    print(f"  🔥 {hotspot['pod']}: {format_memory(current_val)} (avg: {format_memory(avg_val)})")
        else:
            print("✅ No resource hotspots detected")
        
        print()
    
    # Scaling Prediction
    if hpa_info["exists"]:
        prediction = calculate_scaling_prediction(hpa_info, pod_metrics, pod_info)
        print("SCALING PREDICTION")
        print("-" * 60)
        print(f"Prediction: {prediction['recommendation']}")
        print(f"Reason: {prediction['reason']}")
        print(f"Confidence: {prediction['confidence'].upper()}")
        
        if prediction["scale_up_likely"]:
            print("📈 Scale-up likely in next 15-60 seconds")
        elif prediction["scale_down_likely"]:
            print("📉 Scale-down possible in 5+ minutes (stabilization window)")
        
        print()
    
    # Summary for HPA Demo
    print("HPA DEMONSTRATION INSIGHTS")
    print("-" * 60)
    
    if hpa_info["exists"] and hpa_info["current_cpu"] > 0:
        target = hpa_info["target_cpu"]
        current = hpa_info["current_cpu"]
        
        if current > target * 1.1:
            print("🎯 SCALING TRIGGER: CPU usage above target + threshold")
            print(f"   Current: {current}% | Target: {target}% | Threshold: ~{target * 1.1:.1f}%")
            print("   💡 This is why HPA is adding pods!")
        elif current < target * 0.5:
            print("🎯 SCALE-DOWN OPPORTUNITY: CPU usage well below target")
            print(f"   Current: {current}% | Target: {target}% | Scale-down threshold: ~{target * 0.5:.1f}%")
            print("   💡 HPA may remove pods after stabilization window")
        else:
            print("🎯 STABLE STATE: CPU usage near target")
            print(f"   Current: {current}% | Target: {target}%")
            print("   ✅ HPA is maintaining optimal pod count")
    
    # Resource efficiency
    if pod_metrics:
        total_requested_cpu = sum(pod['cpu_request'] for pod in pod_info['pods'])
        total_used_cpu = sum(metrics['cpu_usage'] for metrics in pod_metrics.values())
        
        if total_requested_cpu > 0:
            efficiency = (total_used_cpu / total_requested_cpu) * 100
            print(f"\nResource Efficiency: {efficiency:.1f}%")
            print(f"  Requested: {format_cpu(total_requested_cpu)}")
            print(f"  Actually Using: {format_cpu(total_used_cpu)}")
            
            if efficiency < 30:
                print("  💡 Consider reducing CPU requests to improve efficiency")
            elif efficiency > 90:
                print("  ⚠️ Consider increasing CPU requests or limits")
    
    print("\n" + "=" * 80)

def main():
    """Main function to run pod analysis."""
    deployment_name = "php-apache"  # Default for HPA demo
    namespace = "default"
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        deployment_name = sys.argv[1]
    if len(sys.argv) > 2:
        namespace = sys.argv[2]
    
    # Check if kubectl is available
    success, _ = run_kubectl("version --client=true")
    if not success:
        print("❌ kubectl is not available or not configured")
        print("Please ensure kubectl is installed and configured to access your cluster")
        sys.exit(1)
    
    # Run the analysis
    print_pod_analysis(deployment_name, namespace)

if __name__ == "__main__":
    main()