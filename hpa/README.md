# AKS Horizontal Pod Autoscaler (HPA) Demonstration Guide

## Overview

The Horizontal Pod Autoscaler (HPA) automatically scales the number of pods in a deployment based on observed metrics like CPU utilization, memory usage, or custom metrics. This guide demonstrates HPA functionality using real workload generation and monitoring with Azure Managed Prometheus and Grafana.

## Enable Azure Managed Prometheus and Grafana Monitoring

### Step 0: Configure Azure Monitor for AKS

```bash
# Set environment variables
export RESOURCE_GROUP="democlusterrg"
export CLUSTER="democluster"

# Get Azure Monitor Workspace and Grafana resource IDs
export amwrid=$(az monitor account show --resource-group infrarg --name amwforaks --query id -o tsv)
export amgrid=$(az grafana show --resource-group infrarg --name amgforaks --query id -o tsv)

echo "Azure Monitor Workspace ID: $amwrid"
echo "Grafana Resource ID: $amgrid"

# Enable Azure Monitor metrics (Prometheus) on the cluster
# Note: If you see "RoleAssignmentExists" error, this is just a warning and can be ignored
az aks update \
  --enable-azure-monitor-metrics \
  --name $CLUSTER \
  --resource-group $RESOURCE_GROUP \
  --azure-monitor-workspace-resource-id $amwrid

# Link Grafana to the cluster (run separately after the above completes)
az aks update \
  --name $CLUSTER \
  --resource-group $RESOURCE_GROUP \
  --grafana-resource-id $amgrid

# Verify Azure Monitor is enabled
az aks show \
  --name $CLUSTER \
  --resource-group $RESOURCE_GROUP \
  --query "azureMonitorProfile" -o yaml

# This should show the Azure Monitor Workspace configuration
```

**Note**: The "RoleAssignmentExists" error is a known issue and can be safely ignored. The configuration will still be applied successfully.

**Cluster Configuration**:
- **Cluster Name**: `democluster`
- **Resource Group**: `democlusterrg`
- **Monitoring**: Azure Managed Prometheus + Azure Managed Grafana

## HPA Architecture and Components

### How HPA Works

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        HPA Architecture Overview                         │
└─────────────────────────────────────────────────────────────────────────┘

                    ┌──────────────────────────┐
                    │   HPA Controller         │
                    │  (kube-controller-mgr)   │
                    │                          │
                    │  - Evaluates metrics     │
                    │  - Makes scaling         │
                    │    decisions every 15s   │
                    └────────┬─────────────────┘
                             │
                             │ Queries metrics
                             ↓
                    ┌──────────────────────────┐
                    │   Metrics Server         │
                    │  (metrics.k8s.io)        │
                    │                          │
                    │  - Collects resource     │
                    │    usage from kubelets   │
                    │  - Provides CPU/Memory   │
                    │    metrics via API       │
                    └────────┬─────────────────┘
                             │
                             │ Scrapes metrics
                             ↓
            ┌────────────────────────────────────┐
            │         Kubelet (on each node)      │
            │                                     │
            │  - cAdvisor: Container metrics      │
            │  - Reports pod resource usage       │
            └────────┬───────────────────────┬────┘
                     │                       │
                     ↓                       ↓
            ┌─────────────────┐    ┌─────────────────┐
            │   Pod 1         │    │   Pod 2         │
            │  (Target App)   │    │  (Target App)   │
            └─────────────────┘    └─────────────────┘


Parallel Monitoring Flow:

                    ┌──────────────────────────┐
                    │ Azure Managed Prometheus │
                    │                          │
                    │  - Scrapes metrics from  │
                    │    pods and nodes        │
                    │  - Long-term storage     │
                    └────────┬─────────────────┘
                             │
                             │ Visualizes
                             ↓
                    ┌──────────────────────────┐
                    │  Azure Managed Grafana   │
                    │                          │
                    │  - Real-time dashboards  │
                    │  - CPU/Memory graphs     │
                    │  - Custom queries        │
                    └──────────────────────────┘
