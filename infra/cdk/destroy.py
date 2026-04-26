#!/usr/bin/env python3
"""AgentCore CDK destroy script.

Removes AgentCore Runtime, Endpoint, Gateway, Memory resources
using boto3 bedrock-agentcore client calls.

Usage: AWS_PROFILE=mzadmin python infra/cdk/destroy.py --env demo
"""

from __future__ import annotations

import argparse
import json
import sys

REGION = "ap-northeast-2"
PROJECT = "doc-agent"


def _get_boto3_client(service: str, region: str = REGION):
    """Create a boto3 client."""
    import boto3
    return boto3.client(service, region_name=region)


def _safe_delete(fn, resource_type: str, resource_name: str, **kwargs) -> bool:
    """Attempt deletion, return True if successful or already gone."""
    try:
        fn(**kwargs)
        print(f"[CDK] Deleted {resource_type}: {resource_name}")
        return True
    except Exception as e:
        err_name = type(e).__name__
        if "ResourceNotFoundException" in err_name or "NotFound" in str(e):
            print(f"[CDK] {resource_type} not found (already deleted): {resource_name}")
            return True
        print(f"[CDK] Failed to delete {resource_type} {resource_name}: {e}")
        return False


def destroy_gateway(client, env: str) -> None:
    """Delete AgentCore Gateway and its targets."""
    gateway_name = f"{PROJECT}-gateway-{env}"
    print(f"[CDK] Destroying Gateway: {gateway_name}")

    try:
        gw = client.get_gateway(gatewayName=gateway_name)
        gateway_id = gw["gatewayId"]

        # List and delete all targets first
        try:
            targets_resp = client.list_gateway_targets(gatewayId=gateway_id)
            for target in targets_resp.get("targets", []):
                target_name = target.get("name", target.get("targetName", ""))
                _safe_delete(
                    client.delete_gateway_target,
                    "Gateway target", target_name,
                    gatewayId=gateway_id,
                    targetName=target_name,
                )
        except Exception as e:
            print(f"[CDK] Could not list gateway targets: {e}")

        # Delete gateway
        _safe_delete(
            client.delete_gateway,
            "Gateway", gateway_name,
            gatewayId=gateway_id,
        )
    except Exception as e:
        if "ResourceNotFoundException" in type(e).__name__:
            print(f"[CDK] Gateway not found: {gateway_name}")
        else:
            print(f"[CDK] Error destroying gateway: {e}")


def destroy_endpoint(client, env: str) -> None:
    """Delete AgentCore Endpoint."""
    endpoint_name = f"{PROJECT}-endpoint-{env}"
    print(f"[CDK] Destroying Endpoint: {endpoint_name}")

    try:
        ep = client.get_runtime_endpoint(runtimeEndpointName=endpoint_name)
        endpoint_id = ep["runtimeEndpointId"]
        _safe_delete(
            client.delete_runtime_endpoint,
            "Endpoint", endpoint_name,
            runtimeEndpointId=endpoint_id,
        )
    except Exception as e:
        if "ResourceNotFoundException" in type(e).__name__:
            print(f"[CDK] Endpoint not found: {endpoint_name}")
        else:
            print(f"[CDK] Error destroying endpoint: {e}")


def destroy_runtime(client, env: str) -> None:
    """Delete AgentCore Runtime."""
    runtime_name = f"{PROJECT}-runtime-{env}"
    print(f"[CDK] Destroying Runtime: {runtime_name}")

    try:
        rt = client.get_runtime(runtimeName=runtime_name)
        runtime_id = rt["runtimeId"]
        _safe_delete(
            client.delete_runtime,
            "Runtime", runtime_name,
            runtimeId=runtime_id,
        )
    except Exception as e:
        if "ResourceNotFoundException" in type(e).__name__:
            print(f"[CDK] Runtime not found: {runtime_name}")
        else:
            print(f"[CDK] Error destroying runtime: {e}")


def destroy_memory(client, env: str) -> None:
    """Delete AgentCore Memory instance."""
    memory_name = f"{PROJECT}-memory-{env}"
    print(f"[CDK] Destroying Memory: {memory_name}")

    try:
        mem = client.get_memory(memoryName=memory_name)
        memory_id = mem["memoryId"]
        _safe_delete(
            client.delete_memory,
            "Memory", memory_name,
            memoryId=memory_id,
        )
    except Exception as e:
        if "ResourceNotFoundException" in type(e).__name__:
            print(f"[CDK] Memory not found: {memory_name}")
        else:
            print(f"[CDK] Error destroying memory: {e}")


def destroy(env: str = "demo", region: str = REGION) -> None:
    """Destroy all AgentCore resources in reverse dependency order."""
    print(f"[CDK] Destroying AgentCore resources in {region} (env={env})")
    print("=" * 60)

    client = _get_boto3_client("bedrock-agentcore", region)

    # Delete in reverse dependency order:
    # 1. Gateway targets + Gateway (depends on Lambda ARNs)
    print("\n[CDK] Step 1: Destroy Gateway + targets")
    destroy_gateway(client, env)

    # 2. Endpoint (depends on Runtime)
    print("\n[CDK] Step 2: Destroy Endpoint")
    destroy_endpoint(client, env)

    # 3. Runtime
    print("\n[CDK] Step 3: Destroy Runtime")
    destroy_runtime(client, env)

    # 4. Memory (independent)
    print("\n[CDK] Step 4: Destroy Memory")
    destroy_memory(client, env)

    print("\n" + "=" * 60)
    print("[CDK] Destroy complete!")


def main() -> None:
    parser = argparse.ArgumentParser(description="Destroy AgentCore resources")
    parser.add_argument("--env", default="demo", help="Environment name")
    parser.add_argument("--region", default=REGION, help="AWS region")
    args = parser.parse_args()
    destroy(args.env, args.region)


if __name__ == "__main__":
    main()
