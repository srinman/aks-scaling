# AKS Cluster AutoScaler (CAS) Guide

## Overview

The Cluster AutoScaler (CAS) automatically adjusts the number of nodes in your AKS cluster based on resource demands. When pods cannot be scheduled due to insufficient resources, CAS adds new nodes. When nodes are underutilized, CAS removes them to optimize costs.

## Prerequisites

- Existing AKS cluster with at least one node pool
- `kubectl` configured to access your cluster
- Azure CLI installed and configured

## Current Cluster Assessment

First, let's check the current state of your cluster:

```bash
# Check current cluster and node pool configuration
az aks show --name democluster --resource-group democlusterrg --query "agentPoolProfiles" -o table

# Check current nodes
kubectl get nodes -o wide

# Check current node pool details
az aks nodepool list --cluster-name democluster --resource-group democlusterrg -o table

# Check if autoscaler is enabled (should show 'false' initially)
az aks nodepool show \
    --cluster-name democluster \
    --resource-group democlusterrg \
    --name nodepool1 \
    --query "enableAutoScaling" -o tsv
```

## Step 1: Enable Cluster AutoScaler on Existing Node Pool

### Set Environment Variables

```bash
# Set your cluster details
export CLUSTER_NAME="democluster"
export RG_NAME="democlusterrg"
export NODEPOOL_NAME="nodepool1"  # Your existing node pool name

# Verify current node count
CURRENT_NODE_COUNT=$(kubectl get nodes --no-headers | wc -l)
echo "Current node count: $CURRENT_NODE_COUNT"
```

### Enable AutoScaler

```bash
# Enable cluster autoscaler on the existing node pool
# Set min nodes to current count, max nodes to allow scaling
az aks nodepool update \
    --cluster-name $CLUSTER_NAME \
    --resource-group $RG_NAME \
    --name $NODEPOOL_NAME \
    --enable-cluster-autoscaler \
    --min-count $CURRENT_NODE_COUNT \
    --max-count 10

echo "Cluster AutoScaler enabled successfully!"
```

### Verify AutoScaler Configuration

```bash
# Verify autoscaler is enabled
az aks nodepool show \
    --cluster-name $CLUSTER_NAME \
    --resource-group $RG_NAME \
    --name $NODEPOOL_NAME \
    --query "{name:name, enableAutoScaling:enableAutoScaling, minCount:minCount, maxCount:maxCount, count:count}" \
    -o table

# Check cluster autoscaler addon status
az aks show \
    --name $CLUSTER_NAME \
    --resource-group $RG_NAME \
    --query "autoScalerProfile" \
    -o yaml
```

## Step 2: Monitoring AutoScaler Activity

### View AutoScaler Logs via Azure Log Analytics

**Important**: In AKS, the cluster autoscaler runs on the **Microsoft-managed control plane**, not as a pod in your cluster. You cannot access autoscaler logs via `kubectl logs`. Instead, you must enable diagnostic settings to send logs to Log Analytics.

#### Enable Diagnostic Settings for Cluster Autoscaler

```bash
# Use existing Log Analytics Workspace
export LOG_ANALYTICS_WORKSPACE_NAME="aksresourcelogs"
export LOG_ANALYTICS_RG="infrarg"

# Get Log Analytics Workspace ID
LOG_ANALYTICS_WORKSPACE_ID=$(az monitor log-analytics workspace show \
    --resource-group $LOG_ANALYTICS_RG \
    --workspace-name $LOG_ANALYTICS_WORKSPACE_NAME \
    --query id -o tsv)

echo "Log Analytics Workspace ID: $LOG_ANALYTICS_WORKSPACE_ID"

# Enable diagnostic settings for cluster autoscaler logs
az monitor diagnostic-settings create \
    --name cluster-autoscaler-logs \
    --resource $(az aks show --name $CLUSTER_NAME --resource-group $RG_NAME --query id -o tsv) \
    --workspace $LOG_ANALYTICS_WORKSPACE_ID \
    --logs '[
      {
        "category": "cluster-autoscaler",
        "enabled": true,
        "retentionPolicy": {
          "enabled": false,
          "days": 0
        }
      }
    ]'

echo "Diagnostic settings enabled. Logs will be available in 5-10 minutes."
```

#### Query Autoscaler Logs in Log Analytics

```bash
# Get Log Analytics Workspace ID for queries
WORKSPACE_ID=$(az monitor log-analytics workspace show \
    --resource-group $LOG_ANALYTICS_RG \
    --workspace-name $LOG_ANALYTICS_WORKSPACE_NAME \
    --query customerId -o tsv)

echo "Log Analytics Workspace ID (Customer ID): $WORKSPACE_ID"
```

