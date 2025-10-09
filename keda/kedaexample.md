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

## ⚠️ Important Note
This guide uses **connection string authentication** which requires Azure Service Bus **local authentication to be enabled**. If your organization has Azure policies that disable local authentication, this approach will not work. In that case, use the **[kedaexample-workloadidentity.md](kedaexample-workloadidentity.md)** guide instead, which demonstrates modern Workload Identity authentication that works with disabled local auth.

---

## Part 1: Setting Up the Environment

### Step 1: Create Azure Resources
```bash
# Set variables
LOCATION="East US2"
RG_NAME="democlusterrg"
AKS_NAME="democluster"
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

### Alternative: Update Existing AKS Cluster

If you have an existing AKS cluster without these features, you can enable them with the following commands:

```bash
# Step 1: Enable Workload Identity and OIDC Issuer first
# Note: This requires cluster restart and may take 10-15 minutes
az aks update \
    --name $AKS_NAME \
    --resource-group $RG_NAME \
    --enable-workload-identity \
    --enable-oidc-issuer

# Wait for the update to complete, then enable KEDA
echo "Waiting for Workload Identity enablement to complete..."
echo "This may take 10-15 minutes as it requires node pool updates..."

# Step 2: Enable KEDA addon (after Workload Identity is enabled)
az aks update \
    --name $AKS_NAME \
    --resource-group $RG_NAME \
    --enable-keda

# Verify all features are enabled
az aks show \
    --name $AKS_NAME \
    --resource-group $RG_NAME \
    --query "{workloadIdentity:securityProfile.workloadIdentity,oidcIssuer:oidcIssuerProfile.enabled,keda:workloadAutoScalerProfile.keda.enabled}" \
    --output table

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

### Troubleshooting Cluster Updates

If you encounter issues during cluster updates:

```bash
# Check cluster provisioning state
az aks show \
    --name $AKS_NAME \
    --resource-group $RG_NAME \
    --query "provisioningState" \
    --output tsv

# Check node pool status (updates may restart nodes)
az aks nodepool list \
    --cluster-name $AKS_NAME \
    --resource-group $RG_NAME \
    --query "[].{name:name,provisioningState:provisioningState,powerState:powerState.code}" \
    --output table

# If KEDA pods are not starting, check cluster events
kubectl get events -n kube-system --sort-by='.lastTimestamp' | grep -i keda

# Check KEDA addon status specifically
az aks show \
    --name $AKS_NAME \
    --resource-group $RG_NAME \
    --query "workloadAutoScalerProfile.keda" \
    --output yaml
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

**What is TriggerAuthentication?**

TriggerAuthentication is a KEDA-specific Kubernetes resource that defines how KEDA should authenticate with external systems (like Azure Service Bus). It acts as a bridge between Kubernetes secrets and KEDA scalers, providing secure access to authentication credentials without exposing them in ScaledObject configurations.

**Important: Namespace Considerations**

TriggerAuthentication resources are **namespace-scoped**, meaning they can only be used by ScaledObjects in the same namespace. Key points:

- **Same Namespace Requirement**: The TriggerAuthentication must be created in the same namespace as:
  - The ScaledObject that references it
  - The Kubernetes Secret it references
  - The target Deployment/StatefulSet being scaled

- **Default Namespace**: In this example, we're using the `default` namespace for all resources
- **Production Environments**: Consider creating dedicated namespaces for different applications/teams
- **Cross-Namespace Access**: If you need to share authentication across namespaces, use:
  - `ClusterTriggerAuthentication` (cluster-scoped alternative)
  - Or duplicate the TriggerAuthentication in each required namespace

**Example Namespace Structure:**
```bash
# All resources in the same namespace (our approach)
kubectl get triggerauthentication,scaledobject,deployment,secret -n default