```

### Key Components

1. **HPA Controller**: 
   - Runs in `kube-controller-manager`
   - Checks metrics every 15 seconds (default)
   - Calculates desired replica count
   - Updates Deployment/ReplicaSet

2. **Metrics Server**: 
   - **CRITICAL DEPENDENCY** for HPA
   - Collects CPU and memory metrics from kubelets
   - Provides Metrics API (`metrics.k8s.io`)
   - Required for resource-based autoscaling

3. **Kubelet/cAdvisor**: 
   - Runs on every node
   - Monitors container resource usage
   - Reports metrics to Metrics Server

4. **Azure Managed Prometheus**:
   - Scrapes additional metrics
   - Long-term metric storage
   - Enables advanced monitoring

5. **Azure Managed Grafana**:
   - Visualizes metrics in real-time
   - Pre-built and custom dashboards
   - Query Prometheus data

### HPA Scaling Formula

```
desiredReplicas = ceil[currentReplicas × (currentMetricValue / targetMetricValue)]

Example:
- Current replicas: 2
- Current CPU usage: 80%
- Target CPU usage: 50%
- Desired replicas: ceil[2 × (80/50)] = ceil[3.2] = 4
```

## Prerequisites Verification

```bash
# Set environment variables
export CLUSTER_NAME="democluster"
export RG_NAME="democlusterrg"

# Get cluster credentials
az aks get-credentials \
    --name $CLUSTER_NAME \
    --resource-group $RG_NAME \
    --overwrite-existing

# Verify cluster connection
kubectl cluster-info
kubectl get nodes
```

## Step 1: Verify Metrics Server Installation

**Why This Matters**: HPA cannot function without Metrics Server. This is a critical dependency.

```bash
# Check if Metrics Server is installed
kubectl get deployment metrics-server -n kube-system

# If not found, Metrics Server needs to be installed
# On AKS, Metrics Server is typically pre-installed

# Verify Metrics Server is providing metrics
kubectl top nodes

# Check if pod metrics are available
kubectl top pods -A

# Verify Metrics API is registered
kubectl get apiservices | grep metrics

# Should show:
# v1beta1.metrics.k8s.io    kube-system/metrics-server   True
```


## Step 2: Deploy Target Application (to be scaled)

### Deploy PHP-Apache Application

This is the application that HPA will scale based on CPU usage.

```bash
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: php-apache
  labels:
    app: php-apache
spec:
  replicas: 1
  selector:
    matchLabels:
      app: php-apache
  template:
    metadata:
      labels:
        app: php-apache
    spec:
      containers:
      - name: php-apache
        image: registry.k8s.io/hpa-example
        ports:
        - containerPort: 80
        resources:
          requests:
            cpu: 200m      # Request 200 millicores (0.2 CPU)
            memory: 128Mi
          limits:
            cpu: 500m      # Limit to 500 millicores (0.5 CPU)
            memory: 256Mi
---
apiVersion: v1
kind: Service
metadata:
  name: php-apache
  labels:
    app: php-apache
spec:
  type: ClusterIP
  ports:
  - port: 80
    targetPort: 80
  selector:
    app: php-apache
EOF

# Verify deployment
kubectl get deployment php-apache
kubectl get pods -l app=php-apache
kubectl get svc php-apache

# Test the service internally
kubectl run test-curl --image=curlimages/curl -i --rm --restart=Never -- curl http://php-apache
```

## Step 3: Create Horizontal Pod Autoscaler

### Create HPA with CPU Target

```bash
# Create HPA that scales based on CPU utilization
kubectl apply -f - <<EOF
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: php-apache-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: php-apache
  minReplicas: 1
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 50  # Target 50% CPU utilization
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300  # Wait 5 minutes before scaling down
      policies:
      - type: Percent
        value: 50
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0    # Scale up immediately
      policies:
      - type: Percent
        value: 100
        periodSeconds: 30
      - type: Pods
        value: 2
        periodSeconds: 30
      selectPolicy: Max
EOF

# Verify HPA is created
kubectl get hpa php-apache-hpa

# Watch HPA status (keep this running in a terminal)
watch kubectl get hpa php-apache-hpa
```

### Understanding HPA Status

```bash
# Get detailed HPA information
kubectl describe hpa php-apache-hpa

