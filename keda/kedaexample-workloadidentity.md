# KEDA Training Guide: Modern Workload Identity Implementation

## Learning Objectives
By the end of this training, you will:
- Understand Azure AD Workload Identity and its security benefits
- Implement KEDA with secure, keyless authentication
- Deploy complete KEDA solutions with both ScaledObject and ScaledJob
- Monitor and verify KEDA scaling operations
- Configure advanced KEDA scaling behaviors and multi-trigger setups

## Prerequisites
- Basic understanding of Kubernetes and KEDA concepts
- Azure CLI installed and configured
- kubectl configured
- AKS cluster with KEDA and Workload Identity enabled
- Azure Service Bus namespace and queue already created

---

## Part 1: KEDA with Workload Identity (The Modern Solution)

### What is Workload Identity?
Azure AD Workload Identity is a secure method for Kubernetes workloads to access Azure resources using managed identities, eliminating the need for stored secrets.

### Benefits:
- 🔐 **No secrets in cluster**: Credentials are managed by Azure AD
- 🔄 **Automatic token refresh**: No manual credential rotation
- 🎯 **Least privilege**: Fine-grained access control
- 📊 **Auditing**: Full access logging in Azure AD

### Step 1: Create Managed Identity and Federated Credentials

```bash
# Create managed identity
MI_NAME="keda-demo-identity"
MI_CLIENT_ID=$(az identity create \
    --name $MI_NAME \
    --resource-group $RG_NAME \
    --query "clientId" \
    --output tsv)

echo "Managed Identity Client ID: $MI_CLIENT_ID"

# Get OIDC issuer URL
AKS_OIDC_ISSUER=$(az aks show \
    --name $AKS_NAME \
    --resource-group $RG_NAME \
    --query oidcIssuerProfile.issuerUrl \
    --output tsv)

echo "OIDC Issuer: $AKS_OIDC_ISSUER"
```

### Step 2: Create Federated Credentials

```bash
# Federated credential for workload service account
FED_WORKLOAD="fed-keda-workload"
az identity federated-credential create \
    --name $FED_WORKLOAD \
    --identity-name $MI_NAME \
    --resource-group $RG_NAME \
    --issuer $AKS_OIDC_ISSUER \
    --subject system:serviceaccount:default:$MI_NAME \
    --audience api://AzureADTokenExchange

# Federated credential for KEDA operator
FED_KEDA="fed-keda-operator"
az identity federated-credential create \
    --name $FED_KEDA \
    --identity-name $MI_NAME \
    --resource-group $RG_NAME \
    --issuer $AKS_OIDC_ISSUER \
    --subject system:serviceaccount:kube-system:keda-operator \
    --audience api://AzureADTokenExchange
```

### Step 3: Grant Azure Permissions

```bash
# Get managed identity object ID
MI_OBJECT_ID=$(az identity show \
    --name $MI_NAME \
    --resource-group $RG_NAME \
    --query "principalId" \
    --output tsv)

# Get Service Bus resource ID
SB_ID=$(az servicebus namespace show \
    --name $SB_NAME \
    --resource-group $RG_NAME \
    --query "id" \
    --output tsv)

# Assign Azure Service Bus Data Owner role
az role assignment create \
    --role "Azure Service Bus Data Owner" \
    --assignee-object-id $MI_OBJECT_ID \
    --assignee-principal-type ServicePrincipal \
    --scope $SB_ID
```

### Step 4: Enable Workload Identity on KEDA Operator

```bash
# Restart KEDA operator to inject workload identity environment variables
kubectl rollout restart deployment keda-operator -n kube-system

# Wait for restart
kubectl rollout status deployment keda-operator -n kube-system

# Verify workload identity environment variables
KEDA_POD_ID=$(kubectl get pods -n kube-system -l app.kubernetes.io/name=keda-operator -o jsonpath='{.items[0].metadata.name}')
kubectl describe pod $KEDA_POD_ID -n kube-system | grep -A 15 "Environment:"

# Look for these environment variables:
# AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_FEDERATED_TOKEN_FILE, AZURE_AUTHORITY_HOST
```

