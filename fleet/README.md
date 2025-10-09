# Azure Kubernetes Fleet Manager - Simple Multi-Cluster Scaling Demo

This guide demonstrates how to use **Azure Kubernetes Fleet Manager** to scale workloads across multiple AKS clusters. We'll create a Fleet, add two existing clusters, deploy a simple application, and observe how Fleet enables multi-cluster workload management.

## What is Azure Kubernetes Fleet Manager?

Azure Kubernetes Fleet Manager provides centralized management for multiple AKS clusters through a **hub-and-spoke architecture**:

- **Hub Cluster**: Central control plane for fleet-wide operations
- **Member Clusters**: Your existing AKS clusters that join the fleet
- **Multi-Cluster Workload Orchestration**: Deploy and scale applications across all member clusters from a single point of control

### Key Benefits

- 🚀 **Limitless Scalability**: Scale beyond single cluster limits by distributing workloads across multiple clusters
- 🛡️ **Reduced Blast Radius**: Failures are isolated to individual clusters
- 🌍 **Multi-Region Flexibility**: Distribute workloads across regions for capacity and resilience
- 🎯 **Centralized Management**: Single API to manage resources across all clusters

### Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                  Fleet Hub Cluster                      │
│           (Central Control Plane)                       │
│                                                         │
│  • ClusterResourcePlacement                            │
│  • Resource Propagation                                │
│  • Multi-Cluster Scheduling                            │
└─────────────────┬───────────────────────────────────────┘
                  │
        ┌─────────┴─────────┐
        │                   │
        ▼                   ▼
┌──────────────┐    ┌──────────────┐
│   Cluster 1  │    │   Cluster 2  │
│ (aks-nap-    │    │ (democluster)│
│  cluster)    │    │              │
│              │    │              │
│ Workload A   │    │ Workload A   │
│ Replicas 1-N │    │ Replicas 1-M │
└──────────────┘    └──────────────┘
```

---

## Prerequisites

- Azure CLI installed and authenticated
- Two existing AKS clusters:
  - **Cluster 1**: `aks-nap-cluster` in resource group `aks-nap-rg`
  - **Cluster 2**: `democluster` in resource group `democlusterrg`
- `kubectl` installed
- Contributor access to both resource groups

---

## Part 1: Create and Configure Fleet

### Step 1: Set Environment Variables

```bash
# Set variables for your environment
FLEET_RG="fleet-demo-rg"
FLEET_NAME="scaling-demo-fleet"
LOCATION="eastus2"

# Cluster 1 details
CLUSTER1_NAME="aks-nap-cluster"
CLUSTER1_RG="aks-nap-rg"

# Cluster 2 details
CLUSTER2_NAME="democluster"
CLUSTER2_RG="democlusterrg"
```

### Step 2: Create Fleet Resource

```bash
# Create resource group for Fleet
az group create \
    --name $FLEET_RG \
    --location $LOCATION

# Create Fleet with hub cluster
az fleet create \
    --name $FLEET_NAME \
    --resource-group $FLEET_RG \
    --location $LOCATION \
    --enable-hub

# Verify Fleet creation
az fleet show \
    --name $FLEET_NAME \
    --resource-group $FLEET_RG \
    --output table
```

**What does this do?**
- Creates a Fleet resource with an integrated **hub cluster** (central control plane)
- The `--enable-hub` flag provisions a managed Kubernetes cluster that acts as the Fleet control plane
- This hub cluster is where you'll define multi-cluster policies and placements

### Step 3: Add Member Clusters to Fleet

```bash
# Add Cluster 1 to Fleet
az fleet member create \
    --name ${CLUSTER1_NAME}-member \
    --fleet-name $FLEET_NAME \
    --resource-group $FLEET_RG \
    --member-cluster-id $(az aks show \
        --name $CLUSTER1_NAME \
        --resource-group $CLUSTER1_RG \
        --query id -o tsv)

