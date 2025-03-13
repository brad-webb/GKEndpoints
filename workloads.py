#!/usr/bin/env python3

from google.cloud import container_v1
from kubernetes import client, config
from google.auth import credentials
import google.auth

# Configuration
PROJECT_ID = "your-project-id"  # Replace with your project ID
CLUSTER_NAME = "your-cluster-name"  # Replace with your GKE cluster name
REGION = "your-region"  # Replace with your region (e.g., "us-central1")

def get_cluster_credentials():
    """Authenticate and get Kubernetes cluster configuration."""
    credentials, project = google.auth.default()
    gke_client = container_v1.ClusterManagerClient(credentials=credentials)

    cluster_path = f"projects/{PROJECT_ID}/locations/{REGION}/clusters/{CLUSTER_NAME}"
    cluster = gke_client.get_cluster(name=cluster_path)

    k8s_config = client.Configuration()
    k8s_config.host = f"https://{cluster.endpoint}"
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

def list_workloads_and_routes(project_id):
    """Loop through workloads and print project, workload name, and route on each line."""
    v1 = client.AppsV1Api()
    core_v1 = client.CoreV1Api()
    networking_v1 = client.NetworkingV1Api()

    # Get all namespaces
    namespaces = core_v1.list_namespace().items
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
            ingresses = networking_v1.list_namespaced_ingress(namespace).items
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



def list_ingress_routes(project_id):
    """Loop through Ingress resources and print project and route on each line."""
    networking_v1 = client.NetworkingV1Api()
    core_v1 = client.CoreV1Api()

    # Get all namespaces
    namespaces = core_v1.list_namespace().items
    for ns in namespaces:
        namespace = ns.metadata.name

        # Get all Ingress resources in the namespace
        ingresses = networking_v1.list_namespaced_ingress(namespace).items
        if not ingresses:
            continue

        for ingress in ingresses:
            for rule in ingress.spec.rules or []:
                for path in rule.http.paths or []:
                    # Format route as host + path
                    route = f"{rule.host}{path.path or '/'}"
                    # Print project and route on the same line
                    print(f"{project_id:<20} {route}")



def main():
    try:
        get_cluster_credentials()
        #list_workloads_and_routes(PROJECT_ID)
        list_ingress_routes(PROJECT_ID)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