# Check current metrics
kubectl get hpa php-apache-hpa -o yaml

# Important fields to observe:
# - currentReplicas: Current number of pods
# - desiredReplicas: Target number of pods
# - currentMetrics: Current CPU/memory usage
# - conditions: HPA status and any issues
```

## Step 4: Monitor Before Load Testing

### Terminal Setup for Monitoring

Open **4 terminals** for comprehensive monitoring:

**Terminal 1: Watch HPA**
```bash
watch -n 2 kubectl get hpa php-apache-hpa
```

**Terminal 2: Watch Pods**
```bash
watch -n 2 "kubectl get pods -l app=php-apache -o wide"
```

**Terminal 3: Watch Resource Usage**
```bash
watch -n 2 "kubectl top pods -l app=php-apache"
```

**Terminal 4: HPA Events**
```bash
kubectl get events --watch --field-selector involvedObject.name=php-apache-hpa
```

### Initial State Verification

```bash
# Check current CPU usage (should be very low)
kubectl top pods -l app=php-apache

# Example output:
# NAME                          CPU(cores)   MEMORY(bytes)
# php-apache-xxxx               1m           10Mi

# Verify baseline metrics
kubectl get hpa php-apache-hpa -o yaml | grep -A 5 currentMetrics
```

## Step 5: Generate Load with Load Generator Pod

### Deploy Load Generator

This pod will simulate users hitting the php-apache service to increase CPU usage.

```bash
# Create load generator deployment
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: load-generator
  labels:
    app: load-generator
spec:
  replicas: 1
  selector:
    matchLabels:
      app: load-generator
  template:
    metadata:
      labels:
        app: load-generator
    spec:
      containers:
      - name: load-generator
        image: busybox:latest
        command: ["/bin/sh"]
        args:
        - -c
        - |
          echo "Load generator starting..."
          echo "Target: http://php-apache"
          echo "Starting infinite loop to generate load..."
          while true; do
            wget -q -O- http://php-apache > /dev/null 2>&1
          done
        resources:
          requests:
            cpu: 100m
            memory: 64Mi
          limits:
            cpu: 200m
            memory: 128Mi
EOF

# Verify load generator is running
kubectl get pods -l app=load-generator
kubectl logs -l app=load-generator -f
```

### Alternative: Multiple Load Generators for Higher Load

```bash
# Scale up load generator for more intensive load
kubectl scale deployment load-generator --replicas=3

# Or create a more aggressive load generator
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: aggressive-load-generator
spec:
  replicas: 5
  selector:
    matchLabels:
      app: aggressive-load
  template:
    metadata:
      labels:
        app: aggressive-load
    spec:
      containers:
      - name: load
        image: busybox:latest
        command: ["/bin/sh", "-c"]
        args:
        - "while true; do for i in \$(seq 1 100); do wget -q -O- http://php-apache & done; sleep 0.1; done"
        resources:
          requests:
            cpu: 100m
            memory: 64Mi
EOF
```

## Step 6: Observe HPA Scaling Up

### Watch the Metrics Increase

```bash
# Monitor CPU usage increasing (Terminal 3 should show this)
kubectl top pods -l app=php-apache

# Expected progression:
# Time T+0:  CPU: 1-5m       (baseline)
# Time T+30: CPU: 150-250m   (load hitting)
# Time T+60: CPU: 200-400m   (sustained load)

# Watch HPA making scaling decisions
kubectl describe hpa php-apache-hpa

# Look for events like:
# "New size: 2; reason: cpu resource utilization (percentage of request) above target"
# "Successfully scaled deployment php-apache from 1 to 2"
```

### Key Observations for Participants

1. **Initial State**: 1 pod, low CPU (1-5%)
2. **Load Applied**: CPU increases to 80-100% of request (160-200m)
3. **HPA Decision**: Calculates need for more replicas
4. **Scaling Event**: New pods are created
5. **Load Distribution**: CPU usage distributes across pods
6. **Stable State**: Each pod at ~50% CPU (target achieved)

### Timeline of Events

```bash
# Get detailed event timeline
kubectl get events --sort-by='.lastTimestamp' | grep -E "php-apache|hpa"

