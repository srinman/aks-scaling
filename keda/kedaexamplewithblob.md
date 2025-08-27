# KEDA Training Guide: Blob Storage Scaling with Storage Key Authentication

## Learning Objectives
By the end of this training, you will:
- Set up an Azure environment with AKS and KEDA
- Create Azure Storage Account and Blob Container resources
- Implement KEDA with storage key authentication for blob scaling
- Understand blob-based autoscaling patterns

## Prerequisites
- Basic understanding of Kubernetes concepts (Pods, Deployments, HPA)
- Azure CLI installed and configured
- kubectl configured

---

## Part 1: Setting Up the Environment

### Step 1: Create Azure Resources
```bash
# Set variables
LOCATION="East US2"
RG_NAME="keda-blob-rg"
AKS_NAME="keda-blob-training-aks"
STORAGE_ACCOUNT_NAME="kedablob$(date +%s)"
CONTAINER_NAME="demo-blobs"

# Create resource group
az group create --name $RG_NAME --location "$LOCATION"

# Create AKS cluster with KEDA, Workload Identity, and OIDC Issuer
az aks create \
    --name $AKS_NAME \
    --resource-group $RG_NAME \
    --enable-workload-identity \
    --enable-oidc-issuer \
    --enable-keda \
    --node-count 2 \
    --generate-ssh-keys

# Get credentials
az aks get-credentials \
    --name $AKS_NAME \
    --resource-group $RG_NAME \
    --overwrite-existing
```

### Step 2: Verify KEDA Installation
```bash
# Check KEDA components
kubectl get pods -n kube-system | grep keda

# Expected output:
# keda-admission-webhooks-xxx    1/1     Running
# keda-operator-xxx              1/1     Running
# keda-operator-metrics-apiserver-xxx 1/1     Running

# Verify KEDA has registered as the external metrics provider
kubectl get apiservices | grep external.metrics.k8s.io
# Should show: v1beta1.external.metrics.k8s.io    kube-system/keda-operator-metrics-apiserver   True

# Check KEDA version and status
kubectl get deployment keda-operator -n kube-system -o yaml | grep image:
kubectl get scaledobjects -A  # Should be empty initially
kubectl get scaledjobs -A     # Should be empty initially

# Test KEDA's external metrics API
kubectl get --raw /apis/external.metrics.k8s.io/v1beta1 | jq '.groupVersion'
# Should return: "external.metrics.k8s.io/v1beta1"
```

### Step 3: Create Azure Storage Account and Blob Container
```bash
# Create Storage Account
az storage account create \
    --name $STORAGE_ACCOUNT_NAME \
    --resource-group $RG_NAME \
    --location "$LOCATION" \
    --sku Standard_LRS \
    --kind StorageV2

# Get storage account key
STORAGE_KEY=$(az storage account keys list \
    --account-name $STORAGE_ACCOUNT_NAME \
    --resource-group $RG_NAME \
    --query '[0].value' \
    --output tsv)

# Create blob container
az storage container create \
    --name $CONTAINER_NAME \
    --account-name $STORAGE_ACCOUNT_NAME \
    --account-key $STORAGE_KEY

echo "Storage Account: $STORAGE_ACCOUNT_NAME"
echo "Container: $CONTAINER_NAME"
echo "Storage Key obtained (will store in Kubernetes Secret)"
```

---

## Part 2: KEDA with Storage Key Authentication

### Step 1: Store Storage Key in Kubernetes Secret

```bash
# Create a Kubernetes secret with the storage account key
kubectl create secret generic storage-secret \
    --from-literal=storageKey="$STORAGE_KEY"
```

### Step 2: Create TriggerAuthentication with Storage Key

```bash
kubectl apply -f - <<EOF
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: azure-blob-auth-storagekey
  namespace: default
spec:
  secretTargetRef:
  - parameter: storageKey
    name: storage-secret
    key: storageKey
EOF
```

### Step 3: Deploy a Working KEDA ScaledObject for Blob Storage