**Query autoscaler logs using Azure Portal**:
1. Navigate to Azure Portal → Log Analytics Workspace → Logs
2. Run these queries:

```kql
// View all cluster autoscaler logs from the last hour
AzureDiagnostics
| where Category == "cluster-autoscaler"
| where TimeGenerated > ago(1h)
| project TimeGenerated, log_s
| order by TimeGenerated desc

// Filter for scale-up events
AzureDiagnostics
| where Category == "cluster-autoscaler"
| where log_s contains "scale up" or log_s contains "Scaled up"
| project TimeGenerated, log_s
| order by TimeGenerated desc

// Filter for scale-down events
AzureDiagnostics
| where Category == "cluster-autoscaler"
| where log_s contains "scale down" or log_s contains "Scaled down"
| project TimeGenerated, log_s
| order by TimeGenerated desc

// Check for insufficient resources
AzureDiagnostics
| where Category == "cluster-autoscaler"
| where log_s contains "insufficient" or log_s contains "Insufficient"
| project TimeGenerated, log_s
| order by TimeGenerated desc

// View autoscaler decision timeline
AzureDiagnostics
| where Category == "cluster-autoscaler"
| where log_s contains "node group" or log_s contains "scale"
| project TimeGenerated, log_s
| order by TimeGenerated asc
```

#### Query Logs Using Azure CLI

```bash
# Query recent autoscaler logs via CLI
az monitor log-analytics query \
    --workspace $WORKSPACE_ID \
    --analytics-query "AzureDiagnostics | where Category == 'cluster-autoscaler' | where TimeGenerated > ago(1h) | project TimeGenerated, log_s | order by TimeGenerated desc" \
    --output table

# Query scale-up events
az monitor log-analytics query \
    --workspace $WORKSPACE_ID \
    --analytics-query "AzureDiagnostics | where Category == 'cluster-autoscaler' | where log_s contains 'scale up' | project TimeGenerated, log_s | order by TimeGenerated desc | take 20" \
    --output table
```

### Check AutoScaler ConfigMap

```bash
# View autoscaler configuration
kubectl get configmap cluster-autoscaler-status -n kube-system -o yaml

# Check autoscaler events
kubectl get events -n kube-system --field-selector reason=ScalingUp,reason=ScalingDown --sort-by='.lastTimestamp'
```

### Monitor Node and Resource Usage

```bash
# Watch nodes in real-time
watch kubectl get nodes

# Check resource usage
kubectl top nodes

# Check pod resource requests and limits
kubectl describe nodes | grep -A 5 "Allocated resources"

# Get detailed node resource information
kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, capacity: .status.capacity, allocatable: .status.allocatable}'
```

## Step 3: Demonstrate AutoScaler with Resource-Heavy Workloads

### Demo 1: CPU-Intensive Workload

This approach using pods with resource requests is **the standard and recommended way** to demonstrate cluster autoscaling. It's better than generating actual CPU load because:
- ✅ It's predictable and controllable
- ✅ Shows scheduler behavior clearly
- ✅ Safer for demo environments
- ✅ Faster to trigger scaling decisions

```bash
# Create a deployment with high CPU requests to trigger scaling
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cpu-heavy-demo
  labels:
    app: autoscaler-demo
spec:
  replicas: 1
  selector:
    matchLabels:
      app: cpu-heavy-demo
  template:
    metadata:
      labels:
        app: cpu-heavy-demo
    spec:
      containers:
      - name: cpu-consumer
        image: nginx:latest
        resources:
          requests:
            cpu: 1000m      # Request 1 full CPU core
            memory: 512Mi
          limits:
            cpu: 1000m
            memory: 512Mi
EOF

# Check current pod placement
kubectl get pods -o wide -l app=cpu-heavy-demo
```

### Demo 2: Scale Up Gradually

```bash
# Scale up the deployment to force node addition - based on SKU being used, you may need to scale to more replicas
kubectl scale deployment cpu-heavy-demo --replicas=5

# Monitor pod scheduling
kubectl get pods -l app=cpu-heavy-demo -o wide

# Check for pending pods (these will trigger autoscaling)
kubectl get pods -l app=cpu-heavy-demo --field-selector=status.phase=Pending

# Check events related to scaling
kubectl get events --sort-by='.lastTimestamp' | grep -i "scale\|autoscal\|insufficient"

# Query autoscaler logs from Log Analytics
az monitor log-analytics query \
    --workspace $WORKSPACE_ID \
    --analytics-query "AzureDiagnostics | where Category == 'cluster-autoscaler' | where TimeGenerated > ago(15m) | project TimeGenerated, log_s | order by TimeGenerated desc" \
    --output table
```

