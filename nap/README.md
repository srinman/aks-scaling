# AKS Node Auto Provisioning (NAP) Deployment Guide

## Overview

Node Auto Provisioning (NAP) is AKS's implementation of the open-source Karpenter project that automatically provisions, scales, and manages virtual machines (nodes) in response to pending pod pressure. NAP uses workload resource requirements to determine the optimal VM configuration for efficiency and cost-effectiveness.

## Important Note on Private Clusters

⚠️ **Current Limitation**: According to Microsoft documentation, private clusters are **not currently supported** with Node Auto Provisioning. However, this guide includes the private cluster setup commands for when this limitation is resolved.

## Prerequisites

- Azure CLI 2.76.0 or later
- Azure subscription with appropriate permissions
- `kubectl` installed and configured

### Check Azure CLI Version
```bash
az --version
# Ensure version is 2.76.0 or later
```

## Key Limitations and Requirements

### Supported Features
- System-assigned or user-assigned managed identity (Service Principals not supported)
- Azure CNI or Azure CNI Overlay networking
- Standard Load Balancer (required)
- Linux nodes only (Windows not supported)



## Step 1: Set Environment Variables

```bash
# Set your deployment variables
export LOCATION="East US 2"
export RG_NAME="aks-nap-rg"
export CLUSTER_NAME="aks-nap-cluster"
export VNET_NAME="aks-nap-vnet2"
export IDENTITY_NAME="aks-nap-identity"
export SUBSCRIPTION_ID=$(az account show --query id -o tsv)

echo "Subscription ID: $SUBSCRIPTION_ID"
echo "Resource Group: $RG_NAME"
echo "Cluster Name: $CLUSTER_NAME"
echo "Location: $LOCATION"
```

## Step 2: Create Resource Group

```bash
# Create resource group
az group create \
    --name $RG_NAME \
    --location "$LOCATION"
```

## Step 3: Create Custom Virtual Network

### Create VNET and Cluster Subnet

```bash
# Create virtual network
az network vnet create \
    --name $VNET_NAME \
    --resource-group $RG_NAME \
    --location "$LOCATION" \
    --address-prefixes 192.168.0.0/16

# Create cluster subnet with delegation for NAP
# Note: API server subnet delegation is required for NAP
az network vnet subnet create \
    --resource-group $RG_NAME \
    --vnet-name $VNET_NAME \
    --name cluster-subnet \
    --address-prefixes 192.168.0.0/24 \
    --delegations Microsoft.ContainerService/managedClusters


# Get subnet IDs
CLUSTER_SUBNET_ID=$(az network vnet subnet show \
    --resource-group $RG_NAME \
    --vnet-name $VNET_NAME \
    --name cluster-subnet \
    --query id -o tsv)



echo "Cluster Subnet ID: $CLUSTER_SUBNET_ID"
```

## Step 4: Create Managed Identity and Assign Permissions

```bash
# Create user-assigned managed identity
az identity create \
    --resource-group $RG_NAME \
    --name $IDENTITY_NAME \
    --location "$LOCATION"

# Get identity details
IDENTITY_ID=$(az identity show \
    --resource-group $RG_NAME \
    --name $IDENTITY_NAME \
    --query id -o tsv)

IDENTITY_PRINCIPAL_ID=$(az identity show \
    --resource-group $RG_NAME \
    --name $IDENTITY_NAME \
    --query principalId -o tsv)

# Assign Network Contributor role on the VNET
az role assignment create \
    --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_NAME/providers/Microsoft.Network/virtualNetworks/$VNET_NAME" \
    --role "Network Contributor" \
    --assignee $IDENTITY_PRINCIPAL_ID

echo "Identity ID: $IDENTITY_ID"
echo "Identity Principal ID: $IDENTITY_PRINCIPAL_ID"
```

## Step 5: Deploy AKS Cluster with NAP

### Option A: Public Cluster with NAP (Currently Supported)

⚠️ **Important**: You cannot use `--enable-cluster-autoscaler` with `--node-provisioning-mode Auto`. NAP replaces the traditional cluster autoscaler.

```bash
# Create AKS cluster with Node Auto Provisioning enabled
# Note: We create a minimal system node pool and let NAP handle scaling
az aks create \
    --name $CLUSTER_NAME \
    --resource-group $RG_NAME \
    --location "$LOCATION" \
    --assign-identity $IDENTITY_ID \
    --node-provisioning-mode Auto \
    --network-plugin azure \
    --network-plugin-mode overlay \
    --network-dataplane cilium \
    --enable-managed-identity \
    --generate-ssh-keys \
    --node-count 1 \
    --node-vm-size Standard_D2s_v5

echo "AKS cluster '$CLUSTER_NAME' created successfully with NAP enabled"
```