### Step 5: Create TriggerAuthentication with Workload Identity

```bash
kubectl apply -f - <<EOF
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: azure-servicebus-auth
  namespace: default
spec:
  podIdentity:
    provider: azure-workload
    identityId: $MI_CLIENT_ID
EOF
```

---

## Part 2: Implementing Complete KEDA Solution

### Step 1: Create Service Account for Workloads

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  annotations:
    azure.workload.identity/client-id: $MI_CLIENT_ID
  name: $MI_NAME
  namespace: default
EOF
```

### Step 2: Deploy Producer Job (Publish Messages)

```bash
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: message-producer
spec:
  template:
    metadata:
      labels:
        azure.workload.identity/use: "true"
    spec:
      serviceAccountName: $MI_NAME
      containers:
      - name: producer
        image: ghcr.io/azure-samples/aks-app-samples/servicebusdemo:latest
        env:
        - name: OPERATION_MODE
          value: "producer"
        - name: MESSAGE_COUNT
          value: "50"
        - name: AZURE_SERVICEBUS_QUEUE_NAME
          value: $SB_QUEUE_NAME
        - name: AZURE_SERVICEBUS_HOSTNAME
          value: $SB_HOSTNAME
      restartPolicy: Never
EOF
```

### Step 3: Deploy Consumer with KEDA ScaledObject

```bash
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: message-consumer
spec:
  replicas: 0  # Start with 0, KEDA will scale up
  selector:
    matchLabels:
      app: message-consumer
  template:
    metadata:
      labels:
        app: message-consumer
        azure.workload.identity/use: "true"
    spec:
      serviceAccountName: $MI_NAME
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
        - name: AZURE_SERVICEBUS_HOSTNAME
          value: $SB_HOSTNAME
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: message-consumer-scaledobject
spec:
  scaleTargetRef:
    name: message-consumer
  minReplicaCount: 0
  maxReplicaCount: 10
  triggers:
  - type: azure-servicebus
    metadata:
      queueName: $SB_QUEUE_NAME
      namespace: $SB_NAME
      messageCount: "5"  # Scale up for every 5 messages
    authenticationRef:
      name: azure-servicebus-auth
EOF
```

### Step 4: Alternative - Using ScaledJob for Batch Processing

```bash
kubectl apply -f - <<EOF
apiVersion: keda.sh/v1alpha1
kind: ScaledJob
metadata:
  name: message-processor-scaledjob
spec:
  jobTargetRef:
    template:
      metadata:
        labels:
          azure.workload.identity/use: "true"
      spec:
        serviceAccountName: $MI_NAME
        containers:
        - name: processor
          image: ghcr.io/azure-samples/aks-app-samples/servicebusdemo:latest
          env:
          - name: OPERATION_MODE
            value: "consumer"
          - name: MESSAGE_COUNT
            value: "10"
          - name: AZURE_SERVICEBUS_QUEUE_NAME
            value: $SB_QUEUE_NAME
          - name: AZURE_SERVICEBUS_HOSTNAME
            value: $SB_HOSTNAME
        restartPolicy: Never
  triggers:
  - type: azure-servicebus
    metadata:
      queueName: $SB_QUEUE_NAME
      namespace: $SB_NAME
      messageCount: "10"
    authenticationRef:
      name: azure-servicebus-auth
EOF
```

---

## Part 3: Monitoring and Verification

### Monitor Scaling Activity

```bash
# Watch the pods scaling
watch kubectl get pods -l app=message-consumer

# Check ScaledObject status
kubectl describe scaledobject message-consumer-scaledobject

# Check TriggerAuthentication status (workload identity)
kubectl describe triggerauthentication azure-servicebus-auth

# View KEDA operator logs
kubectl logs -n kube-system deployment/keda-operator

# Check the HPA that KEDA automatically created
kubectl get hpa
kubectl describe hpa keda-hpa-message-consumer-scaledobject

# Verify workload identity is working
kubectl logs -n kube-system deployment/keda-operator | grep -i "azure\|authentication\|token"

