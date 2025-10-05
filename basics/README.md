# AKS Scaling Basics

## Finding Available VM SKUs for AKS Node Pools

When creating AKS node pools, you may encounter errors about VM sizes not being available in certain zones or regions. Here are useful commands to find available VM SKUs.

### 1. Find All Available VM Sizes in a Region

```bash
# List all VM sizes available in a specific region
az vm list-skus --location eastus2 --resource-type virtualMachines --output table
```

### 2. Find VM Sizes Without Subscription Restrictions

```bash
# Filter out VM sizes that are not available for your subscription
az vm list-skus --location eastus2 --resource-type virtualMachines --output table | grep -v "NotAvailableForSubscription"
```

### 3. Search for Specific VM Family

```bash
# Search for D-series VMs
az vm list-skus --location eastus2 --size Standard_D --output table

# Search for B-series VMs (good for general workloads)
az vm list-skus --location eastus2 --size Standard_B --output table

# Search for E-series VMs (memory optimized)
az vm list-skus --location eastus2 --size Standard_E --output table
```

### 4. Check Zone Availability for Specific SKU

```bash
# Check if a specific VM size is available in all zones
az vm list-skus --location eastus2 --query "[?name=='Standard_D4s_v6']" --output table

# More detailed information about a specific SKU
az vm list-skus --location eastus2 --resource-type virtualMachines --query "[?name=='Standard_D4s_v6']" --output json
```

### 5. Find Available SKUs by Core Count

```bash
# Find available D-series VMs with 2-4 cores that work in all zones
az vm list-skus --location eastus2 --size Standard_D --output table | grep -E "Standard_D[2-4][ds]?_v[4-6]" | grep -v "NotAvailableForSubscription"

# Find available B-series VMs (burstable performance)
az vm list-skus --location eastus2 --size Standard_B --output table | grep -v "NotAvailableForSubscription"
```

## Common Available SKUs by Region

### East US 2 Region - Recommended SKUs:

| SKU | vCPUs | RAM | Zones | Notes |
|-----|-------|-----|-------|-------|
| Standard_D2s_v6 | 2 | 8 GB | 1,2,3 | General purpose, latest generation |
| Standard_D4s_v6 | 4 | 16 GB | 1,2,3 | General purpose, good for most workloads |
| Standard_B2ps_v2 | 2 | 8 GB | 1,2,3 | Burstable, cost-effective |
| Standard_B4ps_v2 | 4 | 16 GB | 1,2,3 | Burstable, good for variable workloads |

## Troubleshooting VM Size Issues

### Common Error Messages:

1. **"VM size is only allowed in zones [X Y]"**
   - Solution: Either use only the allowed zones or choose a different VM size
   ```bash
   # Use only allowed zones
   --zones 1 3  # if only zones 1 and 3 are allowed
   
   # Or use a different VM size
   --node-vm-size Standard_D4s_v6
   ```

2. **"NotAvailableForSubscription"**
   - Solution: Choose a different VM size that's available for your subscription
   ```bash
   # Find alternatives
   az vm list-skus --location eastus2 --size Standard_D --output table | grep -v "NotAvailableForSubscription"
   ```

### Example: Adding a Node Pool with Available SKU

```bash
# Working example using Standard_D4s_v6
az aks nodepool add \
    --resource-group keda-rg \
    --cluster-name keda-training-aks \
    --name zredundantnp \
    --node-count 3 \
    --zones 1 2 3 \
    --node-vm-size Standard_D4s_v6 \
    --enable-cluster-autoscaler \
    --min-count 3 \
    --max-count 6 \
    --mode User
```

## Best Practices

1. **Always check availability first** before creating node pools
2. **Use latest generation VMs** (v5, v6) when possible for better performance
3. **Consider B-series VMs** for cost-effective solutions with variable workloads
4. **Test in your target region** as availability varies by region
5. **Have backup VM sizes** in case your preferred size is not available

## Quick Reference Commands

```bash
# Quick check for available D-series VMs in eastus2
az vm list-skus --location eastus2 --size Standard_D --output table | grep -v "NotAvailableForSubscription" | head -10

# Quick check for available B-series VMs in eastus2  
az vm list-skus --location eastus2 --size Standard_B --output table | grep -v "NotAvailableForSubscription" | head -10

# Check current AKS node pools
kubectl get nodes
az aks nodepool list --resource-group <rg-name> --cluster-name <cluster-name> --output table
```