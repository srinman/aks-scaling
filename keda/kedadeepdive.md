# KEDA Training Guide: From Standard HPA to Event-Driven Autoscaling

## Learning Objectives
By the end of this training, you will:
- Understand the limitations of standard Kubernetes HPA
- Learn KEDA concepts and architecture
- Deploy KEDA without workload identity and understand the challenges
- Implement KEDA with workload identity for secure authentication
- Scale applications based on Azure Service Bus queue length

## Prerequisites
- Basic understanding of Kubernetes concepts (Pods, Deployments, HPA)
- Azure CLI installed and configured
- kubectl configured

---

## Part 1: Understanding HPA Metrics APIs and Their Limitations

### Overview: The Three Types of Metrics APIs Architecture

Before diving into KEDA, it's crucial to understand how Kubernetes HPA actually works and why KEDA chose to extend rather than replace it. HPA can use three distinct metrics APIs, each with different capabilities and complexity levels.

```text
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           Kubernetes HPA Architecture Overview                       │
└─────────────────────────────────────────────────────────────────────────────────────┘

Type 1: Resource Metrics (Simple)
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌──────────────┐
│   Metrics       │───▶│  metrics.k8s.io  │───▶│       HPA       │───▶│  Scale       │
│   Server        │    │      API         │    │   Controller    │    │  Target      │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └──────────────┘
        ▲                                                                      │
        │                                                                      ▼
┌─────────────────┐                                                   ┌──────────────┐
│   Node/Pod      │                                                   │ Deployment/  │
│   Resources     │                                                   │ StatefulSet  │
│  (CPU/Memory)   │                                                   │              │
└─────────────────┘                                                   └──────────────┘

Type 2: Custom Metrics (Moderate Complexity)
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌──────────────┐
│   Prometheus    │    │ Prometheus       │    │custom.metrics   │    │       HPA    │
│   Server        │───▶│ Adapter          │───▶│   .k8s.io       │───▶│  Controller  │
└─────────────────┘    └──────────────────┘    │      API        │    └──────┬───────┘
        ▲                       ▲               └─────────────────┘           │
        │                       │                                             ▼
┌─────────────────┐    ┌──────────────────┐                          ┌──────────────┐
│  App Metrics    │    │   Config Rules   │                          │ Deployment/  │
│(Request Rate,   │    │   Mapping        │                          │ StatefulSet  │
│ Queue Length)   │    │                  │                          │              │
└─────────────────┘    └──────────────────┘                          └──────────────┘

Type 3: External Metrics (Complex)
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌──────────────┐
│  External       │    │   External       │    │external.metrics │    │       HPA    │
│  Systems        │───▶│   Metrics        │───▶│   .k8s.io       │───▶│  Controller  │
│(Cloud APIs,     │    │   Adapter        │    │      API        │    └──────┬───────┘
│ SaaS Services)  │    │                  │    │                 │           │
└─────────────────┘    └──────────────────┘    └─────────────────┘           ▼
                               ▲                                     ┌──────────────┐
                               │                                     │ Deployment/  │
                       ┌──────────────────┐                         │ StatefulSet  │
                       │ Custom Adapter   │                         │              │
                       │ Implementation   │                         └──────────────┘
                       │   (Complex!)     │
                       └──────────────────┘

🎯 KEDA's Role: Acts as the Universal External Metrics Adapter
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                    KEDA                                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────┐  │
│  │Azure Service│  │   RabbitMQ  │  │ Prometheus  │  │   Redis     │  │   HTTP  │  │
│  │Bus Scaler   │  │   Scaler    │  │   Scaler    │  │   Scaler    │  │ Scaler  │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  └─────────┘  │
└─────────────────────────────────────┬───────────────────────────────────────────────┘
                                      │ Single external.metrics.k8s.io registration
                                      ▼
                            ┌─────────────────┐    ┌──────────────┐
                            │       HPA       │───▶│ Scale Target │
                            │   Controller    │    │              │
                            └─────────────────┘    └──────────────┘
```

### The Three Types of Metrics APIs in Kubernetes

#### 1. Resource Metrics API (metrics.k8s.io)
- **Source**: Metrics Server (most common)
- **Metrics**: Built-in Kubernetes metrics like CPU and memory usage
- **Use Case**: Basic scaling based on resource utilization
- **Complexity**: ✅ Simple - Works out of the box in most clusters

#### 2. Custom Metrics API (custom.metrics.k8s.io)
- **Source**: Prometheus Adapter, custom metrics adapters
- **Metrics**: Application-specific metrics (e.g., request rate, active connections)
- **Use Case**: Scaling based on business or application-level metrics
- **Complexity**: ⚠️ Moderate - Requires additional components and configuration

#### 3. External Metrics API (external.metrics.k8s.io)
- **Source**: External systems (cloud monitoring, third-party APIs)
- **Metrics**: Metrics not tied to Kubernetes objects (e.g., queue depth, external API latency)
- **Use Case**: Scaling based on external service load or SLAs
- **Complexity**: 🔴 Complex - Requires external metric adapters and complex setup

### HPA Metrics API Comparison Table

| Metric Type | API Used | Source Component | Setup Complexity | Scale-to-Zero | Typical Use Case |
|-------------|----------|------------------|-----------------|---------------|------------------|
| **Resource** | `metrics.k8s.io` | Metrics Server | ✅ Simple | ❌ No | CPU/memory-based scaling |
| **Custom** | `custom.metrics.k8s.io` | Prometheus Adapter, etc. | ⚠️ Moderate | ❌ No | App-specific metrics (e.g., RPS) |
| **External** | `external.metrics.k8s.io` | External metric adapter | 🔴 Complex | ❌ No | Third-party metrics (e.g., cloud queues) |