```bash
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: blob-processor
spec:
  replicas: 0  # Start with 0, KEDA will scale up
  selector:
    matchLabels:
      app: blob-processor
  template:
    metadata:
      labels:
        app: blob-processor
    spec:
      containers:
      - name: processor
        image: mcr.microsoft.com/azure-cli:latest
        command: ["/bin/bash"]
        args:
        - -c
        - |
          echo "Blob processor started..."
          while true; do
            echo "Processing blobs from container: $CONTAINER_NAME"
            # Simulate blob processing work
            az storage blob list \
              --container-name $CONTAINER_NAME \
              --account-name $STORAGE_ACCOUNT_NAME \
              --account-key $STORAGE_KEY \
              --output table || true
            sleep 30
          done
        env:
        - name: STORAGE_ACCOUNT_NAME
          value: $STORAGE_ACCOUNT_NAME
        - name: CONTAINER_NAME
          value: $CONTAINER_NAME
        - name: STORAGE_KEY
          valueFrom:
            secretKeyRef:
              name: storage-secret
              key: storageKey
EOF
```

```bash
# Check deployment status
kubectl get deploy 
kubectl get hpa
```

```bash
kubectl apply -f - <<EOF
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: blob-processor-scaledobject
spec:
  scaleTargetRef:
    name: blob-processor
  minReplicaCount: 0
  maxReplicaCount: 10
  triggers:
  - type: azure-blob
    metadata:
      blobContainerName: $CONTAINER_NAME
      blobCount: "5"  # Scale up for every 5 blobs
      accountName: $STORAGE_ACCOUNT_NAME
    authenticationRef:
      name: azure-blob-auth-storagekey
EOF
```

Issue the following commands and understand metrics:
```bash
kubectl get deploy 
kubectl get hpa
kubectl get hpa keda-hpa-blob-processor-scaledobject -o yaml
```

### Step 4: Test the Blob Storage Scaling

```bash
# Create a job to upload test blobs
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: blob-uploader
spec:
  template:
    spec:
      containers:
      - name: uploader
        image: mcr.microsoft.com/azure-cli:latest
        command: ["/bin/bash"]
        args:
        - -c
        - |
          echo "Uploading test blobs..."
          for i in {1..15}; do
            echo "Test blob content \$i - \$(date)" > test-blob-\$i.txt
            az storage blob upload \
              --file test-blob-\$i.txt \
              --name test-blob-\$i.txt \
              --container-name $CONTAINER_NAME \
              --account-name $STORAGE_ACCOUNT_NAME \
              --account-key $STORAGE_KEY \
              --overwrite
            echo "Uploaded blob \$i"
            sleep 2
          done
          echo "Finished uploading 15 test blobs"
        env:
        - name: STORAGE_ACCOUNT_NAME
          value: $STORAGE_ACCOUNT_NAME
        - name: CONTAINER_NAME
          value: $CONTAINER_NAME
        - name: STORAGE_KEY
          valueFrom:
            secretKeyRef:
              name: storage-secret
              key: storageKey
      restartPolicy: Never
EOF

# Watch the scaling happen
watch kubectl get pods -l app=blob-processor

# In another terminal, monitor KEDA scaling decisions
kubectl get scaledobjects -w

# Check HPA that KEDA automatically created
kubectl get hpa
kubectl describe hpa keda-hpa-blob-processor-scaledobject
```

### Step 5: Verify It Works

```bash
# Check ScaledObject status
kubectl describe scaledobject blob-processor-scaledobject

# See the external metric that KEDA is providing to HPA
# First, get the metric name from the HPA that KEDA created
kubectl get hpa -o yaml | grep -A 5 external

# Use the correct metric name (KEDA generates names like s0-azure-blob-demo-blobs)
# Replace the metric name below with the actual one from your HPA
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1/namespaces/default/s0-azure-blob-demo-blobs?labelSelector=scaledobject.keda.sh%2Fname%3Dblob-processor-scaledobject" | jq

# Alternative: Query all available external metrics
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1" | jq '.resources[]'

# Monitor KEDA operator logs
kubectl logs -n kube-system deployment/keda-operator -f

# Check blob count in container
az storage blob list \
    --container-name $CONTAINER_NAME \
    --account-name $STORAGE_ACCOUNT_NAME \
    --account-key $STORAGE_KEY \
    --query "length(@)"

# Verify scaling works - should scale from 0 to N pods based on blob count
kubectl get pods -l app=blob-processor --watch
```

### Step 6: Test Scale Down by Removing Blobs