### Demo 3: Memory-Intensive Workload

```bash
# Create memory-heavy workload
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: memory-heavy-demo
spec:
  replicas: 3
  selector:
    matchLabels:
      app: memory-heavy-demo
  template:
    metadata:
      labels:
        app: memory-heavy-demo
    spec:
      containers:
      - name: memory-consumer
        image: nginx:latest
        resources:
          requests:
            cpu: 100m
            memory: 2Gi      # Request 2GB memory per pod
          limits:
            cpu: 200m
            memory: 2Gi
EOF

# Monitor the scaling process
watch "kubectl get nodes; echo; kubectl get pods -o wide | grep memory-heavy"
```

### Demo 4: Mixed Resource Requirements

```bash
# Create workload with both CPU and memory requirements
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mixed-resource-demo
spec:
  replicas: 8
  selector:
    matchLabels:
      app: mixed-resource-demo
  template:
    metadata:
      labels:
        app: mixed-resource-demo
    spec:
      containers:
      - name: resource-consumer
        image: nginx:latest
        resources:
          requests:
            cpu: 750m       # 0.75 CPU cores
            memory: 1Gi     # 1GB memory
          limits:
            cpu: 1000m
            memory: 1Gi
EOF
```

## Step 4: Monitoring and Observing AutoScaler Behavior

### Real-Time Monitoring Commands

```bash
# Terminal 1: Watch nodes
watch kubectl get nodes

# Terminal 2: Watch pods
watch kubectl get pods -o wide

# Terminal 3: Watch Kubernetes events for scaling activity
watch "kubectl get events --sort-by='.lastTimestamp' | grep -i 'scale\|insufficient\|trigger' | tail -20"

# Terminal 4: Query autoscaler logs from Log Analytics (requires Azure CLI)
# Note: Run this periodically to check autoscaler decisions
az monitor log-analytics query \
    --workspace $WORKSPACE_ID \
    --analytics-query "AzureDiagnostics | where Category == 'cluster-autoscaler' | where TimeGenerated > ago(15m) | project TimeGenerated, log_s | order by TimeGenerated desc | take 10" \
    --output table
```

**Note**: Since autoscaler runs on the control plane, you need to check Log Analytics for detailed autoscaler logs. Kubernetes events will show pod scheduling issues that trigger autoscaling.

### Key Observations for Participants

1. **Pending Pods**: Look for pods in `Pending` state with reason `Insufficient cpu` or `Insufficient memory`
2. **Scaling Events**: Check for events like `Triggering scale-up` in autoscaler logs
3. **Node Addition**: New nodes should appear with status `Ready` after 2-3 minutes
4. **Pod Scheduling**: Pending pods should move to `Running` state on new nodes

### AutoScaler Status and Metrics

```bash
# Check detailed autoscaler status
kubectl describe configmap cluster-autoscaler-status -n kube-system

# Get autoscaler metrics (if metrics server is enabled)
kubectl top nodes
kubectl top pods

# Check node resource utilization
kubectl describe nodes | grep -A 10 "Allocated resources"

# View detailed pod resource consumption
kubectl get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[0].resources.requests}{"\n"}{end}'
```

## Step 5: Demonstrate Scale-Down Behavior

### Test Scale-Down

```bash
# Scale down deployments to trigger node removal
kubectl scale deployment cpu-heavy-demo --replicas=0
kubectl scale deployment memory-heavy-demo --replicas=0
kubectl scale deployment mixed-resource-demo --replicas=0

# Monitor scale-down (takes 10-15 minutes by default)
kubectl logs -n kube-system -l app=cluster-autoscaler -f | grep -i "scale.*down\|remov\|delet"

# Watch nodes disappear
watch kubectl get nodes
```

### Understanding Scale-Down Timing

```bash
# Check autoscaler configuration for scale-down timing
kubectl get configmap cluster-autoscaler-status -n kube-system -o yaml | grep -A 5 -B 5 "scale-down"

# Default scale-down timings:
# - scale-down-delay-after-add: 10m
# - scale-down-unneeded-time: 10m
# - scale-down-delay-after-delete: 10s
```

## Step 6: Advanced Monitoring and Troubleshooting

### AutoScaler Configuration Details