# Typical timeline:
# T+0s:   Load generator starts
# T+15s:  HPA first check, CPU at 80%
# T+30s:  HPA decides to scale up
# T+35s:  New pod created (Pending)
# T+45s:  New pod running
# T+50s:  Load distributed across 2 pods
# T+60s:  CPU per pod drops to 50%
```

## Step 7: Monitor in Azure Managed Grafana

### Access Grafana Dashboard

```bash
# Get Grafana URL (if not already known)
az grafana list --resource-group $RG_NAME --output table

# Or check AKS monitoring settings
az aks show \
    --name $CLUSTER_NAME \
    --resource-group $RG_NAME \
    --query "azureMonitorProfile" -o yaml
```

### Pre-built Dashboard Queries

**Participants should view these in Grafana**:

1. **Pod CPU Usage**
   ```promql
   # Query for Grafana
   sum(rate(container_cpu_usage_seconds_total{namespace="default",pod=~"php-apache.*"}[5m])) by (pod)
   ```

2. **Pod Memory Usage**
   ```promql
   sum(container_memory_working_set_bytes{namespace="default",pod=~"php-apache.*"}) by (pod)
   ```

3. **HPA Replica Count**
   ```promql
   kube_horizontalpodautoscaler_status_current_replicas{horizontalpodautoscaler="php-apache-hpa"}
   ```

4. **HPA Desired Replicas**
   ```promql
   kube_horizontalpodautoscaler_status_desired_replicas{horizontalpodautoscaler="php-apache-hpa"}
   ```

5. **Request Rate to Service**
   ```promql
   rate(http_requests_total{service="php-apache"}[5m])
   ```

### Create Custom Grafana Dashboard

**Instructions for Participants**:

1. Open Azure Managed Grafana in browser
2. Create New Dashboard
3. Add Panel: "PHP Apache CPU Usage"
   - Query: `sum(rate(container_cpu_usage_seconds_total{namespace="default",pod=~"php-apache.*"}[5m])) by (pod)`
   - Visualization: Time series
4. Add Panel: "HPA Replicas"
   - Query: `kube_horizontalpodautoscaler_status_current_replicas{horizontalpodautoscaler="php-apache-hpa"}`
   - Visualization: Stat
5. Add Panel: "Pod Count Over Time"
   - Query: `count(kube_pod_info{namespace="default",pod=~"php-apache.*"})`
   - Visualization: Graph

### Key Metrics to Show Participants

```bash
# While load is running, show these queries in Grafana:

# 1. CPU Usage Per Pod (should show increase then distribution)
# 2. Total Pod Count (should show 1 → 2 → 3 → 4, etc.)
# 3. CPU Percentage vs Target (should converge to 50%)
# 4. Load Generator Request Rate (shows consistent load)
```

## Step 8: Demonstrate Scale-Down

### Stop Load Generation

```bash
# Delete load generator to stop traffic
kubectl delete deployment load-generator

# If using aggressive load generator
kubectl delete deployment aggressive-load-generator

# Verify load is stopped
kubectl top pods -l app=php-apache

# CPU should start dropping immediately
# Example:
# Time T+0:  CPU: 200m per pod (under load)
# Time T+30: CPU: 50m per pod (load stopped)
# Time T+60: CPU: 5m per pod (idle)
```

### Observe Scale-Down Behavior

```bash
# Watch HPA during scale-down (takes 5+ minutes)
watch kubectl get hpa php-apache-hpa

# Monitor pod count
watch "kubectl get pods -l app=php-apache | wc -l"

# Check HPA events for scale-down
kubectl get events --watch | grep -i "scale.*down"

# Note: Scale-down is intentionally slower than scale-up
# Default: 5 minutes stabilization window
```

### Scale-Down Timeline

```bash
# Typical scale-down timeline:
# T+0m:   Load stopped, CPU drops to 5-10%
# T+5m:   Stabilization window complete
# T+5m:   HPA decides to scale down
# T+6m:   Pod termination begins
# T+7m:   Pod removed, replica count decreases
# T+12m:  Another scale-down (if needed)
# T+15m:  Final state: back to 1 replica