# Add Cluster 2 to Fleet
az fleet member create \
    --name ${CLUSTER2_NAME}-member \
    --fleet-name $FLEET_NAME \
    --resource-group $FLEET_RG \
    --member-cluster-id $(az aks show \
        --name $CLUSTER2_NAME \
        --resource-group $CLUSTER2_RG \
        --query id -o tsv)

# List all Fleet members
az fleet member list \
    --fleet-name $FLEET_NAME \
    --resource-group $FLEET_RG \
    --output table
```

**Expected Output:**
```
Name                        ProvisioningState    Status
--------------------------  -------------------  --------
aks-nap-cluster-member      Succeeded           Joined
democluster-member          Succeeded           Joined
```

### Step 4: Get Fleet Hub Cluster Credentials

```bash
# Get hub cluster credentials
az fleet get-credentials \
    --name $FLEET_NAME \
    --resource-group $FLEET_RG

# Verify connection to hub cluster
kubectl config current-context
# Should show: fleet-<fleet-name>-hub-cluster

# Check Fleet member status from hub
kubectl get memberclusters
```

**Expected Output:**
```
NAME                        JOINED   AGE
aks-nap-cluster-member      True     2m
democluster-member          True     2m
```

---

## Part 2: Deploy Application Across Fleet

### Step 5: Create Namespace

```bash
# Create namespace on hub cluster (will be propagated to members)
kubectl create namespace fleet-demo
```

### Step 6: Deploy Simple Application

Create a simple nginx deployment that we'll scale across both clusters:

```bash
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-fleet-demo
  namespace: fleet-demo
  labels:
    app: nginx-fleet
spec:
  replicas: 3
  selector:
    matchLabels:
      app: nginx-fleet
  template:
    metadata:
      labels:
        app: nginx-fleet
    spec:
      containers:
      - name: nginx
        image: nginx:latest
        ports:
        - containerPort: 80
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 200m
            memory: 256Mi
---
apiVersion: v1
kind: Service
metadata:
  name: nginx-fleet-svc
  namespace: fleet-demo
spec:
  type: LoadBalancer
  selector:
    app: nginx-fleet
  ports:
  - port: 80
    targetPort: 80
EOF
```

**What does this do?**
- Creates a simple nginx deployment with 3 replicas
- Exposes it via a LoadBalancer service
- Resources are defined but not yet propagated to member clusters

### Step 7: Create ClusterResourcePlacement

This is the key resource that tells Fleet **how to distribute workloads** across member clusters:

```bash
kubectl apply -f - <<EOF
apiVersion: placement.kubernetes-fleet.io/v1beta1
kind: ClusterResourcePlacement
metadata:
  name: nginx-fleet-placement
spec:
  resourceSelectors:
    - group: ""
      kind: Namespace
      version: v1
      name: fleet-demo
  policy:
    placementType: PickAll
  strategy:
    type: RollingUpdate
EOF
```

**What does this do?**
- **resourceSelectors**: Selects the `fleet-demo` namespace and all resources within it
- **placementType: PickAll**: Deploys to ALL member clusters (both aks-nap-cluster and democluster)
- **strategy: RollingUpdate**: Updates are rolled out gradually across clusters

**Alternative placement policies:**
- `PickN`: Deploy to N clusters (e.g., pick 1 cluster)
- `PickFixed`: Deploy to specific named clusters

### Step 8: Verify Deployment Across Clusters

```bash
# Check placement status from hub cluster
kubectl get clusterresourceplacement nginx-fleet-placement -o yaml

# Check if resources are applied to member clusters
kubectl get clusterresourceplacement nginx-fleet-placement \
    --output jsonpath='{.status.conditions}' | jq

# See which clusters received the workload
kubectl describe clusterresourceplacement nginx-fleet-placement
```

**Expected Status:**
```yaml
status:
  conditions:
  - type: ClusterResourcePlacementApplied
    status: "True"
    reason: ApplySucceeded
  selectedResources:
  - kind: Namespace
    name: fleet-demo
  - kind: Deployment
    name: nginx-fleet-demo
  - kind: Service
    name: nginx-fleet-svc