```bash
# View all autoscaler settings
az aks show \
    --name $CLUSTER_NAME \
    --resource-group $RG_NAME \
    --query "autoScalerProfile" \
    -o yaml

# Key settings to understand:
# - scan-interval: How often autoscaler evaluates (default: 10s)
# - scale-down-delay-after-add: Wait time after adding nodes (default: 10m)
# - scale-down-unneeded-time: How long node must be unneeded (default: 10m)
# - max-node-provision-time: Max time to wait for node (default: 15m)
```

### Troubleshooting Commands

```bash
# Check for common issues
kubectl get events -A | grep -i "failed\|error\|insufficient"

# Verify node readiness
kubectl get nodes -o wide

# Check pod resource requests vs node capacity
kubectl describe node <node-name> | grep -A 20 "Allocated resources"

# Verify autoscaler is running
kubectl get pods -n kube-system -l app=cluster-autoscaler

# Check for resource quotas that might block scaling
kubectl get resourcequota -A
```

### Performance and Cost Monitoring

```bash
# Monitor cluster costs (requires Azure CLI with cost extension)
az consumption usage list --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_NAME"

# Check node pool scaling history
az monitor activity-log list \
    --resource-group $RG_NAME \
    --start-time 2024-01-01 \
    --query "[?contains(operationName.value, 'Scale')]" \
    -o table
```

## Step 7: Cleanup

```bash
# Clean up demo workloads
kubectl delete deployment cpu-heavy-demo memory-heavy-demo mixed-resource-demo

# Wait for scale-down to complete (10-15 minutes)
watch kubectl get nodes

# Optional: Disable autoscaler if needed
# az aks nodepool update \
#     --cluster-name $CLUSTER_NAME \
#     --resource-group $RG_NAME \
#     --name $NODEPOOL_NAME \
#     --disable-cluster-autoscaler
```

## Workshop Instructions for Participants

### Hands-On Exercise

1. **Enable AutoScaler** (if not already done):
   ```bash
   az aks nodepool update --enable-cluster-autoscaler --min-count 1 --max-count 5 ...
   ```

2. **Monitor in Multiple Terminals**:
   - Terminal 1: `watch kubectl get nodes`
   - Terminal 2: `watch kubectl get pods -o wide`
   - Terminal 3: `watch "kubectl get events --sort-by='.lastTimestamp' | tail -20"`
   - Terminal 4 (Azure Portal): Open Log Analytics and monitor cluster-autoscaler logs

3. **Deploy Resource-Heavy Workload**:
   ```bash
   kubectl create deployment demo --image=nginx --replicas=10
   kubectl patch deployment demo -p '{"spec":{"template":{"spec":{"containers":[{"name":"nginx","resources":{"requests":{"cpu":"1000m","memory":"1Gi"}}}]}}}}'
   ```

4. **Observe Scaling Behavior**:
   - Watch for pending pods
   - Monitor autoscaler logs for "Triggering scale-up"
   - Count nodes before and after scaling
   - Check pod placement on new nodes

5. **Test Scale-Down**:
   ```bash
   kubectl scale deployment demo --replicas=1
   # Wait 10-15 minutes and observe node removal
   ```

## Key Learning Points

### Why Resource Requests Work for Demos

✅ **Scheduler-Based**: Kubernetes scheduler uses resource requests to make placement decisions
✅ **Predictable**: Known resource requirements make scaling predictable
✅ **Safe**: No actual resource consumption, safe for demo environments
✅ **Educational**: Clearly shows the relationship between requests and scheduling
✅ **Industry Standard**: This is how most real applications trigger autoscaling

### AutoScaler Decision Process

1. **Pod Pending**: Pod cannot be scheduled due to insufficient resources
2. **Node Evaluation**: AutoScaler checks if adding a node would help
3. **Scale-Up Decision**: If yes, requests new node from cloud provider
4. **Node Provisioning**: Cloud provider creates and joins new node (2-5 minutes)
5. **Pod Scheduling**: Scheduler places pending pods on new node

### Best Practices Demonstrated

- Set appropriate resource requests on pods
- Use min/max node counts to control costs
- Monitor autoscaler logs for troubleshooting
- Allow 10-15 minutes for scale-down operations
- Consider using multiple node pools for different workload types

## Common AutoScaler Scenarios

### Production Recommendations

1. **Conservative Scaling**: Start with smaller min/max ranges
2. **Resource Requests**: Always set CPU/memory requests on production pods
3. **Node Taints**: Use taints/tolerations for workload isolation
4. **Cost Monitoring**: Track scaling costs and set appropriate limits
5. **Scale-Down Protection**: Use PodDisruptionBudgets for critical workloads

This guide provides a comprehensive, hands-on approach to understanding and demonstrating AKS Cluster AutoScaler functionality using the industry-standard method of resource requests.