# View scale-down events
kubectl describe hpa php-apache-hpa | grep -A 10 "Events"
```

## Step 9: Advanced HPA Demonstrations

### Demo 1: Memory-Based HPA

```bash
kubectl apply -f - <<EOF
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: php-apache-memory-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: php-apache
  minReplicas: 1
  maxReplicas: 5
  metrics:
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 70  # Target 70% memory utilization
EOF
```

### Demo 2: Multiple Metrics (CPU + Memory)

```bash
kubectl apply -f - <<EOF
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: php-apache-multi-metric-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: php-apache
  minReplicas: 1
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 50
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 70
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
      - type: Percent
        value: 100
        periodSeconds: 15
      - type: Pods
        value: 4
        periodSeconds: 15
      selectPolicy: Max
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 50
        periodSeconds: 60
EOF
```

### Demo 3: Custom Metrics (using Prometheus)

```bash
# Example HPA using custom metric from Prometheus
kubectl apply -f - <<EOF
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: php-apache-custom-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: php-apache
  minReplicas: 1
  maxReplicas: 10
  metrics:
  - type: Pods
    pods:
      metric:
        name: http_requests_per_second
      target:
        type: AverageValue
        averageValue: "1000"  # Scale at 1000 requests/sec per pod
EOF

# Note: Requires Prometheus adapter and custom metrics API
```

## Step 10: Troubleshooting and Monitoring Commands

### HPA Status and Debugging

```bash
# Get HPA status
kubectl get hpa

# Detailed HPA information
kubectl describe hpa php-apache-hpa

# Check HPA controller logs
kubectl logs -n kube-system -l component=kube-controller-manager | grep -i "horizontal"

# Verify Metrics Server is providing data
kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes
kubectl get --raw /apis/metrics.k8s.io/v1beta1/pods

# Check if metrics are available for specific pod
kubectl get --raw /apis/metrics.k8s.io/v1beta1/namespaces/default/pods/php-apache-xxxxx
```

### Common Issues and Solutions

```bash
# Issue: "unable to get metrics for resource cpu"
# Solution: Check Metrics Server
kubectl get deployment metrics-server -n kube-system
kubectl logs -n kube-system deployment/metrics-server

# Issue: "failed to get cpu utilization: missing request for cpu"
# Solution: Ensure pods have CPU requests defined
kubectl get deployment php-apache -o yaml | grep -A 5 resources

# Issue: HPA shows "unknown" for current CPU
# Solution: Wait 60 seconds for metrics to populate
# Or check if pods are running
kubectl get pods -l app=php-apache

# Issue: Scale-down not happening
# Solution: Check stabilization window
kubectl get hpa php-apache-hpa -o yaml | grep -A 10 behavior
```

### Performance Analysis

```bash
# Calculate scaling efficiency
START_TIME=$(date +%s)
# ... run load test ...
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
echo "Time to scale up: ${DURATION}s"

# Check scaling metrics
kubectl top pods -l app=php-apache --containers

# Analyze HPA decisions
kubectl get hpa php-apache-hpa -o json | jq '.status'

# View historical scaling events
kubectl get events --sort-by='.lastTimestamp' | grep -i "scaled"
```

## Step 11: Cleanup

```bash
# Delete HPA
kubectl delete hpa php-apache-hpa

# Delete load generator
kubectl delete deployment load-generator
kubectl delete deployment aggressive-load-generator 2>/dev/null || true

# Delete application
kubectl delete deployment php-apache
kubectl delete service php-apache