---

## Part 2: Hands-on Example - All Three HPA Types

Let's demonstrate all three types with working examples to understand their capabilities and limitations.

### Understanding Metrics API Registration

Before we dive into examples, let's understand how these metrics APIs are registered in your cluster:

```bash
# Check which metrics APIs are available and their providers
kubectl get apiservices | grep metrics.k8s.io

# Expected output shows the three metrics APIs:
# v1beta1.metrics.k8s.io                 kube-system/metrics-server   True        
# v1beta1.custom.metrics.k8s.io          monitoring/prometheus-adapter True      
# v1beta1.external.metrics.k8s.io        keda/keda-operator           True        

# Get detailed information about each API service
kubectl get apiservice v1beta1.metrics.k8s.io -o yaml
kubectl get apiservice v1beta1.custom.metrics.k8s.io -o yaml  
kubectl get apiservice v1beta1.external.metrics.k8s.io -o yaml

# Check if metrics APIs are healthy and responding
echo "Testing Resource Metrics API (metrics.k8s.io)..."
kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes | jq '.items[0].metadata.name' && echo "✅ Resource metrics API is working" || echo "❌ Resource metrics not available"

echo "Testing Custom Metrics API (custom.metrics.k8s.io)..."
kubectl get --raw /apis/custom.metrics.k8s.io/v1beta1 | jq '.groupVersion' && echo "✅ Custom metrics API is working" || echo "❌ Custom metrics not available"

echo "Testing External Metrics API (external.metrics.k8s.io)..."
kubectl get --raw /apis/external.metrics.k8s.io/v1beta1 | jq '.groupVersion' && echo "✅ External metrics API is working" || echo "❌ External metrics not available"
```

**Key Observations:**
- Each API can only have **ONE** provider/adapter registered
- The `SERVICE` column shows which service handles each API
- KEDA registers itself as the **single** external metrics provider
- This is why multiple external metrics adapters conflict!

**Prerequisites for this section:**
- Helm installed: `curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash`
- Sufficient cluster resources (this will install Prometheus stack)

### Setup: Deploy a Sample Application

```bash
# Create a simple web application for testing
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sample-app
spec:
  replicas: 2
  selector:
    matchLabels:
      app: sample-app
  template:
    metadata:
      labels:
        app: sample-app
    spec:
      containers:
      - name: app
        image: nginx:alpine
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 512Mi
        ports:
        - containerPort: 80
---
apiVersion: v1
kind: Service
metadata:
  name: sample-app-service
spec:
  selector:
    app: sample-app
  ports:
  - port: 80
    targetPort: 80
  type: ClusterIP
EOF
```

### Type 1: Resource Metrics API Example (Works Immediately)

#### Architecture: Resource Metrics Flow
```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    Type 1: Resource Metrics API Architecture                   │
└─────────────────────────────────────────────────────────────────────────────────┘

Step 1: Metrics Collection
┌─────────────────┐    ┌─────────────────┐
│    Kubelet      │───▶│  Metrics Server │
│  (Node Agent)   │    │  (Aggregator)   │
└─────────────────┘    └─────────┬───────┘
         ▲                       │
         │                       │ Exposes metrics.k8s.io API
┌─────────────────┐              ▼
│   Pod CPU/      │    ┌─────────────────┐
│   Memory        │    │ Kubernetes API  │
│   Usage         │    │    Server       │
└─────────────────┘    └─────────┬───────┘
                                 │
Step 2: HPA Decision Making      │ API calls
┌─────────────────┐              ▼
│       HPA       │    ┌─────────────────┐
│   Controller    │◄───│ metrics.k8s.io  │
│                 │    │      API        │
└─────────┬───────┘    └─────────────────┘
          │
          │ Scaling decisions
          ▼
Step 3: Scaling Action
┌─────────────────┐
│  Deployment/    │
│  StatefulSet    │
│  Replica Count  │
└─────────────────┘

✅ Pros: Simple, works out-of-the-box, reliable
❌ Cons: Limited to CPU/Memory, no scale-to-zero, reactive only
```

```bash
# Create HPA based on CPU utilization
kubectl apply -f - <<EOF
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: sample-app-cpu-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: sample-app
  minReplicas: 1  # Cannot scale to zero
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
EOF

# Check HPA status
kubectl get hpa sample-app-cpu-hpa
kubectl describe hpa sample-app-cpu-hpa

# Test resource metrics API directly
kubectl top nodes    # Shows node resource usage via metrics.k8s.io
kubectl top pods     # Shows pod resource usage via metrics.k8s.io

# Verify the resource metrics API is working
kubectl get --raw /apis/metrics.k8s.io/v1beta1/pods | jq '.items[] | select(.metadata.name | startswith("sample-app")) | {name: .metadata.name, cpu: .containers[0].usage.cpu, memory: .containers[0].usage.memory}'
```

**Observations:**
- ✅ Simple configuration (CPU/memory only)
- ✅ Works immediately with metrics-server
- ❌ Cannot scale to zero (minReplicas: 1 minimum)
- ❌ Limited to basic resource metrics

### Type 2: Custom Metrics API Example (Let's Make It Work!)

