#!/usr/bin/env python3

from google.cloud import container_v1
from kubernetes import client, config
from google.auth import credentials
import google.auth
import requests.exceptions
import json
import csv

# Configuration
PROJECT_ID = "your-project-id"  # Replace with your project ID
CLUSTER_NAME = "your-cluster-name"  # Replace with your GKE cluster name
REGION = "your-region"  # Replace with your region (e.g., "us-central1")

DEBUG=0

def init_k8s_client(*, use_private_endpoint):
    """Initialise K8s API client with public/private endpoint fallback"""
    # Try private
    try:
        private_config = get_cluster_credentials(use_private_endpoint=True)

        core_v1 = client.CoreV1Api(api_client=client.ApiClient(configuration=private_config))
        networking_v1 = client.NetworkingV1Api(api_client=client.ApiClient(configuration=private_config))

        namespaces = core_v1.list_namespace().items
        print("Connected successfully using private endpoint.")
        return networking_v1, core_v1
    except (requests.exceptions.ConnectTimeout, client.exceptions.ApiException) as e:
        print(f"Private endpoint failed: str{(e)}. Falling back to public endpoint")

        # Try public
        try:
            public_config = get_cluster_credentials(use_private_endpoint=False)

            core_v1 = client.CoreV1Api(api_client=client.ApiClient(configuration=public_config))
            networking_v1 = client.NetworkingV1Api(api_client=client.ApiClient(configuration=public_config))

            namespaces = core_v1.list_namespace().items
            print("Connected successfully using public endpoint.")
            return networking_v1, core_v1
        except (requests.exceptions.ConnectTimeout, client.exceptions.ApiException) as e:
            print(f"Public endpoint failed: {str(e)}. Unable to connect to cluster.")
            raise Exception("Failed to connect using both public and private endpoints")



def get_cluster_credentials(use_private_endpoint=False):
    """Authenticate and get Kubernetes cluster configuration."""
    credentials, project = google.auth.default()
    gke_client = container_v1.ClusterManagerClient(credentials=credentials)

    cluster_path = f"projects/{PROJECT_ID}/locations/{REGION}/clusters/{CLUSTER_NAME}"
    cluster = gke_client.get_cluster(name=cluster_path)

    if use_private_endpoint:
        endpoint = cluster.private_cluster_config.private_endpoint
        if not endpoint:
            raise ValueError("Private endpoint not available. Esnure the cluster has a private endpoint and you have connectivity to it")
    else:
        endpoint = cluster.endpoint

    k8s_config = client.Configuration()
    k8s_config.host = f"https://{endpoint}"
    k8s_config.api_key["authorization"] = f"Bearer {credentials.token}"
    k8s_config.verify_ssl = True
    k8s_config.ssl_ca_cert = cluster.master_auth.cluster_ca_certificate.encode()

    config.load_kube_config_from_dict(config_dict={
        "apiVersion": "v1",
        "clusters": [{"name": "gke-cluster", "cluster": {"server": k8s_config.host, "certificate-authority-data": cluster.master_auth.cluster_ca_certificate}}],
        "contexts": [{"name": "gke-context", "context": {"cluster": "gke-cluster", "user": "gke-user"}}],
        "current-context": "gke-context",
        "kind": "Config",
        "users": [{"name": "gke-user", "user": {"token": credentials.token}}]
    })



def list_workloads_and_routes(netApi, coreApi):
    """Loop through workloads and print project, workload name, and route on each line."""
    v1 = client.AppsV1Api()
    core_v1 = client.CoreV1Api()
    networking_v1 = client.NetworkingV1Api()

    # Get all namespaces
    namespaces = coreApi.list_namespace().items
    for ns in namespaces:
        namespace = ns.metadata.name

        # Get all deployments (workloads) in the namespace
        deployments = v1.list_namespaced_deployment(namespace).items
        if not deployments:
            continue

        for deployment in deployments:
            dep_name = deployment.metadata.name

            # Get selector for the deployment
            selector = deployment.spec.selector.match_labels
            selector_str = ",".join([f"{k}={v}" for k, v in selector.items()])

            # Get services in the namespace
            services = core_v1.list_namespaced_service(namespace).items
            service_names = [s.metadata.name for s in services]

            # Get Ingress resources in the namespace
            ingresses = netApi.list_namespaced_ingress(namespace).items
            for ingress in ingresses:
                for rule in ingress.spec.rules or []:
                    for path in rule.http.paths or []:
                        svc_name = path.backend.service.name
                        # Check if the service is tied to the deployment
                        for service in services:
                            svc_selector = service.spec.selector or {}
                            svc_selector_str = ",".join([f"{k}={v}" for k, v in svc_selector.items()])
                            if (svc_name == service.metadata.name and
                                (svc_selector == selector or svc_name.startswith(dep_name))):
                                # Format route as host + path
                                route = f"{rule.host}{path.path or '/'}"
                                # Print project, workload name, and route on the same line
                                print(f"{project_id:<20} {dep_name:<30} {route}")