```bash
# Create a job to clean up blobs and test scale down
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: blob-cleaner
spec:
  template:
    spec:
      containers:
      - name: cleaner
        image: mcr.microsoft.com/azure-cli:latest
        command: ["/bin/bash"]
        args:
        - -c
        - |
          echo "Cleaning up test blobs..."
          az storage blob delete-batch \
            --source $CONTAINER_NAME \
            --account-name $STORAGE_ACCOUNT_NAME \
            --account-key $STORAGE_KEY \
            --pattern "test-blob-*.txt"
          echo "Finished cleaning blobs"
        env:
        - name: STORAGE_ACCOUNT_NAME
          value: $STORAGE_ACCOUNT_NAME
        - name: CONTAINER_NAME
          value: $CONTAINER_NAME
        - name: STORAGE_KEY
          valueFrom:
            secretKeyRef:
              name: storage-secret
              key: storageKey
      restartPolicy: Never
EOF

# Watch pods scale down to 0
watch kubectl get pods -l app=blob-processor
```

### Understanding KEDA External Metrics for Blob Storage

KEDA creates external metrics with specific naming conventions for Azure Blob:
- **Metric Name Format**: `s{trigger-index}-azure-blob-{container-name}`
- **Example**: `s0-azure-blob-demo-blobs` (first trigger, Azure Blob scaler, demo-blobs container)
- **Label Selector Required**: `scaledobject.keda.sh/name={scaledobject-name}`

**Common Issues:**
- ❌ `Error: scaledObject name is not specified` - Missing label selector
- ❌ Using container name directly instead of KEDA-generated metric name
- ❌ Incorrect storage account name or authentication
- ✅ Always check HPA YAML to get the correct metric name and selector

---

## Advanced Blob Scaling Patterns

### Pattern 1: Scale Based on Blob Prefix

```bash
kubectl apply -f - <<EOF
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: blob-processor-prefix-scaledobject
spec:
  scaleTargetRef:
    name: blob-processor
  minReplicaCount: 0
  maxReplicaCount: 10
  triggers:
  - type: azure-blob
    metadata:
      blobContainerName: $CONTAINER_NAME
      blobPrefix: "pending/"  # Only scale based on blobs with this prefix
      blobCount: "3"
      accountName: $STORAGE_ACCOUNT_NAME
    authenticationRef:
      name: azure-blob-auth-storagekey
EOF
```

### Pattern 2: Scale Based on Blob Delimiter

```bash
kubectl apply -f - <<EOF
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: blob-processor-delimiter-scaledobject
spec:
  scaleTargetRef:
    name: blob-processor
  minReplicaCount: 0
  maxReplicaCount: 10
  triggers:
  - type: azure-blob
    metadata:
      blobContainerName: $CONTAINER_NAME
      blobDelimiter: "/"  # Treat blobs as directories
      blobPrefix: "input/"
      blobCount: "2"
      accountName: $STORAGE_ACCOUNT_NAME
    authenticationRef:
      name: azure-blob-auth-storagekey
EOF
```

---

## Summary

### What We Accomplished
1. **Environment Setup**: Created Azure resources including AKS cluster with KEDA enabled
2. **KEDA Verification**: Confirmed KEDA components are running and external metrics API is registered
3. **Blob Storage Setup**: Created Azure Storage Account and blob container for testing
4. **Storage Key Authentication**: Implemented KEDA scaling using storage account key authentication
5. **Testing**: Deployed blob processor applications and tested scaling behavior with blob uploads/deletions

### Key Observations
- KEDA extends HPA capabilities by providing external metrics for blob storage
- Storage key approach works but consider security implications in production
- Scale-to-zero functionality reduces resource costs when no blobs are present
- KEDA automatically creates HPA resources to manage scaling based on blob count
- Blob scaling supports advanced patterns like prefix-based and delimiter-based scaling

### Blob Scaling Use Cases
- **Data Processing Pipelines**: Scale workers based on files waiting to be processed
- **ETL Workloads**: Scale extraction jobs based on new data files
- **Media Processing**: Scale video/image processing based on uploaded files
- **Batch Processing**: Scale compute resources based on pending work files

### Next Steps
- Explore security improvements with Managed Identity instead of storage keys
- Learn about blob metadata-based scaling
- Implement more advanced KEDA scalers and configurations
- Set up monitoring and troubleshooting practices for blob-based scaling

---

## Additional Resources
- [KEDA Azure Blob Scaler Documentation](https://keda.sh/docs/scalers/azure-blob/)
- [KEDA Official Documentation](https://keda.sh/docs/)
- [Azure Storage Documentation](https://learn.microsoft.com/en-us/azure/storage/)
- [KEDA Community Slack](https://kubernetes.slack.com/messages/CKZJ36A5D)

---

*This training guide demonstrates blob storage-based scaling with KEDA using Azure Storage Account key authentication.*