```

---

## Part 3: Verify Multi-Cluster Deployment

### Step 9: Check Workload on Member Clusters

Now switch to each member cluster and verify the deployment:

```bash
# Switch to Cluster 1
az aks get-credentials \
    --name $CLUSTER1_NAME \
    --resource-group $CLUSTER1_RG \
    --overwrite-existing

# Check deployment on Cluster 1
kubectl get pods -n fleet-demo -o wide
kubectl get svc -n fleet-demo

# Switch to Cluster 2
az aks get-credentials \
    --name $CLUSTER2_NAME \
    --resource-group $CLUSTER2_RG \
    --overwrite-existing

# Check deployment on Cluster 2
kubectl get pods -n fleet-demo -o wide
kubectl get svc -n fleet-demo
```

**Expected Output on Each Cluster:**
```
NAME                                READY   STATUS    RESTARTS   AGE     IP
nginx-fleet-demo-xxxxx-xxxxx        1/1     Running   0          2m      10.244.x.x
nginx-fleet-demo-xxxxx-xxxxx        1/1     Running   0          2m      10.244.x.x
nginx-fleet-demo-xxxxx-xxxxx        1/1     Running   0          2m      10.244.x.x

NAME                TYPE           CLUSTER-IP     EXTERNAL-IP     PORT(S)
nginx-fleet-svc     LoadBalancer   10.0.x.x       <pending/IP>    80:xxxxx/TCP
```

✅ **Success!** Both clusters should show the nginx deployment with 3 replicas and the LoadBalancer service.

---

## Part 4: Test Scaling Across Fleet

### Step 10: Scale Application from Hub

Switch back to the Fleet hub cluster:

```bash
# Get hub credentials
az fleet get-credentials \
    --name $FLEET_NAME \
    --resource-group $FLEET_RG

# Scale the deployment
kubectl scale deployment nginx-fleet-demo \
    --namespace fleet-demo \
    --replicas=10
```

### Step 11: Verify Scaling on Member Clusters

```bash
# Check Cluster 1
az aks get-credentials --name $CLUSTER1_NAME --resource-group $CLUSTER1_RG --overwrite-existing
kubectl get pods -n fleet-demo --watch

# Check Cluster 2
az aks get-credentials --name $CLUSTER2_NAME --resource-group $CLUSTER2_RG --overwrite-existing
kubectl get pods -n fleet-demo --watch
```

**Expected Behavior:**
- Each cluster should now have **10 nginx pods** running
- Pods are scaled **independently on each cluster**
- Total pods across fleet: **20 pods** (10 on each cluster)

---

## Part 5: Portal Verification (Optional)

### View Fleet in Azure Portal

1. Navigate to [Azure Portal](https://portal.azure.com)
2. Search for **"Kubernetes Fleet Manager"** or go to your resource group `fleet-demo-rg`
3. Click on your Fleet: `scaling-demo-fleet`

**What to verify:**
- ✅ **Overview**: See both member clusters listed
- ✅ **Member clusters**: View health status of aks-nap-cluster and democluster
- ✅ **Resources**: See propagated workloads (requires Fleet hub cluster access)

### View Member Clusters

1. Navigate to each AKS cluster:
   - `aks-nap-cluster` in `aks-nap-rg`
   - `democluster` in `democlusterrg`
2. Go to **Workloads** → **Deployments**
3. Select namespace: `fleet-demo`
4. Verify: `nginx-fleet-demo` deployment with 10 replicas

---

## Understanding the Fleet Scaling Model

### How Fleet Distributes Workloads

```
Hub Cluster (Define Once)
  └─ Deployment: nginx-fleet-demo (10 replicas)
     └─ ClusterResourcePlacement: PickAll
           │
           ├──> Cluster 1: 10 replicas
           │
           └──> Cluster 2: 10 replicas