def list_ingresses(netApi, coreApi):
    """Loop through Ingress resources and print project and route on each line."""

    ingress_endpoints={}
    headers = ["PROJECT_ID", "CLUSTER_NAME", "namespace", "ingress_name", "rule_count", "route", "service", "port", "ingress_class"]

    # Get all namespaces
    namespaces = coreApi.list_namespace().items
    for ns in namespaces:
        namespace = ns.metadata.name
        print(f"Looking at {namespace}") if DEBUG else None

        # Get all Ingress resources in the namespace
        ingresses = netApi.list_namespaced_ingress(namespace=namespace).items
        if not ingresses:
            continue

        for ingress in ingresses:
            annotations = ingress.metadata.annotations
            ingress_name = ingress.metadata.name
            ingress_class_key = "kubernetes.io/ingress.class"
            ingress_class = None #default if no class

            if annotations and ingress_class_key in annotations:
                ingress_class = annotations[ingress_class_key]
                print(f"Ingress: {ingress_name}, class: {ingress_class}")

            rule_count=0
            for rule in ingress.spec.rules or []:
                for path in rule.http.paths or []:
                    route   = f"{rule.host}{path.path or '/'}"
                    service = path.backend.service.name
                    port    = str(path.backend.service.port.number)
                    print(f"About to assign ingress_endpoints using {PROJECT_ID}, {CLUSTER_NAME}, {namespace}, {ingress_class}, {ingress_name}, {rule_count}, {route}, {service}, {port}")
                    # Use setdefault to create the multi-layer dict from the empty dict
                    ingress_endpoints.setdefault(PROJECT_ID, {}) \
                      .setdefault(CLUSTER_NAME, {}) \
                      .setdefault(namespace, {}) \
                      .setdefault(ingress_name, {}) \
                      [rule_count] = {
                         "route": route,
                         "service": service,
                         "port": port,
                         "ingress_class": ingress_class
                      }
                    rule_count += 1

    return ingress_endpoints, headers