# Alternative: Dedicated namespace
kubectl create namespace keda-demo
# Then create all resources with: kubectl apply -f resource.yaml -n keda-demo
```

**Key Components Explained:**
- **apiVersion**: `keda.sh/v1alpha1` - Uses KEDA's custom resource definition
- **kind**: `TriggerAuthentication` - Tells Kubernetes this is a KEDA authentication resource
- **metadata.name**: `azure-servicebus-auth-connectionstring` - Name that will be referenced by ScaledObjects
- **spec.secretTargetRef**: Defines which Kubernetes secret contains the authentication data
  - **parameter**: `connection` - The parameter name that KEDA expects for Service Bus authentication
  - **name**: `servicebus-secret` - The name of the Kubernetes secret we created earlier
  - **key**: `connection` - The specific key within the secret that contains the connection string

**Why Use TriggerAuthentication?**
1. **Security**: Keeps sensitive data in Kubernetes secrets instead of hardcoding in ScaledObjects
2. **Reusability**: Multiple ScaledObjects can reference the same TriggerAuthentication
3. **Separation of Concerns**: Authentication logic is separated from scaling logic
4. **Flexibility**: Supports various authentication methods (secrets, service accounts, pod identity)

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

#### Step 3a: Deploy the Target Application

**What is this deployment?**

This deployment creates the application that KEDA will scale. It's a Service Bus message consumer that processes messages from our queue. Key characteristics:

- **Starts with 0 replicas**: KEDA will scale it up when messages arrive (scale-to-zero capability)
- **Message Consumer**: Processes messages from the Service Bus queue we created
- **Uses Connection String**: Authenticates to Service Bus using the secret we created
- **Processing Capacity**: Configured to process 5 messages per pod instance

**Why start with 0 replicas?**
- Demonstrates KEDA's scale-to-zero capability
- Saves resources when no work is available
- Shows reactive scaling based on actual workload

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
EOF
```

k get deploy 
k get hpa

#### Step 3b: Create the ScaledObject

**What is a ScaledObject?**

ScaledObject is the core KEDA resource that defines scaling behavior based on external metrics. It tells KEDA:
- **Which deployment to scale** (scaleTargetRef)
- **Scaling boundaries** (min/max replicas)
- **What metrics to monitor** (triggers)
- **How to authenticate** (authenticationRef)

**How this ScaledObject works:**
1. **Monitors Azure Service Bus queue depth** every 30 seconds (default polling interval)
2. **Scales up when**: Queue has more than 5 messages (messageCount threshold)
3. **Scales down when**: Queue is empty or below threshold
4. **Creates an HPA automatically** with name: `keda-hpa-message-consumer-traditional-scaledobject`
5. **Enables scale-to-zero** unlike standard HPA

**Key Configuration:**
- **minReplicaCount: 0**: Allows scaling down to zero pods
- **maxReplicaCount: 10**: Maximum 10 pods for this workload
- **messageCount: "5"**: Each pod handles ~5 messages, so scale formula is: `ceil(queue_depth / 5)`

```bash
kubectl apply -f - <<EOF
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

Issue the following commands and understand metrics: uner spec: 
k get deploy 
k get hpa
k get hpa keda-hpa-message-consumer-traditional-scaledobject -o yaml


#### Step 3c: KEDA and HPA 


Apply this following - creates same HPA as in HPA demo. 
```bash
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
```

k get hpa php-apache-hpa -n default -o yaml
k get hpa keda-hpa-message-consumer-traditional-scaledobject -o yaml 

**Understanding HPA: Standard vs KEDA**

After running the above commands, you'll see two different HPA configurations that demonstrate the fundamental relationship between standard HPA and KEDA. Let's analyze their key differences:

### **1. Standard Application HPA (php-apache-hpa)**

**Purpose**: Traditional CPU-based scaling for application workloads
```yaml
metrics:
- resource:
    name: cpu
    target:
      averageUtilization: 50
      type: Utilization
  type: Resource
```

**Characteristics:**
- **Metric Type**: `Resource` (CPU utilization)
- **Metric Source**: Kubernetes metrics server (built-in)
- **Scaling Range**: 1-10 replicas (no scale-to-zero)
- **Management**: Manually created and managed
- **Target**: Application deployment (`php-apache`)

### **2. KEDA External Metrics HPA (keda-hpa-message-consumer-traditional-scaledobject)**

**Purpose**: External metrics-based scaling for event-driven workloads
```yaml
metrics:
- external:
    metric:
      name: s0-azure-servicebus-demo-queue
      selector:
        matchLabels:
          scaledobject.keda.sh/name: message-consumer-traditional-scaledobject
    target:
      averageValue: "5"
      type: AverageValue
  type: External