#### Architecture: Custom Metrics Flow
```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│                   Type 2: Custom Metrics API Architecture                      │
└─────────────────────────────────────────────────────────────────────────────────┘

Step 1: Metrics Collection & Storage
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Application    │───▶│   Prometheus    │───▶│   Time Series   │
│  /metrics       │    │     Server      │    │    Database     │
│  Endpoint       │    │  (Scraping)     │    │   (Storage)     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         ▲
┌─────────────────┐
│ ServiceMonitor  │
│  (Discovery)    │
└─────────────────┘

Step 2: Metrics Adaptation
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Prometheus    │───▶│  Prometheus     │───▶│custom.metrics   │
│    Server       │    │    Adapter      │    │   .k8s.io       │
│  (Query PromQL) │    │ (Translation)   │    │     API         │
└─────────────────┘    └─────────────────┘    └─────────┬───────┘
                                ▲                       │
                       ┌─────────────────┐              │
                       │ Configuration   │              │
                       │ Rules & Mapping │              │
                       └─────────────────┘              │

Step 3: HPA Consumption                                  │
┌─────────────────┐                                     │
│       HPA       │◄────────────────────────────────────┘
│   Controller    │    API calls for custom metrics
│                 │
└─────────┬───────┘
          │ Scaling decisions
          ▼
┌─────────────────┐
│  Deployment/    │
│  StatefulSet    │
│  Replica Count  │
└─────────────────┘

⚠️  Pros: Business metrics, application-aware scaling
❌  Cons: Complex setup, multiple components, configuration-heavy
```

**🎯 Let's install Prometheus and Prometheus Adapter to demonstrate custom metrics:**

#### Step 2.1: Install Prometheus Stack

```bash
# Add Prometheus Helm repository
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Install Prometheus with basic configuration
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
  --set prometheus.prometheusSpec.podMonitorSelectorNilUsesHelmValues=false \
  --wait

# Wait for Prometheus to be ready
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=prometheus -n monitoring --timeout=300s
```

#### Step 2.2: Install Prometheus Adapter

```bash
# Install Prometheus Adapter for custom metrics
helm install prometheus-adapter prometheus-community/prometheus-adapter \
  --namespace monitoring \
  --set prometheus.url=http://prometheus-kube-prometheus-prometheus.monitoring.svc \
  --set prometheus.port=9090 \
  --wait

# Verify custom metrics API is available
kubectl get apiservices | grep custom.metrics
```

#### Step 2.3: Deploy App with Prometheus Metrics

```bash
# Deploy an enhanced sample app that exposes metrics
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sample-app-with-metrics
  labels:
    app: sample-app-with-metrics
spec:
  replicas: 2
  selector:
    matchLabels:
      app: sample-app-with-metrics
  template:
    metadata:
      labels:
        app: sample-app-with-metrics
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8080"
        prometheus.io/path: "/metrics"
    spec:
      containers:
      - name: app
        image: nginx/nginx-prometheus-exporter:0.10.0
        args:
          - -nginx.scrape-uri=http://localhost:8080/nginx_status
        ports:
        - containerPort: 9113
          name: metrics
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
          limits:
            cpu: 200m
            memory: 256Mi
      - name: nginx
        image: nginx:alpine
        ports:
        - containerPort: 8080
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
          limits:
            cpu: 200m
            memory: 256Mi
        volumeMounts:
        - name: nginx-config
          mountPath: /etc/nginx/conf.d
      volumes:
      - name: nginx-config
        configMap:
          name: nginx-config
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: nginx-config
data:
  default.conf: |
    server {
        listen 8080;
        location / {
            return 200 "Hello from NGINX with metrics!";
            add_header Content-Type text/plain;
        }
        location /nginx_status {
            stub_status on;
            access_log off;
        }
    }
---
apiVersion: v1
kind: Service
metadata:
  name: sample-app-with-metrics-service
  labels:
    app: sample-app-with-metrics
spec:
  selector:
    app: sample-app-with-metrics
  ports:
  - port: 8080
    targetPort: 8080
    name: http
  - port: 9113
    targetPort: 9113
    name: metrics
---
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: sample-app-with-metrics
  labels:
    app: sample-app-with-metrics
spec:
  selector:
    matchLabels:
      app: sample-app-with-metrics
  endpoints:
  - port: metrics
    path: /metrics
EOF
```

##### Check if the metrics endpoint is accessible
kubectl get pods -l app=sample-app-with-metrics

##### Get the pod name
METRICS_POD=$(kubectl get pods -l app=sample-app-with-metrics -o jsonpath='{.items[0].metadata.name}')

##### Port forward to access metrics directly
kubectl port-forward $METRICS_POD 9113:9113 &
PF_PID=$!

##### Check metrics endpoint (should show nginx metrics)
curl http://localhost:9113/metrics

##### Stop port forwarding
kill $PF_PID

#### Step 2.4: Generate Load to Create Metrics

```bash
# Create a load generator to produce custom metrics
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: load-generator
spec:
  template:
    spec:
      containers:
      - name: load-generator
        image: busybox
        command: ["/bin/sh"]
        args:
        - -c
        - |
          while true; do
            wget -q -O- http://sample-app-with-metrics-service.default.svc.cluster.local:8080/ || true
            sleep 0.5
          done
      restartPolicy: Never
  backoffLimit: 1000
EOF
```

#### Step 2.5: Configure Prometheus Adapter for Custom Metrics

```bash
# Update Prometheus Adapter with custom metrics configuration
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: adapter-config
  namespace: monitoring
data:
  config.yaml: |
    rules:
    - seriesQuery: 'nginx_connections_active{namespace!="",pod!=""}'
      resources:
        overrides:
          namespace: {resource: "namespace"}
          pod: {resource: "pod"}
      name:
        matches: "^nginx_connections_(.*)$"
        as: "nginx_connections_\${1}"
      metricsQuery: 'sum(<<.Series>>{<<.LabelMatchers>>}) by (<<.GroupBy>>)'
    - seriesQuery: 'nginx_http_requests_total{namespace!="",pod!=""}'
      resources:
        overrides:
          namespace: {resource: "namespace"}
          pod: {resource: "pod"}
      name:
        matches: "^nginx_http_requests_(.*)$"
        as: "nginx_http_requests_\${1}_per_second"
      metricsQuery: 'rate(<<.Series>>{<<.LabelMatchers>>}[1m])'
EOF

# Restart prometheus-adapter to pick up new config
kubectl rollout restart deployment prometheus-adapter -n monitoring
kubectl rollout status deployment prometheus-adapter -n monitoring
```