Total Capacity: 20 replicas (10 per cluster)
```

### Key Concepts

| Concept | Description |
|---------|-------------|
| **ClusterResourcePlacement** | Defines which resources to deploy and to which clusters |
| **placementType: PickAll** | Deploys to all member clusters |
| **placementType: PickN** | Deploys to N clusters (useful for cost optimization) |
| **Resource Propagation** | Automatically syncs resources from hub to members |
| **Independent Scaling** | Each cluster scales independently (no cross-cluster replica balancing by default) |

### Scaling Patterns

1. **Uniform Distribution** (Current Demo)
   - Same number of replicas on each cluster
   - Good for: High availability, geographic distribution

2. **Selective Placement** (PickN)
   - Deploy to subset of clusters
   - Good for: Cost optimization, region-specific workloads

3. **Priority-Based** (Advanced)
   - Use cluster labels and affinity rules
   - Good for: Different cluster tiers (GPU vs CPU)

---

## Cleanup

### Remove Fleet Resources

```bash
# Delete the ClusterResourcePlacement (removes workloads from member clusters)
kubectl delete clusterresourceplacement nginx-fleet-placement

# Verify resources are removed from member clusters
az aks get-credentials --name $CLUSTER1_NAME --resource-group $CLUSTER1_RG --overwrite-existing
kubectl get all -n fleet-demo

az aks get-credentials --name $CLUSTER2_NAME --resource-group $CLUSTER2_RG --overwrite-existing
kubectl get all -n fleet-demo

# Remove member clusters from Fleet
az fleet member delete \
    --name ${CLUSTER1_NAME}-member \
    --fleet-name $FLEET_NAME \
    --resource-group $FLEET_RG \
    --yes

az fleet member delete \
    --name ${CLUSTER2_NAME}-member \
    --fleet-name $FLEET_NAME \
    --resource-group $FLEET_RG \
    --yes

# Delete Fleet (includes hub cluster)
az fleet delete \
    --name $FLEET_NAME \
    --resource-group $FLEET_RG \
    --yes

# Delete Fleet resource group
az group delete \
    --name $FLEET_RG \
    --yes --no-wait
```

---

## Key Takeaways

✅ **What We Accomplished:**
1. Created a Fleet with centralized hub cluster
2. Added two existing AKS clusters as members
3. Deployed an application from hub that propagated to both clusters
4. Scaled the application across multiple clusters from a single command

✅ **Benefits Demonstrated:**
- **Single Point of Control**: Manage multiple clusters from hub
- **Automatic Propagation**: Resources deployed once, distributed automatically
- **Scale Beyond Limits**: Combined capacity of both clusters
- **Reduced Complexity**: No manual deployment to each cluster

---

## Advanced Scenarios (Future Exploration)

### Multi-Cluster Load Balancing
- Use **Azure Traffic Manager** or **Azure Front Door** to distribute traffic across cluster LoadBalancers
- Implement DNS-based routing between regions

### Kueue Integration (Batch Workloads)
- Deploy **Kueue** for intelligent batch job scheduling across Fleet
- See: [AKS Blog - Scaling for AI Workloads](https://blog.aks.azure.com/2025/04/02/Scaling-Kubernetes-for-AI-and-Data-intensive-Workloads)

### Resource Quotas and Scheduling
- Use **ClusterResourceOverride** to customize resources per cluster
- Implement **placement affinity** based on cluster labels (e.g., GPU clusters)

---

## Additional Resources

- 📘 [Azure Fleet Manager - Multi-Cluster Workload Management](https://learn.microsoft.com/en-us/azure/kubernetes-fleet/concepts-multi-cluster-workload-management)
- 📘 [AKS Blog - Scaling Kubernetes for AI Workloads](https://blog.aks.azure.com/2025/04/02/Scaling-Kubernetes-for-AI-and-Data-intensive-Workloads)
- 🔧 [Fleet GitHub - KubeFleet Project](https://github.com/kubefleet-dev/kubefleet)
- 📖 [Fleet Resource Placement Documentation](https://learn.microsoft.com/en-us/azure/kubernetes-fleet/concepts-resource-propagation)
- 📺 [Fleet Roadmap](https://github.com/orgs/Azure/projects/712)

---

*This demo provides a foundational understanding of Azure Kubernetes Fleet Manager for multi-cluster scaling. For production deployments, consider implementing advanced placement policies, monitoring, and disaster recovery strategies.*