```

**Characteristics:**
- **Metric Type**: `External` (Service Bus queue depth)
- **Metric Source**: KEDA external metrics API
- **Scaling Range**: 1-10 replicas (with KEDA scale-to-zero)
- **Management**: KEDA operator managed (auto-generated)
- **Target**: Message processing deployment (`message-consumer-traditional`)

### **Key Differences Explained**

| Aspect | Standard HPA | KEDA HPA |
|--------|-------------|-----------|
| **Metric Source** | Kubernetes metrics server | KEDA external metrics API |
| **Metric Type** | `Resource` (cpu/memory) | `External` (custom metrics) |
| **Scale-to-Zero** | ❌ No (min: 1) | ✅ Yes (KEDA managed) |
| **Label Selectors** | Not required | Required (`scaledobject.keda.sh/name`) |
| **Management** | Manual creation | Auto-generated by KEDA |
| **Owner References** | None | Owned by ScaledObject |
| **Metric Names** | Standard (`cpu`, `memory`) | Generated (`s0-azure-servicebus-*`) |

### **Understanding the KEDA-HPA Relationship**

#### **KEDA Extends HPA, Doesn't Replace It**

```
┌─────────────────────────────────────────────────────────────┐
│                    KEDA Architecture                        │
└─────────────────────────────────────────────────────────────┘

    ScaledObject (User Creates)
           │
           ▼
    ┌──────────────────┐    Creates & Manages    ┌─────────────┐
    │  KEDA Operator   │ ─────────────────────► │     HPA     │
    └──────────────────┘                        └─────────────┘
           │                                           │
           │ Polls External System                     │ Scales
           ▼                                           ▼
    ┌──────────────────┐                        ┌─────────────┐
    │ Azure Service Bus│                        │ Deployment  │
    │ (Queue Depth)    │                        │   Pods      │
    └──────────────────┘                        └─────────────┘
           │
           ▼
    ┌──────────────────┐
    │ External Metrics │
    │      API         │
    └──────────────────┘
```

#### **How Scale-to-Zero Works**

```yaml
# Standard HPA Limitation
minReplicas: 1  # Cannot go below 1

# KEDA Solution
# 1. KEDA monitors external metric (queue depth)
# 2. When queue is empty, KEDA scales deployment directly to 0
# 3. When messages arrive, KEDA scales to minReplicas (1)
# 4. HPA takes over for scaling beyond minReplicas
```

### **Practical Implications**

#### **When to Use Standard HPA:**
- CPU/Memory based scaling
- Traditional web applications
- Consistent traffic patterns
- Simple scaling requirements

#### **When to Use KEDA:**
- Event-driven architectures
- Queue-based processing
- External metrics (databases, APIs, custom metrics)
- Need scale-to-zero capability
- Cost optimization important

### **Key Learning Points**

1. **KEDA is HPA-Compatible**: KEDA creates standard HPAs, just with external metrics
2. **External Metrics Require Selectors**: Label selectors identify which ScaledObject provides the metric
3. **Generated Metric Names**: KEDA creates metric names like `s0-azure-servicebus-demo-queue`
4. **Ownership Model**: KEDA HPAs are owned by ScaledObjects (automatic cleanup)
5. **Scale-to-Zero**: KEDA handles this separately from HPA's normal operation

### **Common Troubleshooting**

#### **Standard HPA Issues:**
```bash
# Check metrics server availability
kubectl top nodes
kubectl get apiservices | grep metrics.k8s.io
```

#### **KEDA HPA Issues:**
```bash
# Check KEDA external metrics API
kubectl get apiservices | grep external.metrics

# Check ScaledObject status
kubectl describe scaledobject message-consumer-traditional-scaledobject

