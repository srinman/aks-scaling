# AKS Node Auto Provisioning (NAP) Deployment Guide

## Overview

Node Auto Provisioning (NAP) is AKS's implementation of the open-source Karpenter project that automatically provisions, scales, and manages virtual machines (nodes) in response to pending pod pressure. NAP uses workload resource requirements to determine the optimal VM configuration for efficiency and cost-effectiveness.

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

**Review this link for more details on AKSNodeClass**   
https://learn.microsoft.com/en-us/azure/aks/node-autoprovision-aksnodeclass  

An excerpt:   
AKSNodeClass enables configuration of Azure-specific settings for node auto provisioning. Each NodePool must reference an AKSNodeClass using spec.template.spec.nodeClassRef. Multiple NodePools may point to the same AKSNodeClass, allowing you to share common Azure configurations across different node pools.


Compare this with what's possible in regular nodepool:   
https://learn.microsoft.com/en-us/azure/aks/custom-node-configuration?tabs=linux-node-pools   


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
k explain aksnc.spec
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

### Common Troubleshooting Commands

```bash

# Describe NodePool for issues
kubectl describe nodepool default-nodepool

# Check node provisioning issues
kubectl describe nodeclaims

# Verify resource requests and limits
kubectl describe pods -l app=nap-test

# Check available VM SKUs in region
az vm list-skus --location "East US 2" --size Standard_D --output table | grep -v "NotAvailableForSubscription"
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
s
## References

- [Microsoft NAP Documentation](https://learn.microsoft.com/en-us/azure/aks/node-autoprovision)
- [Karpenter Documentation](https://karpenter.sh/)
- [AKS Karpenter Provider](https://github.com/Azure/karpenter-provider-azure)
- [NAP Networking Configuration](https://learn.microsoft.com/en-us/azure/aks/node-autoprovision-networking)
- [NAP Disruption Policies](https://learn.microsoft.com/en-us/azure/aks/node-autoprovision-disruption)
