#!/usr/bin/env python3

import sys
import os
from google.cloud import compute_v1
from google.api_core import exceptions

def list_instances_with_external_ips(project):
    """List Compute Engine instances with external IPs in the given project."""
    client = compute_v1.InstancesClient()
    instances = []
    try:
        # List all instances across all zones
        request = compute_v1.AggregatedListInstancesRequest(project=project)
        for zone, response in client.aggregated_list(request=request):
            if response.instances:
                for instance in response.instances:
                    if instance.network_interfaces:
                        for interface in instance.network_interfaces:
                            if interface.access_configs:
                                for config in interface.access_configs:
                                    if config.nat_i_p:
                                        instances.append({
                                            'name': instance.name,
                                            'zone': zone.split('/')[-1],
                                            'machine_type': instance.machine_type.split('/')[-1],
                                            'external_ip': config.nat_i_p
                                        })
        return instances
    except exceptions.GoogleAPIError as e:
        print(f"Error listing instances in {project}: {e}", file=sys.stderr)
        return []

def list_external_addresses(project):
    """List external IP addresses in the given project."""
    client = compute_v1.AddressesClient()
    addresses = []
    try:
        # List all addresses across all regions
        request = compute_v1.AggregatedListAddressesRequest(project=project)
        for region, response in client.aggregated_list(request=request):
            if response.addresses:
                for address in response.addresses:
                    if address.address_type == "EXTERNAL":
                        addresses.append({
                            'name': address.name,
                            'region': region.split('/')[-1] if region else 'global',
                            'address': address.address
                        })
        return addresses
    except exceptions.GoogleAPIError as e:
        print(f"Error listing addresses in {project}: {e}", file=sys.stderr)
        return []

def list_forwarding_rules(project):
    """List forwarding rules in the given project."""
    client = compute_v1.ForwardingRulesClient()
    rules = []
    try:
        # List all forwarding rules across all regions
        request = compute_v1.AggregatedListForwardingRulesRequest(project=project)
        for region, response in client.aggregated_list(request=request):
            if response.forwarding_rules:
                for rule in response.forwarding_rules:
                    rules.append({
                        'name': rule.name,
                        'region': region.split('/')[-1] if region else 'global',
                        'ip_address': rule.I_p_address,
                        'ip_protocol': rule.I_p_protocol,
                        'target': rule.target.split('/')[-1] if rule.target else ''
                    })
        return rules
    except exceptions.GoogleAPIError as e:
        print(f"Error listing forwarding rules in {project}: {e}", file=sys.stderr)
        return []

def main():
    # Check if an input file was provided
    if len(sys.argv) < 2:
        print(f"Error: No input file provided. Usage: {sys.argv[0]} <input_file>", file=sys.stderr)
        sys.exit(1)

    input_file = sys.argv[1]
    if not os.path.isfile(input_file):
        print(f"Error: File '{input_file}' does not exist.", file=sys.stderr)
        sys.exit(1)

    # Save the current CLOUDSDK_CORE_PROJECT (if set)
    default_project = os.environ.get('CLOUDSDK_CORE_PROJECT', '')

    # Read the input file
    with open(input_file, 'r') as f:
        projects = [line.strip() for line in f if line.strip()]

    # Process each project
    for project in projects:
        print(f"Processing project: {project}")

        # Set the project for API calls via environment variable
        os.environ['CLOUDSDK_CORE_PROJECT'] = project

        # Get resources
        instances = list_instances_with_external_ips(project)
        addresses = list_external_addresses(project)
        forwarding_rules_list = list_forwarding_rules(project)

        # Check if there’s any output to display
        if instances or addresses or forwarding_rules_list:
            print(f"Project: {project}")
            if instances:
                print("Instance IPs:")
                for inst in instances:
                    print(f"{inst['name']}  {inst['zone']}  {inst['machine_type']}  {inst['external_ip']}")
            if addresses:
                print("External Addresses:")
                for addr in addresses:
                    print(f"{addr['name']}  {addr['region']}  {addr['address']}")
            if forwarding_rules_list:
                print("Forwarding Rules:")
                for rule in forwarding_rules_list:
                    print(f"{rule['name']}  {rule['region']}  {rule['ip_address']}  {rule['ip_protocol']}  {rule['target']}")
            print("----------------------------------------")

    # Restore the original CLOUDSDK_CORE_PROJECT
    if default_project:
        os.environ['CLOUDSDK_CORE_PROJECT'] = default_project

    print("Script completed.")

if __name__ == "__main__":
    main()
