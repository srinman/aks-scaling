# AKS Scaling Learning Guides

This repository covers various scaling mechanisms in Kubernetes, from basic pod scaling to advanced node provisioning strategies.

## 🚀 Introduction to Kubernetes Scaling

Scaling in Kubernetes involves multiple dimensions to ensure applications can handle varying workloads efficiently and cost-effectively:

- **Pod Scaling**: Horizontally scaling application instances based on metrics like CPU, memory, or custom metrics
- **Node Scaling**: Automatically adding or removing worker nodes to accommodate pod resource demands
- **Vertical Scaling**: Adjusting resource requests and limits for existing pods (CPU and memory)
- **Custom Metrics Scaling**: Scaling based on application-specific metrics from external sources
- **Event-Driven Scaling**: Scaling triggered by external events like message queues, storage events, or HTTP requests

Each scaling approach addresses different aspects of application performance, availability, and resource optimization. Understanding when and how to use each method is crucial for building resilient, efficient Kubernetes applications.

## 📚 Available Guides

| Guide | Description |
|-------|-------------|
| [HPA](hpa/) | Horizontal Pod Autoscaler - Scale pods based on CPU, memory, and custom metrics |
| [CAS](cas/) | Cluster AutoScaler - Automatically scale AKS cluster nodes up and down |
| [KEDA](keda/) | Kubernetes Event-Driven Autoscaling - Scale based on external metrics and events |
| [NAP](nap/) | Node Auto Provisioning - Advanced node scaling with Karpenter for optimal VM selection |
| [VPA](vpa/) | WORK-IN-PROGRESS Vertical Pod Autoscaler - Automatically adjust pod resource requests and limits |
| [Basics](basics/) | Foundational concepts and VM SKU management for AKS scaling |

## 🛠️ Prerequisites

- Azure CLI 2.76.0 or later
- kubectl installed and configured
- Azure subscription with appropriate permissions
- Basic understanding of Kubernetes concepts (pods, deployments, services)


## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     AKS Scaling Stack                      │
├─────────────────────────────────────────────────────────────┤
│  Application Layer                                         │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐          │
│  │   HPA   │ │  KEDA   │ │   VPA   │ │  Custom │          │
│  │ (Pods)  │ │(Events) │ │(Vertical│ │Scalers  │          │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘          │
├─────────────────────────────────────────────────────────────┤
│  Infrastructure Layer                                      │
│  ┌─────────┐ ┌─────────┐                                  │
│  │   CAS   │ │   NAP   │                                  │
│  │ (Nodes) │ │(Smart   │                                  │
│  │         │ │ Nodes)  │                                  │
│  └─────────┘ └─────────┘                                  │
├─────────────────────────────────────────────────────────────┤
│  Azure Infrastructure                                      │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │           Azure Kubernetes Service (AKS)               │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## 🔗 Quick Links

- [Azure AKS Documentation](https://docs.microsoft.com/en-us/azure/aks/)
- [Kubernetes Autoscaling](https://kubernetes.io/docs/concepts/cluster-administration/manage-deployment/#scaling-your-application)
- [KEDA Documentation](https://keda.sh/)
- [Cluster Autoscaler](https://github.com/kubernetes/autoscaler/tree/master/cluster-autoscaler)
- [Karpenter](https://karpenter.sh/docs/concepts/)
- [Azure Karpenter](https://github.com/Azure/karpenter-provider-azure)