## Step 6: Configure kubectl

```bash
# Get AKS credentials
az aks get-credentials \
    --resource-group $RG_NAME \
    --name $CLUSTER_NAME \
    --overwrite-existing

# Verify connection
kubectl get nodes
kubectl get pods -A
```

## Step 7: Verify NAP Installation

```bash
# Check if NAP is enabled
az aks show \
    --name $CLUSTER_NAME \
    --resource-group $RG_NAME \
    --query "nodeProvisioningProfile.mode" -o tsv

# Should return "Auto"


# Check for NAP api-resources
kubectl  api-resources | grep karp

```

## Step 8: Create Basic AKSNodeClass and NodePool

### Basic AKSNodeClass Configuration

```bash
kubectl apply -f - <<EOF
apiVersion: karpenter.azure.com/v1beta1
kind: AKSNodeClass
metadata:
  name: default-nodeclass
  annotations:
    kubernetes.io/description: "General purpose AKSNodeClass for Ubuntu2204 nodes"
spec:
  imageFamily: Ubuntu2204
EOF
```

### Explore spec for aksnodeclasses  

```bash
k explain aksnodeclasses.spec
k explain aksnodeclasses.spec.imageFamily
```

### Basic NodePool Configuration

```bash
kubectl apply -f - <<EOF
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: default-nodepool
spec:
  template:
    metadata:
      labels:
        intent: apps
    spec:
      requirements:
        - key: karpenter.sh/capacity-type
          operator: In
          values: [spot, on-demand]
        - key: node.kubernetes.io/instance-type
          operator: In
          values: [Standard_D2s_v5, Standard_D4s_v5, Standard_D8s_v5]  # Specific VM sizes
      nodeClassRef:
        group: karpenter.azure.com
        kind: AKSNodeClass
        name: default-nodeclass
      expireAfter: Never
  limits:
    cpu: 30  # Maximum 30 vCPUs across all nodes in this pool
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 0s
EOF
```

## Step 9: Test NAP with Sample Workload

### Deploy Test Application

```bash
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nap-test-app
spec:
  replicas: 5
  selector:
    matchLabels:
      app: nap-test
  template:
    metadata:
      labels:
        app: nap-test
    spec:
      containers:
      - name: app
        image: nginx:latest
        resources:
          requests:
            cpu: 500m
            memory: 512Mi
          limits:
            cpu: 1000m
            memory: 1Gi
EOF
```

### Monitor NAP Scaling

```bash
# Watch nodes being created
watch kubectl get nodes

# Monitor NAP events (sorted by timestamp)
kubectl get events -A --field-selector source=karpenter --sort-by='.lastTimestamp'

# Watch NAP events in real-time
kubectl get events -A --field-selector source=karpenter -w

# Check node claims (managed by NAP)
kubectl get nodeclaims

# Check pod scheduling
kubectl get pods -o wide

# Check if pods are pending and why
kubectl get pods -o wide | grep Pending
kubectl describe pods -l app=nap-test | grep -A 10 "Events:"

# Check nodeclaim details for troubleshooting
kubectl describe nodeclaims
```

## Advanced NodePool Configurations

### Production NodePool with Multiple Instance Types

```bash
kubectl apply -f - <<EOF
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: production-nodepool
spec:
  template:
    metadata:
      labels:
        intent: production
        environment: prod
    spec:
      requirements:
        - key: karpenter.sh/capacity-type
          operator: In
          values: [on-demand]  # Only on-demand for production
        - key: node.kubernetes.io/instance-type
          operator: In
          values: [Standard_D4s_v5, Standard_D8s_v5, Standard_D16s_v5, Standard_E4s_v5, Standard_E8s_v5]  # D-series and E-series
        - key: kubernetes.io/arch
          operator: In
          values: [amd64]
      nodeClassRef:
        group: karpenter.azure.com
        kind: AKSNodeClass
        name: default-nodeclass
      expireAfter: 24h  # Expire nodes after 24 hours for security
      taints:
        - key: production
          value: "true"
          effect: NoSchedule
  limits:
    cpu: 500  # Higher limit for production workloads
  disruption:
    consolidationPolicy: WhenEmpty
    consolidateAfter: 60s  # Longer wait time for production
EOF
```

### Spot Instance NodePool for Development