#### Step 2.6: Verify Custom Metrics Are Available

```bash
# Wait a few minutes for metrics to be collected, then check
sleep 120

# List available custom metrics
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1" | jq -r '.resources[].name' | grep -i nginx || echo "Metrics not yet available, waiting..."

# Check if our specific metric is available
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/default/pods/*/nginx_connections_active" | jq . || echo "Metric not ready yet"

# Alternative: Check nginx HTTP requests metric
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/default/pods/*/nginx_http_requests_total_per_second" | jq . || echo "HTTP requests metric not ready yet"
```

#### Step 2.7: Create Working Custom Metrics HPA

```bash
# Now create an HPA that uses custom metrics
kubectl apply -f - <<EOF
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: sample-app-custom-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: sample-app-with-metrics
  minReplicas: 1
  maxReplicas: 10
  metrics:
  - type: Pods
    pods:
      metric:
        name: nginx_connections_active
      target:
        type: AverageValue
        averageValue: "5"  # Scale up if more than 5 active connections per pod
EOF

# Check HPA status (should now show actual metric values)
kubectl get hpa sample-app-custom-hpa
kubectl describe hpa sample-app-custom-hpa

# Test custom metrics API directly
kubectl get --raw /apis/custom.metrics.k8s.io/v1beta1 | jq
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/default/pods/*/nginx_connections_active" | jq

# List all available custom metrics
kubectl get --raw /apis/custom.metrics.k8s.io/v1beta1 | jq '.resources[].name' | sort

# Check Prometheus adapter logs
kubectl logs -n monitoring deployment/prometheus-adapter

# Verify Prometheus adapter configuration
kubectl get configmap -n monitoring prometheus-adapter -o yaml
```

#### Step 2.8: Observe Custom Metrics Scaling

```bash
# Watch the scaling happen
watch kubectl get hpa sample-app-custom-hpa

# In another terminal, you can generate more load:
# kubectl scale job load-generator --replicas=3
```

**✅ Success! You now have a working Custom Metrics API example with:**
- Prometheus collecting application metrics
- Prometheus Adapter exposing metrics to `custom.metrics.k8s.io`  
- HPA scaling based on `http_requests_per_second` custom metric

### Type 3: External Metrics API Example (Most Complex)

#### Architecture: External Metrics Flow
```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│                  Type 3: External Metrics API Architecture                     │
└─────────────────────────────────────────────────────────────────────────────────┘

Step 1: External Data Sources
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Azure Service │    │   Amazon SQS    │    │   Redis Queue   │
│      Bus        │    │     Queue       │    │    Length       │
│   Queue Length  │    │    Depth        │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │                       │                       │
         ▼                       ▼                       ▼

Step 2: Custom External Adapters (The Problem!)
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│    Azure SB     │    │   Amazon SQS    │    │     Redis       │
│    Adapter      │    │    Adapter      │    │    Adapter      │
│  (Custom Build) │    │ (Custom Build)  │    │ (Custom Build)  │
└─────────┬───────┘    └─────────┬───────┘    └─────────┬───────┘
          │                      │                      │
          │ ❌ Only ONE can register!                   │
          │                      │                      │
          └──────────────────────┼──────────────────────┘
                                 ▼
Step 3: API Registration Conflict
┌─────────────────────────────────────────────────────────────────┐
│                external.metrics.k8s.io API                     │
│              ⚠️  SINGLE REGISTRATION ONLY!                     │
│                                                                 │
│  Last registered adapter wins, others become unreachable!      │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
Step 4: HPA Attempts to Scale
┌─────────────────┐
│       HPA       │◄─── ❌ "unable to get external metric" errors
│   Controller    │      
│                 │      
└─────────────────┘      

🔴 Problem: Building & maintaining separate adapters for each external system
🔴 Problem: Only one external adapter can work at a time
🔴 Problem: Complex authentication & configuration for each adapter
```

#### KEDA's Solution: Unified External Metrics Adapter
```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        KEDA: The Solution Architecture                         │
└─────────────────────────────────────────────────────────────────────────────────┘

Step 1: Multiple External Sources (Same as above)
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Azure Service │    │   Amazon SQS    │    │   Redis Queue   │
│      Bus        │    │     Queue       │    │    Length       │
│   Queue Length  │    │    Depth        │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │                       │                       │
         ▼                       ▼                       ▼

Step 2: KEDA Unified Adapter (The Solution!)
┌─────────────────────────────────────────────────────────────────┐
│                          KEDA Operator                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────┐  │
│  │Azure Service│  │ Amazon SQS  │  │   Redis     │  │ 60+   │  │
│  │Bus Scaler   │  │   Scaler    │  │   Scaler    │  │Others │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └───────┘  │
│                                                                 │
│  • Built-in authentication handling                            │
│  • Standardized configuration                                  │
│  • Scale-to-zero support                                       │
│  • Unified metrics collection                                  │
└─────────────────────────┬───────────────────────────────────────┘
                          │ Single external.metrics.k8s.io registration
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│               external.metrics.k8s.io API                      │
│                  ✅ Single Registration                        │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────┐
│       HPA       │◄─── ✅ All metrics available through one adapter
│   Controller    │      ✅ Consistent scaling behavior
│                 │      ✅ Scale-to-zero capability
└─────────┬───────┘
          │ Intelligent scaling decisions
          ▼
┌─────────────────┐
│  Deployment/    │
│  StatefulSet    │
│  (0 to N pods)  │
└─────────────────┘
```