# Verify cleanup
kubectl get all -l app=php-apache
kubectl get all -l app=load-generator
kubectl get hpa
```

## Workshop Instructions for Participants

### Lab Exercise: Complete HPA Demo

**Duration**: 30-45 minutes

**Objectives**:
1. Understand HPA architecture and dependencies
2. Deploy and configure HPA
3. Generate load and observe scaling
4. Monitor with Grafana dashboards
5. Observe scale-down behavior

**Steps**:

1. **Setup** (5 minutes)
   - Verify Metrics Server: `kubectl top nodes`
   - Deploy php-apache application
   - Create HPA with 50% CPU target

2. **Baseline** (5 minutes)
   - Setup 4 monitoring terminals
   - Verify 1 pod running
   - Check CPU usage (should be ~1-5m)
   - Note baseline metrics

3. **Load Generation** (10 minutes)
   - Deploy load generator
   - Watch CPU increase in Terminal 3
   - Observe HPA scaling decisions in Terminal 1
   - Count pods increasing in Terminal 2
   - Note events in Terminal 4

4. **Grafana Monitoring** (10 minutes)
   - Open Azure Managed Grafana
   - Create dashboard with CPU and replica count
   - Run queries for pod metrics
   - Screenshot graphs showing scale-up

5. **Scale-Down** (10 minutes)
   - Delete load generator
   - Watch CPU drop immediately
   - Wait for 5-minute stabilization
   - Observe pod count decrease
   - Note final state: 1 replica

6. **Analysis** (5 minutes)
   - Review events: `kubectl get events --sort-by='.lastTimestamp'`
   - Check HPA status: `kubectl describe hpa`
   - Calculate time to scale up vs down
   - Discuss observations

### Expected Results

| Phase | Time | Pods | CPU per Pod | HPA Target |
|-------|------|------|-------------|------------|
| Initial | T+0 | 1 | 5m (2%) | 50% |
| Load Start | T+30 | 1 | 200m (100%) | 50% |
| Scaling Up | T+60 | 2 | 150m (75%) | 50% |
| Scaled Up | T+120 | 4 | 100m (50%) | 50% ✓ |
| Load Stop | T+180 | 4 | 5m (2%) | 50% |
| Scale Down 1 | T+480 | 2 | 5m (2%) | 50% |
| Scale Down 2 | T+780 | 1 | 5m (2%) | 50% ✓ |

## Key Learning Points

### HPA Dependencies
✅ **Metrics Server is REQUIRED** - HPA cannot function without it
✅ **Resource Requests are REQUIRED** - Pods must define CPU/memory requests
✅ **Service is REQUIRED** - Load generator needs to reach target pods

### HPA Behavior
- Scales up quickly (15-30 seconds after threshold)
- Scales down slowly (5+ minutes after load drops)
- Uses stabilization windows to prevent flapping
- Calculates replicas based on target utilization percentage

### Monitoring Best Practices
- Use multiple terminals for real-time monitoring
- Leverage Grafana for historical analysis
- Check HPA events for scaling decisions
- Monitor both current and desired metrics

### Real-World Applications
- Web applications with variable traffic
- API services with burst patterns
- Background processing jobs
- Microservices with unpredictable load

## Advanced Topics

### HPA Scaling Policies

```yaml
behavior:
  scaleUp:
    stabilizationWindowSeconds: 0  # Scale up immediately
    policies:
    - type: Percent
      value: 100    # Double pods
      periodSeconds: 15
    - type: Pods
      value: 4      # Or add 4 pods
      periodSeconds: 15
    selectPolicy: Max  # Use whichever gives more pods
  scaleDown:
    stabilizationWindowSeconds: 300  # Wait 5 minutes
    policies:
    - type: Percent
      value: 50     # Remove 50% of pods
      periodSeconds: 60
```

### Prometheus Integration

For custom metrics, install Prometheus Adapter:

```bash
# Install Prometheus Adapter for custom metrics
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install prometheus-adapter prometheus-community/prometheus-adapter \
    --set prometheus.url=http://prometheus-server \
    --set prometheus.port=80

# Verify custom metrics API
kubectl get apiservices | grep custom.metrics
```

## References

- [Kubernetes HPA Documentation](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
- [Metrics Server GitHub](https://github.com/kubernetes-sigs/metrics-server)
- [Azure Monitor for AKS](https://learn.microsoft.com/en-us/azure/azure-monitor/containers/container-insights-overview)
- [Azure Managed Grafana](https://learn.microsoft.com/en-us/azure/managed-grafana/)
- [HPA Walkthrough](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale-walkthrough/)

---

**This guide provides a comprehensive, hands-on demonstration of HPA functionality with real-world monitoring using Azure Managed Prometheus and Grafana.**