# Verify metric availability
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1" | jq '.resources[]'
```

### **Summary: KEDA Enhances HPA**

- **Standard HPA**: Limited to CPU/memory metrics from Kubernetes
- **KEDA HPA**: Extends to any external metric while maintaining HPA compatibility
- **Best of Both**: Use standard HPA for resource-based scaling, KEDA for event-driven scaling
- **Architecture**: KEDA acts as a bridge between external systems and Kubernetes HPA framework 


### Step 4: Test the Traditional Approach

**What does this step accomplish?**

This step creates the workload that will trigger KEDA scaling. We deploy a message producer job that sends messages to the Azure Service Bus queue, which will cause KEDA to scale up the consumer deployment from 0 to multiple replicas based on queue depth.

**Key Functions:**
- **Triggers KEDA Scaling**: Adds messages to the queue that KEDA is monitoring
- **Demonstrates Scale-from-Zero**: Shows how KEDA scales up from 0 replicas when work arrives
- **Tests the Complete Flow**: Validates that ScaledObject, TriggerAuthentication, and external metrics work together
- **Provides Observable Load**: Creates a measurable workload (20 messages) that will result in predictable scaling behavior

**Expected Behavior:**
1. **Initial State**: Consumer deployment has 0 replicas (scale-to-zero)
2. **Producer Runs**: Job sends 20 messages to Service Bus queue
3. **KEDA Detects Load**: Monitors queue depth via external metrics API
4. **Scaling Triggered**: KEDA scales consumer deployment based on messageCount threshold (5 messages per pod)
5. **HPA Takes Over**: Auto-generated HPA manages scaling decisions
6. **Pods Process Work**: Consumer pods start processing messages from the queue

### ⚠️ **Pre-deployment Verification: Check Service Bus Local Authentication**

**Important**: Before deploying the producer job, we need to verify that Azure Service Bus local authentication is enabled. If disabled (often enforced by Azure policies), connection string authentication will fail.

```bash
# Check if local authentication is enabled
# First, verify that required variables are set
if [[ -z "$SB_NAME" || -z "$RG_NAME" ]]; then
    echo "❌ ERROR: Required variables are not set"
    echo "   Please ensure you have run the environment setup commands:"
    echo "   SB_NAME and RG_NAME variables must be defined"
    echo ""
    echo "🔧 Quick fix - set variables manually:"
    echo "   export RG_NAME=\"democlusterrg\""
    echo "   export SB_NAME=\"your-servicebus-name\""
    echo ""
    echo "   Or re-run the setup commands from Step 1"
    exit 1
fi

echo "Checking Service Bus: $SB_NAME in Resource Group: $RG_NAME"

SB_LOCAL_AUTH_STATUS=$(az servicebus namespace show \
    --name "$SB_NAME" \
    --resource-group "$RG_NAME" \
    --query "disableLocalAuth" \
    --output tsv)

# Check if the command succeeded
if [ $? -ne 0 ]; then
    echo "❌ ERROR: Failed to query Service Bus namespace"
    echo "   Please verify:"
    echo "   1. Service Bus namespace '$SB_NAME' exists"
    echo "   2. Resource group '$RG_NAME' exists"
    echo "   3. You have proper Azure CLI authentication"
    echo ""
    echo "   Run: az servicebus namespace list --resource-group $RG_NAME"
    exit 1
fi

echo "Service Bus Local Auth Disabled: $SB_LOCAL_AUTH_STATUS"

if [ "$SB_LOCAL_AUTH_STATUS" = "true" ]; then
    echo ""
    echo "❌ ERROR: Local Authentication is DISABLED on Service Bus namespace"
    echo "   Connection string authentication will not work."
    echo ""
    echo "🔧 SOLUTIONS:"
    echo ""
    echo "1. Enable local authentication (if allowed by policy):"
    echo "   az servicebus namespace update \\"
    echo "       --name $SB_NAME \\"
    echo "       --resource-group $RG_NAME \\"
    echo "       --disable-local-auth false"
    echo ""
    echo "2. If Azure policy prevents enabling local auth, clean up and use Workload Identity:"
    echo "   # Clean up current deployment"
    echo "   kubectl delete scaledobject message-consumer-traditional-scaledobject"
    echo "   kubectl delete deployment message-consumer-traditional"
    echo "   kubectl delete triggerauthentication azure-servicebus-auth-traditional"
    echo "   kubectl delete secret servicebus-secret"
    echo ""
    echo "   # Follow the secure Workload Identity approach instead:"
    echo "   echo 'Please follow the kedaexample-workloadidentity.md guide'"
    echo "   echo 'which demonstrates modern, secure authentication without connection strings'"
    echo ""
    echo "⚠️  STOPPING HERE - Fix authentication issue before proceeding"
    exit 1