**🔴 This example demonstrates the complexity - it won't work without external adapters:**

```bash
# This would require an external metrics adapter
kubectl apply -f - <<EOF
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: sample-app-external-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: sample-app
  minReplicas: 1
  maxReplicas: 10
  metrics:
  - type: External
    external:
      metric:
        name: azure_servicebus_queue_length  # This would need an external adapter
        selector:
          matchLabels:
            queue: "demo-queue"
      target:
        type: Value
        value: "10"
EOF

# Check the failure
kubectl describe hpa sample-app-external-hpa
# You'll see: "unable to get external metric"

# Try to test external metrics API directly (will fail)
kubectl get --raw /apis/external.metrics.k8s.io/v1beta1 | jq || echo "External metrics API not available"

# Check what's registered for external metrics
kubectl get apiservice v1beta1.external.metrics.k8s.io -o yaml

# You'll see the SERVICE field shows which component should provide external metrics
# If KEDA is installed, it shows: keda/keda-operator
# If nothing is installed, the API returns errors
```

### Observations from the Examples

```bash
# Check all HPAs
kubectl get hpa

# Now you should see:
# NAME                      REFERENCE              TARGETS   MINPODS   MAXPODS   REPLICAS
# sample-app-cpu-hpa        Deployment/sample-app  0%/70%    1         10        2
# sample-app-custom-hpa     Deployment/sample-app-with-metrics  5/10 (avg)  1  10  3
# sample-app-external-hpa   Deployment/sample-app  <unknown>/10   1    10        2

# The custom metrics HPA now works! 🎉

# Notice the complexity we just went through:
# 1. Installed Prometheus (monitoring system)  
# 2. Installed Prometheus Adapter (metrics bridge)
# 3. Configured custom metrics rules
# 4. Created ServiceMonitor for metrics collection
# 5. Generated load to produce metrics
# 6. Waited for metrics to be available
```

**🎓 Key Learning Point**: This demonstrates why KEDA is valuable - imagine doing this setup for every external system you want to scale on (Azure Service Bus, Redis, RabbitMQ, etc.)!

### Clean Up Example Resources

```bash
# Clean up the HPA demonstration resources
kubectl delete hpa sample-app-cpu-hpa sample-app-custom-hpa sample-app-external-hpa
kubectl delete deployment sample-app sample-app-with-metrics
kubectl delete service sample-app-service sample-app-with-metrics-service
kubectl delete servicemonitor sample-app-with-metrics
kubectl delete job load-generator

# Optional: Clean up Prometheus (if you don't want to keep it)
# helm uninstall prometheus-adapter -n monitoring
# helm uninstall prometheus -n monitoring
# kubectl delete namespace monitoring
```

### Complete Environment Cleanup (Start Fresh)

If you want to completely clean up and start testing from the beginning:

```bash
#!/bin/bash
echo "🧹 Starting complete KEDA and HPA cleanup..."

# Delete all HPA objects
echo "Deleting all HPA objects..."
kubectl delete hpa --all --all-namespaces

# Delete all KEDA ScaledObjects
echo "Deleting all KEDA ScaledObjects..."
kubectl delete scaledobjects --all --all-namespaces

# Delete all KEDA ScaledJobs  
echo "Deleting all KEDA ScaledJobs..."
kubectl delete scaledjobs --all --all-namespaces

# Delete all KEDA TriggerAuthentications
echo "Deleting all KEDA TriggerAuthentications..."
kubectl delete triggerauthentications --all --all-namespaces

# Delete all training deployments and services
echo "Deleting training deployments..."
kubectl delete deployment sample-app sample-app-with-metrics message-consumer message-consumer-traditional --ignore-not-found=true

echo "Deleting training services..."
kubectl delete service sample-app-service sample-app-with-metrics-service --ignore-not-found=true

# Delete training jobs
echo "Deleting training jobs..."
kubectl delete job load-generator message-producer message-producer-traditional --ignore-not-found=true

# Delete ServiceMonitors
echo "Deleting ServiceMonitors..."
kubectl delete servicemonitor sample-app-with-metrics --ignore-not-found=true

# Delete secrets used in training
echo "Deleting training secrets..."
kubectl delete secret servicebus-secret --ignore-not-found=true

# Delete ConfigMaps created during training
echo "Deleting training ConfigMaps..."
kubectl delete configmap adapter-config -n monitoring --ignore-not-found=true

echo "✅ Cleanup completed! You can now start fresh with the training."
echo ""
echo "To verify cleanup:"
echo "kubectl get hpa,scaledobjects,scaledjobs,triggerauthentications --all-namespaces"
echo "kubectl get deployments,services,jobs | grep -E 'sample-app|message-|load-'"
```

### Quick Cleanup Verification

```bash
# Verify everything is cleaned up
echo "Checking for remaining KEDA and HPA objects..."
kubectl get hpa,scaledobjects,scaledjobs,triggerauthentications --all-namespaces

echo "Checking for training deployments..."
kubectl get deployments,services,jobs | grep -E 'sample-app|message-|load-' || echo "No training objects found"

echo "Checking KEDA operator status (should still be running)..."
kubectl get pods -n kube-system | grep keda
```

---

## Part 3: The HPA Limitations and KEDA's Strategic Solution

### Why Standard HPA Falls Short for Event-Driven Scaling

From our examples above, you can see the challenges:

