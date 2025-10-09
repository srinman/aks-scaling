# AKS Vertical Pod Autoscaler (VPA)

## Introduction  

This folder contains notes and examples for experimenting with the Kubernetes Vertical Pod Autoscaler (VPA) on Azure Kubernetes Service (AKS).

VPA automatically recommends (and optionally applies) changes to pod resource requests (CPU and memory) based on observed usage. It is useful when you want pods to be tuned for the actual workload rather than sizing them manually.

Important: On AKS, VPA integrates with the cluster but has specific prerequisites and recommended practices. For a complete, up-to-date walkthrough and AKS-specific considerations, follow Microsoft's guide:

https://learn.microsoft.com/en-us/azure/aks/use-vertical-pod-autoscaler

Quick try-it checklist
- Ensure your AKS cluster is running a supported Kubernetes version and you have cluster admin access.
- Deploy a sample workload (a deployment with a container that increases memory or CPU over time).
- Create a VPA object (recommendation-only first) and monitor the recommendations.



Commands to watch recommendations

```bash
# See VPA recommendation status
kubectl get vpa -n default
kubectl describe vpa myapp-vpa -n default

# Check the pod's resource requests before and after applying recommendations
kubectl get deploy myapp -o yaml
```

## Caveats & notes
- VPA and HPA should generally not actively control the same pod simultaneously (VPA may be used to set requests while HPA controls replicas).
- For production, consider using VPA in recommendation mode, apply changes during maintenance windows, or use safe update modes.
- On managed AKS, check the Microsoft guide for any managed addon options, RBAC requirements, and cluster feature flags.

## Next steps
- Follow the Microsoft Learn guide above for AKS-specific instructions and examples.
- Add sample manifests and a small load generator to this folder if you'd like a ready-to-run demo.
