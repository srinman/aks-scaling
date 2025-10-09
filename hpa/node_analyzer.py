#!/usr/bin/env python3
"""
Node Resource Analyzer for Kubernetes
Provides detailed CPU and memory information for all nodes.
"""

import subprocess
import json
import sys
from typing import Dict, List, Optional

def run_kubectl(command: str) -> Optional[str]:
    """Execute kubectl command and return output."""
    try:
        result = subprocess.run(
            f"kubectl {command}",
            shell=True,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error running kubectl {command}: {e}", file=sys.stderr)
        return None

def parse_resource_unit(value: str) -> float:
    """Convert Kubernetes resource units to standard units."""
    if not value or value == "0":
        return 0.0
    
    # Handle CPU units (m = millicores)
    if value.endswith('m'):
        return float(value[:-1]) / 1000  # Convert millicores to cores
    
    # Handle memory units
    multipliers = {
        'Ki': 1024,
        'Mi': 1024**2,
        'Gi': 1024**3,
        'Ti': 1024**4,
        'K': 1000,
        'M': 1000**2,
        'G': 1000**3,
        'T': 1000**4
    }
    
    for suffix, multiplier in multipliers.items():
        if value.endswith(suffix):
            return float(value[:-len(suffix)]) * multiplier
    
    # If no suffix, assume base unit
    return float(value)

def format_cpu(cores: float) -> str:
    """Format CPU value for display."""
    if cores >= 1:
        return f"{cores:.2f}"
    else:
        return f"{int(cores * 1000)}m"

def format_memory(bytes_val: float) -> str:
    """Format memory value for display."""
    if bytes_val >= 1024**3:
        return f"{bytes_val / 1024**3:.2f}Gi"
    elif bytes_val >= 1024**2:
        return f"{bytes_val / 1024**2:.2f}Mi"
    elif bytes_val >= 1024:
        return f"{bytes_val / 1024:.2f}Ki"
    else:
        return f"{int(bytes_val)}B"

def get_node_capacity_info() -> Dict:
    """Get node capacity and allocatable resources."""
    output = run_kubectl("get nodes -o json")
    if not output:
        return {}
    
    nodes_data = json.loads(output)
    node_info = {}
    
    for node in nodes_data['items']:
        name = node['metadata']['name']
        capacity = node['status']['capacity']
        allocatable = node['status']['allocatable']
        
        node_info[name] = {
            'cpu_capacity': parse_resource_unit(capacity.get('cpu', '0')),
            'cpu_allocatable': parse_resource_unit(allocatable.get('cpu', '0')),
            'memory_capacity': parse_resource_unit(capacity.get('memory', '0')),
            'memory_allocatable': parse_resource_unit(allocatable.get('memory', '0'))
        }
    
    return node_info

def get_node_allocated_resources() -> Dict:
    """Get resources allocated (requested) by pods on each node."""
    allocated = {}
    
    # Get all pods with their node assignments and resource requests
    output = run_kubectl("get pods -A -o json")
    if not output:
        return allocated
    
    pods_data = json.loads(output)
    
    for pod in pods_data['items']:
        node_name = pod['spec'].get('nodeName')
        if not node_name:
            continue
        
        if node_name not in allocated:
            allocated[node_name] = {'cpu': 0, 'memory': 0}
        
        # Sum up resource requests from all containers
        for container in pod['spec'].get('containers', []):
            requests = container.get('resources', {}).get('requests', {})
            
            cpu_request = requests.get('cpu', '0')
            memory_request = requests.get('memory', '0')
            
            allocated[node_name]['cpu'] += parse_resource_unit(cpu_request)
            allocated[node_name]['memory'] += parse_resource_unit(memory_request)
    
    return allocated

def get_node_current_usage() -> Dict:
    """Get current resource usage from metrics server."""
    usage = {}
    
    # Get current node metrics
    output = run_kubectl("top nodes --no-headers")
    if not output:
        return usage
    
    for line in output.strip().split('\n'):
        if not line.strip():
            continue
        
        parts = line.split()
        if len(parts) >= 5:
            node_name = parts[0]
            cpu_usage = parts[1]  # e.g., "143m"
            memory_usage = parts[3]  # e.g., "2425Mi"
            
            usage[node_name] = {
                'cpu': parse_resource_unit(cpu_usage),
                'memory': parse_resource_unit(memory_usage)
            }
    
    return usage

def calculate_percentage(used: float, total: float) -> float:
    """Calculate percentage usage."""
    if total == 0:
        return 0.0
    return (used / total) * 100

def main():
    """Main function to display node resource information."""
    print("=" * 80)
    print("KUBERNETES NODE RESOURCE ANALYSIS")
    print("=" * 80)
    print()
    
    # Get all data
    capacity_info = get_node_capacity_info()
    allocated_resources = get_node_allocated_resources()
    current_usage = get_node_current_usage()
    
    if not capacity_info:
        print("Error: Could not retrieve node information")
        sys.exit(1)
    
    # Display information for each node
    for node_name in sorted(capacity_info.keys()):
        node_data = capacity_info[node_name]
        allocated = allocated_resources.get(node_name, {'cpu': 0, 'memory': 0})
        usage = current_usage.get(node_name, {'cpu': 0, 'memory': 0})
        
        print(f"NODE: {node_name}")
        print("-" * 60)
        
        # CPU Information
        cpu_capacity = node_data['cpu_capacity']
        cpu_allocatable = node_data['cpu_allocatable']
        cpu_allocated = allocated['cpu']
        cpu_used = usage['cpu']
        
        cpu_reserved = cpu_capacity - cpu_allocatable
        cpu_allocated_pct = calculate_percentage(cpu_allocated, cpu_allocatable)
        cpu_used_pct = calculate_percentage(cpu_used, cpu_allocatable)
        
        print(f"CPU:")
        print(f"  Capacity:    {format_cpu(cpu_capacity)} cores")
        print(f"  Reserved:    {format_cpu(cpu_reserved)} cores (for system)")
        print(f"  Allocatable: {format_cpu(cpu_allocatable)} cores")
        print(f"  Allocated:   {format_cpu(cpu_allocated)} cores ({cpu_allocated_pct:.1f}% of allocatable)")
        print(f"  Current Use: {format_cpu(cpu_used)} cores ({cpu_used_pct:.1f}% of allocatable)")
        
        # Memory Information
        mem_capacity = node_data['memory_capacity']
        mem_allocatable = node_data['memory_allocatable']
        mem_allocated = allocated['memory']
        mem_used = usage['memory']
        
        mem_reserved = mem_capacity - mem_allocatable
        mem_allocated_pct = calculate_percentage(mem_allocated, mem_allocatable)
        mem_used_pct = calculate_percentage(mem_used, mem_allocatable)
        
        print(f"Memory:")
        print(f"  Capacity:    {format_memory(mem_capacity)}")
        print(f"  Reserved:    {format_memory(mem_reserved)} (for system)")
        print(f"  Allocatable: {format_memory(mem_allocatable)}")
        print(f"  Allocated:   {format_memory(mem_allocated)} ({mem_allocated_pct:.1f}% of allocatable)")
        print(f"  Current Use: {format_memory(mem_used)} ({mem_used_pct:.1f}% of allocatable)")
        
        print()
        
        # Analysis
        print("Analysis:")
        if cpu_used > cpu_allocated:
            print(f"  ⚠️  CPU usage ({format_cpu(cpu_used)}) exceeds allocated ({format_cpu(cpu_allocated)})")
        if mem_used > mem_allocated:
            print(f"  ⚠️  Memory usage ({format_memory(mem_used)}) exceeds allocated ({format_memory(mem_allocated)})")
        if cpu_used_pct > 80:
            print(f"  🔥 High CPU usage: {cpu_used_pct:.1f}%")
        if mem_used_pct > 80:
            print(f"  🔥 High memory usage: {mem_used_pct:.1f}%")
        if cpu_allocated_pct > 80:
            print(f"  📊 High CPU allocation: {cpu_allocated_pct:.1f}%")
        if mem_allocated_pct > 80:
            print(f"  📊 High memory allocation: {mem_allocated_pct:.1f}%")
        
        print("=" * 80)
        print()

if __name__ == "__main__":
    main()