1. **Resource Metrics**: ✅ Works but only for CPU/Memory
2. **Custom Metrics**: ⚠️ Requires complex Prometheus setup
3. **External Metrics**: 🔴 Requires building custom adapters

### The "Upstream Limitations" Explained

The statement "Due to upstream limitations, KEDA must be the only installed external metric adapter" refers to a fundamental architectural constraint in Kubernetes:

#### The Single External Metrics Adapter Problem

```text
┌─────────────────────────────────────────────────────────────┐
│                    Kubernetes API Server                    │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              external.metrics.k8s.io API                   │
│                  (Single Registration)                     │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼ Only ONE can be registered!
        ┌─────────────────────────────────┐
        │    External Metrics Adapter     │
        │   (KEDA, Custom Adapter, etc.)  │
        └─────────────────────────────────┘
```

**The Problem**: Kubernetes only allows **one external metrics adapter** to be registered for the `external.metrics.k8s.io` API. If you try to install multiple adapters:

- Only the last one registered will work
- Previous adapters become unreachable  
- HPAs will fail with "unable to get external metric" errors
- No automatic failover or load balancing

#### KEDA's Strategic Design Decision

Instead of creating a completely new scaling system, KEDA cleverly:

1. **Uses existing HPA**: Leverages battle-tested Kubernetes scaling logic
2. **Provides external metrics**: Acts as the single external metrics adapter
3. **Handles complexity**: Manages connections to 60+ external services
4. **Enables scale-to-zero**: Adds this capability on top of HPA

```text
Traditional Approach (Complex):
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Custom    │    │   Custom    │    │   Custom    │
│  Adapter 1  │    │  Adapter 2  │    │  Adapter 3  │
│ (Prometheus)│    │ (RabbitMQ)  │    │ (Azure SB)  │
└─────────────┘    └─────────────┘    └─────────────┘
       ▲                  ▲                  ▲
       │ Can't coexist!   │                  │
       └──────────────────┼──────────────────┘
                          ▼
                ❌ Only one can work!

KEDA Approach (Unified):
┌─────────────────────────────────────────────────────────────┐
│                        KEDA                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │ Prometheus  │  │   RabbitMQ  │  │  Azure SB   │   ...  │
│  │   Scaler    │  │   Scaler    │  │   Scaler    │        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────┘
                          ▲
                          │ Single external metrics adapter
                          ▼
                ✅ All services work together!
```

---

## Part 4: KEDA Introduction - The Unified Solution

### Architectural Evolution: From Fragmented to Unified

#### The Traditional Approach (Problematic)
```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    Traditional Multi-Adapter Approach                          │
│                              (Doesn't Work!)                                   │
└─────────────────────────────────────────────────────────────────────────────────┘

External Systems:
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│Azure Service│  │   RabbitMQ  │  │ Prometheus  │  │    Redis    │  │   HTTP API  │
│    Bus      │  │   Queue     │  │   Metrics   │  │   Queue     │  │  Endpoint   │
└─────┬───────┘  └─────┬───────┘  └─────┬───────┘  └─────┬───────┘  └─────┬───────┘
      │                │                │                │                │
      ▼                ▼                ▼                ▼                ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│   Custom    │  │   Custom    │  │ Prometheus  │  │   Custom    │  │   Custom    │
│ Azure SB    │  │  RabbitMQ   │  │   Adapter   │  │   Redis     │  │    HTTP     │
│  Adapter    │  │   Adapter   │  │             │  │   Adapter   │  │   Adapter   │
└─────┬───────┘  └─────┬───────┘  └─────┬───────┘  └─────┬───────┘  └─────┬───────┘
      │                │                │                │                │
      └────────────────┼────────────────┼────────────────┼────────────────┘
                       │                │                │
              ❌ CONFLICT! Only ONE can register!      │
                       │                                 │
                       ▼                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    external.metrics.k8s.io API                                 │
│                  ⚠️ Single Registration Limit                                  │
│                                                                                 │
│  Result: Last adapter wins, others fail with "unable to get metric" errors    │
└─────────────────────────┬───────────────────────────────────────────────────────┘
                          │
                          ▼ Inconsistent behavior
┌─────────────────┐
│       HPA       │
│   Controller    │
└─────────────────┘
```

#### KEDA's Unified Approach (The Solution!)
```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           KEDA Unified Architecture                            │
│                               (It Works!)                                      │
└─────────────────────────────────────────────────────────────────────────────────┘

External Systems (Same):
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│Azure Service│  │   RabbitMQ  │  │ Prometheus  │  │    Redis    │  │   HTTP API  │
│    Bus      │  │   Queue     │  │   Metrics   │  │   Queue     │  │  Endpoint   │
└─────┬───────┘  └─────┬───────┘  └─────┬───────┘  └─────┬───────┘  └─────┬───────┘
      │                │                │                │                │
      ▼                ▼                ▼                ▼                ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              KEDA Operator                                     │
│                            (Single Adapter)                                    │
│                                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────┐ │
│  │Azure Service│  │  RabbitMQ   │  │ Prometheus  │  │    Redis    │  │ HTTP  │ │
│  │Bus Scaler   │  │   Scaler    │  │   Scaler    │  │   Scaler    │  │Scaler │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  └───────┘ │
│                                                                                 │
│  ✅ Built-in Authentication    ✅ Unified Configuration                        │
│  ✅ Scale-to-Zero Support      ✅ Consistent Behavior                         │
│  ✅ 60+ Pre-built Scalers     ✅ Single Point of Management                   │
└─────────────────────────────────┬───────────────────────────────────────────────┘
                                  │ Single external.metrics.k8s.io registration
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    external.metrics.k8s.io API                                 │
│                     ✅ Single, Stable Registration                            │
│                                                                                 │
│  Result: All external metrics work harmoniously through one adapter           │
└─────────────────────────┬───────────────────────────────────────────────────────┘
                          │
                          ▼ Consistent, reliable scaling
┌─────────────────┐      ┌─────────────────┐
│       HPA       │─────▶│   Scale Target  │
│   Controller    │      │ (Deployment/    │
│                 │      │  StatefulSet)   │
│  • Rate Limiting│      │                 │
│  • Stabilization│      │ ✅ 0 to N pods  │
│  • Multi-metrics│      │ ✅ Event-driven │
└─────────────────┘      └─────────────────┘
```