else
    echo "✅ Local Authentication is ENABLED - Connection strings will work"
    echo "   Proceeding with producer job deployment..."
fi
```

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

# NEW: Use KEDA Demo Monitor for comprehensive analysis
python3 keda-demo-monitor.py

# Monitor continuously during testing
watch -n 15 python3 keda-demo-monitor.py
```

### KEDA Demo Monitor Tool

For comprehensive KEDA monitoring during demonstrations, use the included `keda-demo-monitor.py` script:

**Features:**
- **KEDA Component Health**: Verifies all KEDA components are running
- **ScaledObject Analysis**: Shows configuration, triggers, and conditions
- **HPA Comparison**: Compares standard vs KEDA-generated HPAs
- **External Metrics**: Lists available external metrics and their values
- **Service Bus Integration**: Shows Azure Service Bus queue depths
- **Scaling Insights**: Provides real-time scaling analysis and predictions

**Usage:**
```bash
# Basic analysis
python3 keda-demo-monitor.py

# Monitor specific namespace
python3 keda-demo-monitor.py keda-demo

# Monitor specific ScaledObject
python3 keda-demo-monitor.py default message-consumer-traditional-scaledobject

# Continuous monitoring during demo
watch -n 10 python3 keda-demo-monitor.py
```

**Example Output Analysis:**
```bash
KEDA COMPONENT HEALTH
------------------------------------------------------------
✅ KEDA Installed: Version v2.16.1
✅ External Metrics API: Available
✅ operator: Running

SCALEDOBJECTS ANALYSIS
------------------------------------------------------------
ScaledObject: message-consumer-traditional-scaledobject
  Target Deployment: message-consumer-traditional
  Scaling Range: 0-10 replicas
  Scale-to-Zero: ✅ Enabled
  Triggers: azure-servicebus (5 messages per pod)

AZURE SERVICE BUS STATUS
------------------------------------------------------------
✅ Queue: keda-training-sb-xxx/demo-queue - 0 messages

KEDA DEMO INSIGHTS
------------------------------------------------------------
💤 Scale-to-Zero State:
  • No messages in queue → KEDA scaled to zero
  • Event-driven → Will scale up when work arrives
```

### Step 5: Verify It Works

```bash
# Check ScaledObject status
kubectl describe scaledobject message-consumer-traditional-scaledobject

# See the external metric that KEDA is providing to HPA
# First, get the metric name from the HPA that KEDA created
kubectl get hpa -o yaml | grep -A 5 external

# Use the correct metric name (KEDA generates names like s0-azure-servicebus-demo-queue)
# Replace the metric name below with the actual one from your HPA
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1/namespaces/default/s0-azure-servicebus-demo-queue?labelSelector=scaledobject.keda.sh%2Fname%3Dmessage-consumer-traditional-scaledobject" | jq

# Alternative: Query all available external metrics
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1" | jq '.resources[]'

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

### Understanding KEDA External Metrics

KEDA creates external metrics with specific naming conventions:
- **Metric Name Format**: `s{trigger-index}-{scaler-type}-{queue-name}`
- **Example**: `s0-azure-servicebus-demo-queue` (first trigger, Service Bus scaler, demo-queue)
- **Label Selector Required**: `scaledobject.keda.sh/name={scaledobject-name}`

**Common Issues:**
- ❌ `Error: scaledObject name is not specified` - Missing label selector
- ❌ Using queue name directly instead of KEDA-generated metric name
- ✅ Always check HPA YAML to get the correct metric name and selector

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