# Check queue length (requires Azure CLI)
az servicebus queue show \
    --name $SB_QUEUE_NAME \
    --namespace $SB_NAME \
    --resource-group $RG_NAME \
    --query "messageCount"
```

### Understanding the Scaling Metrics

```bash
# View all external metrics provided by KEDA
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1" | jq '.resources[].name'

# Get specific metric values for your Service Bus queue
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1/namespaces/default/azure-servicebus-$SB_QUEUE_NAME" | jq

# Check KEDA's metric server status
kubectl get apiservice v1beta1.external.metrics.k8s.io -o yaml

# Monitor scaling events
kubectl get events --field-selector reason=SuccessfulRescale
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1/namespaces/default/azure-servicebus-$SB_QUEUE_NAME" | jq .
```

---

## Part 4: Advanced KEDA Concepts

### ScaledObject vs ScaledJob
| Aspect | ScaledObject | ScaledJob |
|--------|--------------|-----------|
| **Target** | Deployment, StatefulSet | Kubernetes Job |
| **Use Case** | Long-running services | Batch processing |
| **Scale-to-zero** | ✅ Supported | ✅ Supported |
| **Job lifecycle** | Continuous | One-time execution |

### Multiple Triggers Example
```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: multi-trigger-example
spec:
  scaleTargetRef:
    name: myapp
  triggers:
  - type: azure-servicebus
    metadata:
      queueName: queue1
      messageCount: "5"
    authenticationRef:
      name: azure-servicebus-auth
  - type: prometheus
    metadata:
      serverAddress: http://prometheus:9090
      metricName: http_requests_per_second
      threshold: '100'
      query: sum(rate(http_requests_total[1m]))
```

### Scaling Behavior Configuration
```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: advanced-scaling
spec:
  scaleTargetRef:
    name: myapp
  advanced:
    restoreToOriginalReplicaCount: false
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: 300
          policies:
          - type: Percent
            value: 50
            periodSeconds: 60
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
  triggers:
  - type: azure-servicebus
    metadata:
      queueName: $SB_QUEUE_NAME
      namespace: $SB_NAME
      messageCount: "5"
    authenticationRef:
      name: azure-servicebus-auth
```

---

## Summary

### What We Accomplished
1. **Modern Authentication**: Implemented secure workload identity without storing secrets
2. **Complete Solution**: Deployed both ScaledObject and ScaledJob configurations
3. **Monitoring Setup**: Established comprehensive monitoring and verification processes
4. **Advanced Concepts**: Explored multi-trigger scenarios and custom scaling behaviors

### Key Security Improvements
- ✅ **Zero secrets**: No connection strings or credentials stored in cluster
- ✅ **Automatic rotation**: Azure AD handles token lifecycle management
- ✅ **Fine-grained permissions**: Least privilege access with Azure RBAC
- ✅ **Full auditing**: Complete logging through Azure AD sign-in logs

### Advanced Features Demonstrated
- **ScaledObject**: For long-running service scaling
- **ScaledJob**: For batch processing workloads
- **Multiple triggers**: Combining different scaling sources
- **Custom behaviors**: Fine-tuning scaling policies and stabilization windows

### Next Steps
- Implement other KEDA scalers (Prometheus, Redis, HTTP)
- Set up comprehensive monitoring and alerting
- Explore KEDA HTTP Add-on for HTTP-based scaling
- Implement in production environments with proper governance

---

## Additional Resources
- [KEDA Official Documentation](https://keda.sh/docs/)
- [Azure Workload Identity Documentation](https://learn.microsoft.com/en-us/azure/aks/workload-identity-overview)
- [KEDA Scalers Reference](https://keda.sh/docs/scalers/)
- [Azure Service Bus KEDA Scaler](https://keda.sh/docs/scalers/azure-service-bus/)
- [KEDA Community Slack](https://kubernetes.slack.com/messages/CKZJ36A5D)

---

*This training guide demonstrates modern, secure KEDA implementation using Azure AD Workload Identity for keyless authentication and advanced scaling configurations.*