### What is KEDA?
**Kubernetes Event-driven Autoscaling (KEDA)** is a single-purpose, lightweight component that strategically extends Kubernetes autoscaling capabilities by:
- Acting as the **unified external metrics adapter**
- Supporting **scale-to-zero** functionality  
- Working **alongside** the standard HPA (doesn't replace it)
- Providing **60+ built-in scalers** for various external services

### KEDA's Architectural Brilliance

Rather than reinventing scaling logic, KEDA leverages the existing, battle-tested HPA mechanism:

```text
┌─────────────────────────────────────────────────────────────┐
│                      KEDA Operator                         │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌───────┐ │
│  │ Azure   │ │RabbitMQ │ │Postgres │ │Prometheus│ │ HTTP  │ │
│  │Service  │ │ Scaler  │ │ Scaler  │ │ Scaler   │ │Scaler │ │
│  │Bus      │ │         │ │         │ │          │ │       │ │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └───────┘ │
└─────────────────────────┬───────────────────────────────────┘
                          │ Single external.metrics.k8s.io adapter
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              Kubernetes HPA (existing logic)                │
│         • Scaling decisions                                 │
│         • Rate limiting                                     │  
│         • Stabilization windows                            │
│         • Multiple metrics support                         │
└─────────────────────────┬───────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    Your Workload                           │
│              (Deployment/StatefulSet)                      │
└─────────────────────────────────────────────────────────────┘
```

### Why This Design is Genius

1. **Solves the "Single Adapter" Problem**: One adapter supporting multiple external sources
2. **Leverages Proven HPA Logic**: No need to reimplement scaling algorithms
3. **Adds Scale-to-Zero**: Enhances HPA without breaking compatibility
4. **Simplifies Operations**: One component to manage, not dozens of adapters
5. **Future-Proof**: Benefits from HPA improvements automatically

### KEDA Architecture Deep Dive
```
External Events → KEDA Scalers → KEDA Metrics Server → HPA → Scale Target
     ↓                 ↓              ↓              ↓          ↓
[Queue Messages] → [Scaler Logic] → [Metrics API] → [Scale Decision] → [Pod Count]
[DB Connections] 
[HTTP Requests]
[Custom Metrics]
```

### Key KEDA Components
1. **KEDA Operator**: Manages scaling based on external events
2. **Metrics Server**: Provides external metrics to HPA
3. **Scalers**: Connect to external event sources (60+ built-in scalers)
4. **Custom Resource Definitions (CRDs)**:
   - `ScaledObject`: For scaling Deployments/StatefulSets
   - `ScaledJob`: For scaling Jobs
   - `TriggerAuthentication`: For secure authentication

### KEDA Benefits
- ✅ **Scale-to-zero**: Save costs when no demand
- ✅ **Event-driven**: React to real business metrics
- ✅ **Rich scalers**: 60+ built-in scalers for various services
- ✅ **Cloud-native**: Supports major cloud providers
- ✅ **Secure**: Multiple authentication methods

---

## Part 5: Setting Up the Environment

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

## Part 6: KEDA with Connection String Authentication (Traditional Approach)

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

## Part 7: Security Risks of Connection String Approach

### 🚨 Critical Security Issues with Connection Strings

#### 1. **Secrets Stored in Cluster**
- Connection strings contain credentials stored as Kubernetes secrets
- Secrets are only base64 encoded (not encrypted at rest by default)
- Anyone with cluster access can decode secrets: `kubectl get secret servicebus-secret -o yaml`

#### 2. **Broad Permissions**
- Connection strings typically have broad permissions (often RootManageSharedAccessKey)
- No fine-grained access control
- If compromised, attacker has full access to Service Bus namespace

#### 3. **Secret Rotation Challenges**
- Manual secret rotation required
- Application downtime during credential updates
- No automatic key rollover

#### 4. **Credential Sprawl**
- Same connection string used across multiple environments
- Difficult to track where credentials are used
- Hard to audit access patterns

#### 5. **No Native Azure AD Integration**
- Can't leverage Azure AD Conditional Access
- No centralized identity management
- Limited audit logging capabilities

### Let's Examine the Security Risk

```bash
# Anyone with kubectl access can see the connection string
echo "Decoding the secret stored in cluster:"
kubectl get secret servicebus-secret -o jsonpath="{.data.connection}" | base64 --decode
echo ""
echo ""
echo "☝️ This connection string provides full access to the Service Bus namespace!"
```

### Example Attack Scenario
```text
1. Attacker gains read access to Kubernetes cluster
2. Extracts connection string from secret
3. Uses connection string to:
   - Read/modify/delete messages
   - Create/delete queues and topics  
   - Access billing information
   - Potentially pivot to other Azure resources
```

---

## Part 8: Modern Security with Workload Identity

### What is Azure AD Workload Identity?
Azure AD Workload Identity eliminates stored secrets by using **federated identity credentials** and **managed identities**.

### How It Works
```text
1. Pod requests Azure token using Kubernetes service account token
2. Azure AD validates the token against federated credential
3. Azure AD issues Azure access token
4. Pod uses Azure token to access Service Bus
5. Token automatically refreshes (no manual rotation)
```

### Security Benefits Comparison

| Aspect | Connection String | Workload Identity |
|--------|------------------|-------------------|
| **Secrets in cluster** | ❌ Yes (base64) | ✅ No secrets |
| **Automatic rotation** | ❌ Manual | ✅ Automatic |
| **Fine-grained access** | ❌ Broad permissions | ✅ RBAC control |
| **Azure AD integration** | ❌ No | ✅ Full integration |
| **Audit logging** | ❌ Limited | ✅ Complete |
| **Conditional access** | ❌ Not supported | ✅ Supported |
| **Zero-trust ready** | ❌ No | ✅ Yes |

### Migration Steps: From Connection String to Workload Identity

Let's now upgrade our Service Bus to use modern security:

```bash
# Clean up the traditional approach first
kubectl delete scaledobject message-consumer-traditional-scaledobject
kubectl delete deployment message-consumer-traditional
kubectl delete job message-producer-traditional
kubectl delete triggerauthentication azure-servicebus-auth-connectionstring
kubectl delete secret servicebus-secret

# Update Service Bus to disable local auth (modern security requirement)
echo "Updating Service Bus to disable local authentication..."
az servicebus namespace update \
    --name $SB_NAME \
    --resource-group $RG_NAME \
    --disable-local-auth true

echo "✅ Service Bus now requires Azure AD authentication (connection strings disabled)"
```

---

## Part 9: KEDA with Workload Identity (The Modern Solution)

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

## Part 10: Implementing Complete KEDA Solution

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

## Part 11: Monitoring and Verification

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

## Part 12: Advanced KEDA Concepts

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

## Part 13: Troubleshooting Common Issues

### Issue 1: Authentication Failures
**Symptoms**: ScaledObject shows authentication errors
**Solution**:
```bash
# Check federated credentials
az identity federated-credential list \
    --identity-name $MI_NAME \
    --resource-group $RG_NAME

# Verify KEDA operator has workload identity variables
kubectl describe pod -n kube-system -l app.kubernetes.io/name=keda-operator
```

### Issue 2: Pods Not Scaling
**Symptoms**: Messages in queue but no pods created
**Solution**:
```bash
# Check ScaledObject events
kubectl describe scaledobject message-consumer-scaledobject

# Check HPA created by KEDA
kubectl get hpa

# View KEDA operator logs
kubectl logs -n kube-system deployment/keda-operator --tail=50
```

### Issue 3: Scale-to-Zero Not Working
**Symptoms**: Pods don't scale down to zero
**Solution**:
```bash
# Verify minReplicaCount is 0
kubectl get scaledobject message-consumer-scaledobject -o yaml | grep minReplicaCount

# Check if queue is actually empty
az servicebus queue show \
    --name $SB_QUEUE_NAME \
    --namespace $SB_NAME \
    --resource-group $RG_NAME \
    --query "messageCount"
```

---

## Part 14: Best Practices and Security

### Security Best Practices
1. **Use Workload Identity**: Eliminates stored secrets
2. **Least Privilege**: Grant minimal required permissions
3. **Namespace Isolation**: Use TriggerAuthentication in appropriate namespaces
4. **Regular Auditing**: Monitor Azure AD sign-in logs

### Performance Best Practices
1. **Right-size triggers**: Don't set messageCount too low
2. **Use stabilization windows**: Prevent thrashing
3. **Monitor costs**: Scale-to-zero saves money but monitor cold starts
4. **Test scaling policies**: Verify behavior under load

### Monitoring and Observability
```bash
# Enable KEDA metrics
kubectl apply -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: keda-operator-metrics-apiserver
  namespace: kube-system
  labels:
    app: keda-operator-metrics-apiserver
spec:
  ports:
  - name: https
    port: 443
    targetPort: 6443
  selector:
    app: keda-operator-metrics-apiserver
EOF
```

---

## Part 15: Clean Up Resources

```bash
# Delete Kubernetes resources
kubectl delete scaledobject --all
kubectl delete triggerauthentication --all
kubectl delete job --all
kubectl delete deployment --all
kubectl delete serviceaccount $MI_NAME

# Delete Azure resources
az group delete --name $RG_NAME --yes --no-wait
```

---

## Summary

### What We Learned
1. **Standard HPA limitations**: CPU/Memory based, no scale-to-zero
2. **KEDA advantages**: Event-driven, scale-to-zero, 60+ scalers
3. **Security evolution**: From connection strings to Workload Identity
4. **Practical implementation**: Real-world Azure Service Bus scaling

### Key Takeaways
- KEDA extends HPA capabilities without replacing it
- Workload Identity provides secure, keyless authentication
- Scale-to-zero capability can significantly reduce costs
- External event sources enable reactive scaling
- Proper monitoring and troubleshooting are essential

### Next Steps
- Explore other KEDA scalers (Prometheus, Redis, HTTP, etc.)
- Implement KEDA in production workloads
- Set up monitoring and alerting for KEDA operations
- Consider KEDA HTTP Add-on for HTTP-based scaling

---

## Additional Resources
- [KEDA Official Documentation](https://keda.sh/docs/)
- [KEDA Scalers Reference](https://keda.sh/docs/scalers/)
- [Azure Workload Identity Documentation](https://learn.microsoft.com/en-us/azure/aks/workload-identity-overview)
- [KEDA Community Slack](https://kubernetes.slack.com/messages/CKZJ36A5D)

---

*This training guide demonstrates the evolution from traditional HPA to modern event-driven autoscaling with KEDA and secure authentication practices.*