def list_gateways(coreApi):
    """Loop through Gateway resources and extract relevant information."""

    gateway_endpoints = {}
    headers = ["PROJECT_ID", "CLUSTER_NAME", "namespace", "gateway_name", "gateway_class",
               "loadbalancer", "ip_address", "listener_count", "listener_name", "listener_protocol",
               "listener_port", "routes"]

    # Get namespaces
    namespaces = coreApi.list_namespace().items
    for ns in namespaces:
        namespace = ns.metadata.name
        print(f"Looking at {namespace}") if DEBUG else None

        try:
            gateways = customApi.list_namespaced_custom_object(
                group="gateway.networking.k8s.io",
                version="v1",
                namespace=namespace,
                plural="gateways"
            ).get("items", [])
        except Exception as e:
            print(f"Error fetching gateways in {namespace}: {e}")
            continue

        if not gateways:
            continue

        for gateway in gateways:
            gateway_name = gateway["metadata"]["name"]
            gateway_class = gateway["spec"].get("gatewayClassName", "None")  # Default to "None"
            loadbalancer = None
            ip_address = None

            # Get LoadBalancer and IP address
            status = gateway.get("status", {})
            addresses = status.get("addresses", [])
            if addresses:
                for address in addresses:
                    if address["type"] == "IPAddress":
                        ip_address = address["value"]
                    elif address["type"] == "Hostname" and "loadbalancer" in address["value"].lower():
                        loadbalancer = address["value"]
                    # If no specific LoadBalancer type, assume first IP is from LB if present
                    if not ip_address and address["type"] == "IPAddress":
                        ip_address = address["value"]
                        loadbalancer = "inferred"

            print(f"Gateway: {gateway_name}, class: {gateway_class}, IP: {ip_address or 'None'}, LB: {loadbalancer or 'None'}") if DEBUG else None

            listener_count = 0
            for listener in gateway["spec"].get("listeners", []):
                listener_name = listener.get("name")
                listener_protocol = listener.get("protocol")
                listener_port = str(listener.get("port"))

                # Routes: Placeholder for correlated route data
                # For simplicity, set as "N/A"; see notes below for full route correlation
                routes = "N/A"

                print(f"About to assign gateway_endpoints using {PROJECT_ID}, {CLUSTER_NAME}, {namespace}, {gateway_name}, {gateway_class}, {loadbalancer}, {ip_address}, {listener_count}, {listener_name}, {listener_protocol}, {listener_port}, {routes}") if DEBUG else None

                # Build the nested dictionary
                gateway_endpoints.setdefault(PROJECT_ID, {}) \
                    .setdefault(CLUSTER_NAME, {}) \
                    .setdefault(namespace, {}) \
                    .setdefault(gateway_name, {}) \
                    [listener_count] = {
                        "gateway_class": gateway_class,
                        "loadbalancer": loadbalancer or "None",
                        "ip_address": ip_address or "None",
                        "listener_name": listener_name,
                        "listener_protocol": listener_protocol,
                        "listener_port": listener_port,
                        "routes": routes
                    }
                listener_count += 1

    return gateway_endpoints, headers


def flatten_ingress_data(data):
    """ Take multi-level dicts and flatten so we can later write to csv"""
    print(f"Flattening data") if DEBUG else None
    rows = []

    for project_id, clusters in data.items():
        for cluster_name, namespaces in clusters.items():
            for namespace, ingresses in namespaces.items():
                for ingress_name, rules in ingresses.items():
                    for rule_count, details in rules.items():
                        rows.append({
                            "PROJECT_ID": project_id,
                            "CLUSTER_NAME": cluster_name,
                            "namespace": namespace,
                            "ingress_name": ingress_name,
                            "rule_count": rule_count,
                            "route": details["route"],
                            "service": details["service"],
                            "port": details["port"],
                            "ingress_class": details["ingress_class"],
                        })

    return rows



def flatten_gateway_data(data):
    """ Take multi-level dicts and flatten so we can later write to csv"""
    print(f"Flattening data") if DEBUG else None
    rows = []

    for project_id, clusters in data.items():
        for cluster_name, namespaces in clusters.items():
            for namespace, gateways in namespaces.items():
                for gateway_name, details in gateways.items():
                    rows.append({
                        "PROJECT_ID": project_id,
                        "CLUSTER_NAME": cluster_name,
                        "namespace": namespace,
                        "gateway_name": gateway_name,
                        "gateway_class": details["gateway_class"],
                        "loadbalancer": details["loadbalancer"],
                        "ip_address": details["ip_address"],
                        "listener_count": details["listener_count"],
                        "listener_name": details["listener_name"],
                        "listener_protocol": details["listener_protocol"],
                        "listener_port": details["listener_port"],
                        "routes": details["routes"]
                    })

    return rows



def write_csv(data, headers):
    """ Write data to CSV file """
    print(f"Writing CSV file") if DEBUG else None
    with open("endpoints.csv", "w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers)
        writer.writeheader()
        writer.writerows(data)




def main():
    try:
        networking_v1, core_v1             = init_k8s_client(use_private_endpoint=True)
        ingress_endpoints, ingress_headers = list_ingresses(netApi=networking_v1, coreApi=core_v1)
        gateway_endpoints, gateway_headers = list_gateways(coreApi=core_v1)
        flat_ingress_data                  = flatten_ingress_data(ingress_endpoints)
        flat_gateway_data                  = flatten_gateway_data(gateway_endpoints)

        write_csv(flat_ingress_data, ingress_headers)
        write_csv(flat_ingress_data, gateway_headers)

        #gateway_endpoints      = list_gateway_routes(netApi=networking_v1, coreApi=core_v1)
        #list_workloads_and_routes(netApi=networking_v1, coreApi=core_v1)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
