# KEDA Training Guide: Setting Up the Environment and Connection String Authentication

## Learning Objectives
By the end of this training, you will:
- Set up an Azure environment with AKS and KEDA
- Create Azure Service Bus resources
- Implement KEDA with connection string authentication
- Understand the traditional approach to KEDA scaling

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
RG_NAME="keda-rg"
AKS_NAME="keda-training-aks"
SB_NAME="keda-training-sb-$(date +%s)"
SB_QUEUE_NAME="demo-queue"

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

### Step 3: Create Azure Service Bus (Traditional Approach)
```bash
# Create Service Bus namespace with local auth ENABLED (traditional approach)
az servicebus namespace create \
    --name $SB_NAME \
    --resource-group $RG_NAME

# Create queue
az servicebus queue create \
    --name $SB_QUEUE_NAME \
    --namespace $SB_NAME \
    --resource-group $RG_NAME

# Get Service Bus hostname
SB_HOSTNAME="${SB_NAME}.servicebus.windows.net"
echo "Service Bus Hostname: $SB_HOSTNAME"

# Get the connection string (traditional approach)
SB_CONNECTION_STRING=$(az servicebus namespace authorization-rule keys list \
    --resource-group $RG_NAME \
    --namespace-name $SB_NAME \
    --name RootManageSharedAccessKey \
    --query primaryConnectionString \
    --output tsv)

echo "Connection String obtained (will store in Kubernetes Secret)"
```

---

## Part 2: KEDA with Connection String Authentication (Traditional Approach)

### Step 1: Store Connection String in Kubernetes Secret

First, let's implement KEDA using the traditional connection string approach:

```bash
# Create a Kubernetes secret with the connection string
kubectl create secret generic servicebus-secret \
    --from-literal=connection="$SB_CONNECTION_STRING"
```

### Step 2: Create TriggerAuthentication with Connection String

```bash
kubectl apply -f - <<EOF
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: azure-servicebus-auth-connectionstring
  namespace: default
spec:
  secretTargetRef:
  - parameter: connection
    name: servicebus-secret
    key: connection
EOF
```

### Step 3: Deploy a Working KEDA ScaledObject (Traditional)

```bash
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: message-consumer-traditional
spec:
  replicas: 0  # Start with 0, KEDA will scale up
  selector:
    matchLabels:
      app: message-consumer-traditional
  template:
    metadata:
      labels:
        app: message-consumer-traditional
    spec:
      containers:
      - name: consumer
        image: ghcr.io/azure-samples/aks-app-samples/servicebusdemo:latest
        env:
        - name: OPERATION_MODE
          value: "consumer"
        - name: MESSAGE_COUNT
          value: "5"
        - name: AZURE_SERVICEBUS_QUEUE_NAME
          value: $SB_QUEUE_NAME
        - name: AZURE_SERVICEBUS_CONNECTION_STRING
          valueFrom:
            secretKeyRef:
              name: servicebus-secret
              key: connection
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: message-consumer-traditional-scaledobject
spec:
  scaleTargetRef:
    name: message-consumer-traditional
  minReplicaCount: 0
  maxReplicaCount: 10
  triggers:
  - type: azure-servicebus
    metadata:
      queueName: $SB_QUEUE_NAME
      messageCount: "5"  # Scale up for every 5 messages
    authenticationRef:
      name: azure-servicebus-auth-connectionstring
EOF
```

### Step 4: Test the Traditional Approach

```bash
# Create a producer to send messages
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: message-producer-traditional
spec:
  template:
    spec:
      containers:
      - name: producer
        image: ghcr.io/azure-samples/aks-app-samples/servicebusdemo:latest
        env:
        - name: OPERATION_MODE
          value: "producer"
        - name: MESSAGE_COUNT
          value: "20"
        - name: AZURE_SERVICEBUS_QUEUE_NAME
          value: $SB_QUEUE_NAME
        - name: AZURE_SERVICEBUS_CONNECTION_STRING
          valueFrom:
            secretKeyRef:
              name: servicebus-secret
              key: connection
      restartPolicy: Never
EOF

# Watch the scaling happen
watch kubectl get pods -l app=message-consumer-traditional

# In another terminal, monitor KEDA scaling decisions
kubectl get scaledobjects -w

# Check HPA that KEDA automatically created
kubectl get hpa
kubectl describe hpa keda-hpa-message-consumer-traditional-scaledobject
```

### Step 5: Verify It Works

```bash
# Check ScaledObject status
kubectl describe scaledobject message-consumer-traditional-scaledobject

# See the external metric that KEDA is providing to HPA
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1/namespaces/default/azure-servicebus-$SB_QUEUE_NAME" | jq

# Monitor KEDA operator logs
kubectl logs -n kube-system deployment/keda-operator -f

# Check queue message count
az servicebus queue show \
    --name $SB_QUEUE_NAME \
    --namespace $SB_NAME \
    --resource-group $RG_NAME \
    --query "messageCount"

# Verify scaling works - should scale from 0 to N pods based on queue depth
kubectl get pods -l app=message-consumer-traditional --watch
```

---

## Summary

### What We Accomplished
1. **Environment Setup**: Created Azure resources including AKS cluster with KEDA enabled
2. **KEDA Verification**: Confirmed KEDA components are running and external metrics API is registered
3. **Service Bus Setup**: Created Azure Service Bus namespace and queue for testing
4. **Traditional Authentication**: Implemented KEDA scaling using connection string authentication
5. **Testing**: Deployed producer and consumer applications to verify scaling behavior

### Key Observations
- KEDA extends HPA capabilities by providing external metrics
- Connection string approach works but has security implications
- Scale-to-zero functionality reduces resource costs
- KEDA automatically creates HPA resources to manage scaling

### Next Steps
- Explore security risks of connection string approach
- Learn about modern authentication with Workload Identity
- Implement more advanced KEDA scalers and configurations
- Set up monitoring and troubleshooting practices

---

## Additional Resources
- [KEDA Official Documentation](https://keda.sh/docs/)
- [KEDA Scalers Reference](https://keda.sh/docs/scalers/)
- [Azure Service Bus Documentation](https://learn.microsoft.com/en-us/azure/service-bus-messaging/)
- [KEDA Community Slack](https://kubernetes.slack.com/messages/CKZJ36A5D)

---

*This training guide demonstrates the basic setup and traditional approach to KEDA implementation with Azure Service Bus.*