```bash
kubectl apply -f - <<EOF
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: spot-nodepool
spec:
  template:
    metadata:
      labels:
        intent: development
        cost-optimization: spot
    spec:
      requirements:
        - key: karpenter.sh/capacity-type
          operator: In
          values: [spot]  # Only spot instances
        - key: node.kubernetes.io/instance-type
          operator: In
          values: [Standard_B2s, Standard_B4ms, Standard_D2s_v5, Standard_D4s_v5]  # B-series and D-series
      nodeClassRef:
        group: karpenter.azure.com
        kind: AKSNodeClass
        name: default-nodeclass
      expireAfter: 2h  # Short-lived for dev workloads
      taints:
        - key: spot
          value: "true"
          effect: NoSchedule
  limits:
    cpu: 50
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 10s  # Quick consolidation for cost savings
EOF
```

## Monitoring and Troubleshooting

### Monitor NAP Operations

```bash
# View all NAP-related events
kubectl get events -A --field-selector source=karpenter --sort-by='.lastTimestamp'

# Check NodePool status
kubectl get nodepool -o wide

# Check AKSNodeClass status
kubectl get aksnodeclass -o wide

# View node claims
kubectl get nodeclaims -o wide

# Check cluster capacity
kubectl top nodes
```

### Common Troubleshooting Commands

```bash
# Check NAP controller logs
kubectl logs -n kube-system -l app.kubernetes.io/name=karpenter -f

# Describe NodePool for issues
kubectl describe nodepool default-nodepool

# Check node provisioning issues
kubectl describe nodeclaims

# Verify resource requests and limits
kubectl describe pods -l app=nap-test

# Check available VM SKUs in region
az vm list-skus --location "East US 2" --size Standard_D --output table | grep -v "NotAvailableForSubscription"
```

### Common Errors and Solutions

#### Error: "SubnetIsDelegated" 
```
AgentPoolProfile subnet cannot be used as it's a delegated subnet
```
**Cause**: Trying to use a delegated subnet for regular node pools or mixing NAP with traditional cluster autoscaler.

**Solutions**:
1. Remove `--enable-cluster-autoscaler` when using `--node-provisioning-mode Auto`
2. Use a non-delegated subnet for the initial system node pool
3. Let NAP handle all scaling instead of traditional cluster autoscaler

#### Error: "Cannot enable NAP with existing cluster autoscaler"
**Solution**: Disable cluster autoscaler on all node pools before enabling NAP:
```bash
az aks nodepool update \
    --cluster-name $CLUSTER_NAME \
    --resource-group $RG_NAME \
    --name nodepool1 \
    --disable-cluster-autoscaler
```

## Enable NAP on Existing Cluster

```bash
# Update existing cluster to enable NAP
az aks update \
    --name $CLUSTER_NAME \
    --resource-group $RG_NAME \
    --node-provisioning-mode Auto

# Note: Cannot enable NAP if cluster autoscaler is already enabled on node pools
# Must disable cluster autoscaler first
```

## Cleanup Commands

```bash
# Scale down NodePool to prevent new nodes
kubectl patch nodepool default-nodepool --type='merge' -p='{"spec":{"limits":{"cpu":"0"}}}'

# Add disable taint to trigger workload migration
kubectl patch nodepool default-nodepool --type='merge' -p='{"spec":{"template":{"spec":{"taints":[{"key":"karpenter.azure.com/disable","effect":"NoSchedule"}]}}}}'

# Disable NAP on cluster
az aks update \
    --name $CLUSTER_NAME \
    --resource-group $RG_NAME \
    --node-provisioning-mode Manual

# Delete cluster and resources
az aks delete --name $CLUSTER_NAME --resource-group $RG_NAME --yes --no-wait
az group delete --name $RG_NAME --yes --no-wait
```

## Key Benefits of NAP

1. **Automatic Right-Sizing**: Selects optimal VM sizes based on workload requirements
2. **Cost Optimization**: Uses spot instances and consolidates underutilized nodes
3. **Zero-to-Scale**: Can scale from 0 nodes to handle workload demands
4. **Simplified Management**: No need to pre-provision node pools with specific VM sizes
5. **Workload-Driven**: Provisions nodes based on actual pod resource requests

## Next Steps

1. **Monitor Costs**: Use Azure Cost Management to track NAP cost optimization
2. **Configure Alerts**: Set up monitoring for node provisioning events
3. **Tune NodePools**: Adjust limits and requirements based on workload patterns
4. **Security**: Implement proper RBAC and Pod Security Standards
5. **Integration**: Integrate with CI/CD pipelines for automated workload deployment

## References

- [Microsoft NAP Documentation](https://learn.microsoft.com/en-us/azure/aks/node-autoprovision)
- [Karpenter Documentation](https://karpenter.sh/)
- [AKS Karpenter Provider](https://github.com/Azure/karpenter-provider-azure)
- [NAP Networking Configuration](https://learn.microsoft.com/en-us/azure/aks/node-autoprovision-networking)
- [NAP Disruption Policies](https://learn.microsoft.com/en-us/azure/aks/node-autoprovision-disruption)
