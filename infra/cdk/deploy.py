#!/usr/bin/env python3
"""AgentCore CDK deploy script.

Creates/updates AgentCore Runtime, Endpoint, Gateway, Memory resources
using boto3 bedrock-agentcore-control client calls.

Usage: AWS_PROFILE=mzadmin python infra/cdk/deploy.py --env demo
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

REGION = "ap-northeast-2"
PROJECT = "doc-agent"
# AgentCore names must match [a-zA-Z][a-zA-Z0-9_]{0,47}
AC_PREFIX = "doc_agent"

# MCP tool schema definitions for Gateway target registration
TOOL_SCHEMAS: dict[str, dict] = {
    "validate_template_constraints": {
        "name": "validate_template_constraints",
        "description": "Validate Document_State against APN PoC template constraints",
        "inputSchema": {"type": "object", "properties": {"sections": {"type": "object"}, "staffing_plan": {"type": "object"}}, "required": ["sections"]},
    },
    "generate_architecture_diagram": {
        "name": "generate_architecture_diagram",
        "description": "Generate .drawio architecture diagram and preview artifacts",
        "inputSchema": {"type": "object", "properties": {"doc_id": {"type": "string"}, "services": {"type": "array"}}, "required": ["doc_id"]},
    },
    "estimate_cost": {
        "name": "estimate_cost",
        "description": "Estimate AWS service costs via Calculator MCP wrapper",
        "inputSchema": {"type": "object", "properties": {"services": {"type": "array"}}, "required": ["services"]},
    },
    "calculate_staffing_cost": {
        "name": "calculate_staffing_cost",
        "description": "Deterministic staffing cost calculation from staffing_plan",
        "inputSchema": {"type": "object", "properties": {"staffing_plan": {"type": "object"}}, "required": ["staffing_plan"]},
    },
    "export_docx": {
        "name": "export_docx",
        "description": "Generate DOCX from Document_State and store in S3",
        "inputSchema": {"type": "object", "properties": {"doc_id": {"type": "string"}, "sections": {"type": "object"}}, "required": ["doc_id", "sections"]},
    },
    "build_milestone_summary": {
        "name": "build_milestone_summary",
        "description": "Synchronize milestones from staffing_plan and scope_of_work",
        "inputSchema": {"type": "object", "properties": {"staffing_plan": {"type": "object"}}, "required": ["staffing_plan"]},
    },
}

TOOL_LAMBDA_MAP: dict[str, str] = {
    "validate_template_constraints": f"{PROJECT}-validate-template",
    "generate_architecture_diagram": f"{PROJECT}-generate-diagram",
    "estimate_cost": f"{PROJECT}-estimate-cost",
    "calculate_staffing_cost": f"{PROJECT}-calc-staffing",
    "export_docx": f"{PROJECT}-export-docx",
    "build_milestone_summary": f"{PROJECT}-build-milestones",
}


def _get_boto3_client(service: str, region: str = REGION):
    """Create a boto3 client with proper credential_process support."""
    import boto3
    import botocore.session

    profile = os.environ.get("AWS_PROFILE")
    if profile:
        session = botocore.session.Session(profile=profile)
        boto_session = boto3.Session(botocore_session=session)
        return boto_session.client(service, region_name=region, verify=False)
    return boto3.client(service, region_name=region, verify=False)


def _get_account_id(region: str = REGION) -> str:
    sts = _get_boto3_client("sts", region)
    return sts.get_caller_identity()["Account"]


def _upload_code_to_s3(s3_client, zip_path: str, bucket: str, key: str) -> None:
    """Upload agent code ZIP to S3 for Runtime deployment."""
    print(f"[CDK] Uploading code to s3://{bucket}/{key}")
    s3_client.upload_file(zip_path, bucket, key)


def _package_agent_code(root_dir: str) -> str:
    agent_dir = Path(root_dir) / "agent"
    if not agent_dir.exists():
        raise FileNotFoundError(f"Agent directory not found: {agent_dir}")

    tmp_dir = tempfile.mkdtemp(prefix="agentcore-deploy-")
    zip_path = os.path.join(tmp_dir, "agent-runtime.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(agent_dir):
            dirs[:] = [d for d in dirs if d not in (".venv", "__pycache__", ".pytest_cache", "node_modules")]
            for f in files:
                if f.endswith((".pyc", ".pyo")):
                    continue
                full_path = os.path.join(root, f)
                arcname = os.path.relpath(full_path, root_dir)
                zf.write(full_path, arcname)

    print(f"[CDK] Packaged agent code: {zip_path} ({os.path.getsize(zip_path)} bytes)")
    return zip_path



def _find_runtime_by_name(client, name: str) -> str | None:
    """Find an existing runtime by name. Returns agentRuntimeId or None."""
    try:
        resp = client.list_agent_runtimes()
        for rt in resp.get("agentRuntimes", resp.get("agentRuntimeSummaries", [])):
            if rt.get("agentRuntimeName") == name:
                return rt["agentRuntimeId"]
    except Exception:
        pass
    return None


def _find_gateway_by_name(client, name: str) -> str | None:
    """Find an existing gateway by name. Returns gatewayId or None."""
    try:
        resp = client.list_gateways()
        for gw in resp.get("items", resp.get("gateways", resp.get("gatewaySummaries", []))):
            if gw.get("name") == name:
                return gw["gatewayId"]
    except Exception:
        pass
    return None


def _find_gateway_target_id_by_name(client, gateway_id: str, target_name: str) -> str | None:
    """Find an existing Gateway target by name. Returns targetId or None."""
    try:
        resp = client.list_gateway_targets(gatewayIdentifier=gateway_id)
        targets = resp.get("items", resp.get("targets", resp.get("gatewayTargets", [])))
        for target in targets:
            if target.get("name") == target_name or target.get("targetName") == target_name:
                return (
                    target.get("targetId")
                    or target.get("gatewayTargetId")
                    or target.get("id")
                )
    except Exception as exc:
        print(f"[CDK]     Could not list gateway targets: {exc}")
    return None


def _ensure_lambda_invoke_permission(lambda_client, lambda_fn_name: str, role_arn: str, statement_id: str) -> None:
    """Ensure the Gateway execution role can invoke the target Lambda."""
    try:
        lambda_client.add_permission(
            FunctionName=lambda_fn_name,
            StatementId=statement_id,
            Action="lambda:InvokeFunction",
            Principal=role_arn,
        )
        print(f"[CDK]     Lambda invoke permission added: {statement_id}")
    except Exception as exc:
        if "ResourceConflictException" in type(exc).__name__ or "already exists" in str(exc).lower():
            print(f"[CDK]     Lambda invoke permission exists: {statement_id}")
        else:
            raise


def _find_memory_by_name(client, name: str) -> str | None:
    """Find an existing memory by name. Returns memoryId or None."""
    try:
        resp = client.list_memories()
        for mem in resp.get("memories", []):
            mem_id = mem.get("id", "")
            mem_name = mem.get("name", "")
            # ID contains the name as prefix (e.g. "doc_agent_memory_demo-EAmE03Aa8g")
            if mem_name == name or mem_id.startswith(name):
                return mem_id
    except Exception:
        pass
    return None


def create_or_update_runtime(client, s3_client, env: str, zip_path: str, account_id: str, region: str, artifacts_bucket: str) -> str:
    """Create or update AgentCore Runtime."""
    runtime_name = f"{AC_PREFIX}_runtime_{env}"
    s3_key = f"agentcore/{runtime_name}/agent-runtime.zip"
    role_arn = f"arn:aws:iam::{account_id}:role/{PROJECT}-lambda-exec"

    print(f"[CDK] Creating/updating AgentCore Runtime: {runtime_name}")

    # Upload code to S3
    _upload_code_to_s3(s3_client, zip_path, artifacts_bucket, s3_key)

    existing_id = _find_runtime_by_name(client, runtime_name)

    if existing_id:
        print(f"[CDK] Runtime exists ({existing_id}), updating...")
        client.update_agent_runtime(
            agentRuntimeId=existing_id,
            roleArn=role_arn,
            networkConfiguration={"networkMode": "PUBLIC"},
            agentRuntimeArtifact={
                "codeConfiguration": {
                    "code": {"s3": {"bucket": artifacts_bucket, "prefix": s3_key}},
                    "runtime": "PYTHON_3_12",
                    "entryPoint": ["agent/app/parent/runtime.py"],
                }
            },
        )
        return existing_id

    print(f"[CDK] Creating new runtime...")
    resp = client.create_agent_runtime(
        agentRuntimeName=runtime_name,
        description=f"Doc Agent Parent Orchestrator ({env})",
        roleArn=role_arn,
        agentRuntimeArtifact={
            "codeConfiguration": {
                "code": {"s3": {"bucket": artifacts_bucket, "prefix": s3_key}},
                "runtime": "PYTHON_3_12",
                "entryPoint": ["agent/app/parent/runtime.py"],
            }
        },
        networkConfiguration={"networkMode": "PUBLIC"},
    )
    runtime_id = resp["agentRuntimeId"]
    print(f"[CDK] Runtime ID: {runtime_id}")
    return runtime_id


def create_or_update_endpoint(client, env: str, runtime_id: str) -> str:
    """Create or update AgentCore Endpoint."""
    endpoint_name = f"{AC_PREFIX}_endpoint_{env}"
    print(f"[CDK] Creating/updating AgentCore Endpoint: {endpoint_name}")

    # Wait for runtime to be READY
    print(f"[CDK] Waiting for runtime {runtime_id} to be READY...")
    for i in range(60):
        try:
            rt = client.get_agent_runtime(agentRuntimeId=runtime_id)
            status = rt.get("status", rt.get("agentRuntimeStatus", ""))
            print(f"[CDK]   Runtime status: {status} ({i*5}s)")
            if status.upper() in ("READY", "ACTIVE"):
                break
            if "FAIL" in status.upper():
                raise RuntimeError(f"Runtime failed: {status}")
        except Exception as e:
            if "FAIL" in str(e).upper():
                raise
            print(f"[CDK]   Checking... ({e})")
        time.sleep(5)
    else:
        print("[CDK] WARNING: Runtime may not be READY yet, attempting endpoint creation anyway")

    # Check existing endpoints
    try:
        resp = client.list_agent_runtime_endpoints(agentRuntimeId=runtime_id)
        for ep in resp.get("runtimeEndpoints", []):
            if ep.get("name") == endpoint_name:
                ep_id = ep.get("id", ep.get("agentRuntimeEndpointId", ""))
                print(f"[CDK] Endpoint exists ({ep_id})")
                return ep_id
    except Exception:
        pass

    print(f"[CDK] Creating new endpoint...")
    resp = client.create_agent_runtime_endpoint(
        agentRuntimeId=runtime_id,
        name=endpoint_name,
        description=f"Doc Agent endpoint ({env})",
    )
    endpoint_id = resp.get("id", resp.get("agentRuntimeEndpointId", resp.get("name", "")))
    print(f"[CDK] Endpoint ID: {endpoint_id}")
    return endpoint_id


def create_or_update_gateway(client, env: str, account_id: str, region: str) -> str:
    """Create or update AgentCore Gateway and register Lambda targets."""
    gateway_name = f"doc-agent-gateway-{env}"
    role_arn = f"arn:aws:iam::{account_id}:role/{PROJECT}-lambda-exec"
    lambda_client = _get_boto3_client("lambda", region)
    print(f"[CDK] Creating/updating AgentCore Gateway: {gateway_name}")

    gateway_id = _find_gateway_by_name(client, gateway_name)

    if not gateway_id:
        print(f"[CDK] Creating new gateway...")
        resp = client.create_gateway(
            name=gateway_name,
            description=f"Doc Agent MCP Gateway ({env})",
            protocolType="MCP",
            authorizerType="NONE",
            roleArn=role_arn,
        )
        gateway_id = resp.get("gatewayId", resp.get("id", ""))

    print(f"[CDK] Gateway ID: {gateway_id}")

    # Register Lambda targets
    for tool_name, lambda_fn_name in TOOL_LAMBDA_MAP.items():
        lambda_arn = f"arn:aws:lambda:{region}:{account_id}:function:{lambda_fn_name}"
        target_name = tool_name.replace("_", "-") + "-target"
        schema = TOOL_SCHEMAS.get(tool_name, {})
        description = schema.get("description", tool_name)
        target_configuration = {
            "mcp": {
                "lambda": {
                    "lambdaArn": lambda_arn,
                    "toolSchema": {"inlinePayload": [schema]},
                }
            }
        }
        credential_provider_configurations = [
            {"credentialProviderType": "GATEWAY_IAM_ROLE"}
        ]

        print(f"[CDK]   Registering target: {tool_name} → {lambda_fn_name}")
        statement_id = f"AllowAgentCoreGateway{tool_name.replace('_', '')}"[:100]
        try:
            _ensure_lambda_invoke_permission(
                lambda_client,
                lambda_fn_name,
                role_arn,
                statement_id,
            )
        except Exception as pe:
            print(f"[CDK]     Lambda permission setup failed: {pe}")
            continue

        target_id = _find_gateway_target_id_by_name(client, gateway_id, target_name)
        if target_id:
            print(f"[CDK]     Target exists ({target_id}), updating...")
            try:
                client.update_gateway_target(
                    gatewayIdentifier=gateway_id,
                    targetId=target_id,
                    name=target_name,
                    description=description,
                    targetConfiguration=target_configuration,
                    credentialProviderConfigurations=credential_provider_configurations,
                )
                print(f"[CDK]     Target updated: {target_name}")
            except Exception as ue:
                print(f"[CDK]     Update failed: {ue}")
            continue

        try:
            resp = client.create_gateway_target(
                gatewayIdentifier=gateway_id,
                name=target_name,
                description=description,
                targetConfiguration=target_configuration,
                credentialProviderConfigurations=credential_provider_configurations,
            )
            created_id = resp.get("targetId", resp.get("gatewayTargetId", resp.get("id", "")))
            suffix = f" ({created_id})" if created_id else ""
            print(f"[CDK]     Target created: {target_name}{suffix}")
        except Exception as e:
            print(f"[CDK]     Create failed: {e}")

    return gateway_id


def create_or_update_memory(client, env: str) -> str:
    """Create or update AgentCore Memory."""
    memory_name = f"{AC_PREFIX}_memory_{env}"
    print(f"[CDK] Creating/updating AgentCore Memory: {memory_name}")

    memory_id = _find_memory_by_name(client, memory_name)

    if memory_id:
        print(f"[CDK] Memory exists ({memory_id})")
        return memory_id

    print(f"[CDK] Creating new memory...")
    resp = client.create_memory(
        name=memory_name,
        description=f"Doc Agent Memory ({env})",
        eventExpiryDuration=365,
        memoryStrategies=[
            {
                "semanticMemoryStrategy": {
                    "name": "customer_context",
                    "description": "Long-term customer characteristics",
                    "namespaces": ["/customers/"],
                }
            }
        ],
    )
    memory_id = resp.get("memoryId", resp.get("id", resp.get("name", "")))
    print(f"[CDK] Memory ID: {memory_id}")
    return memory_id


def _get_artifacts_bucket(region: str) -> str:
    """Get the artifacts S3 bucket from Terraform output or convention."""
    try:
        import subprocess
        result = subprocess.run(
            ["terraform", "-chdir=infra/terraform", "output", "-raw", "s3_bucket"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    # Fallback: list buckets matching pattern
    s3 = _get_boto3_client("s3", region)
    try:
        resp = s3.list_buckets()
        for b in resp.get("Buckets", []):
            if b["Name"].startswith(f"{PROJECT}-artifacts-"):
                return b["Name"]
    except Exception:
        pass
    raise RuntimeError("Cannot find artifacts S3 bucket. Run terraform apply first.")


def deploy(env: str = "demo", region: str = REGION) -> dict:
    """Deploy all AgentCore resources."""
    print(f"[CDK] Deploying AgentCore resources to {region} (env={env})")
    print("=" * 60)

    control_client = _get_boto3_client("bedrock-agentcore-control", region)
    s3_client = _get_boto3_client("s3", region)
    account_id = _get_account_id(region)
    artifacts_bucket = _get_artifacts_bucket(region)

    script_dir = Path(__file__).resolve().parent
    root_dir = str(script_dir.parent.parent)

    # 1. Package agent code
    print("\n[CDK] Step 1: Package agent code")
    zip_path = _package_agent_code(root_dir)

    # 2. Create/update Runtime
    print("\n[CDK] Step 2: AgentCore Runtime")
    runtime_id = create_or_update_runtime(control_client, s3_client, env, zip_path, account_id, region, artifacts_bucket)

    # 3. Create/update Endpoint
    print("\n[CDK] Step 3: AgentCore Endpoint")
    endpoint_id = create_or_update_endpoint(control_client, env, runtime_id)

    # 4. Create/update Gateway + targets
    print("\n[CDK] Step 4: AgentCore Gateway + Lambda targets")
    gateway_id = create_or_update_gateway(control_client, env, account_id, region)

    # 5. Create/update Memory
    print("\n[CDK] Step 5: AgentCore Memory")
    memory_id = create_or_update_memory(control_client, env)

    # Cleanup
    if os.path.exists(zip_path):
        shutil.rmtree(os.path.dirname(zip_path), ignore_errors=True)

    resources = {
        "runtime_id": runtime_id,
        "endpoint_id": endpoint_id,
        "gateway_id": gateway_id,
        "memory_id": memory_id,
        "artifacts_bucket": artifacts_bucket,
        "env": env,
        "region": region,
    }

    print("\n" + "=" * 60)
    print("[CDK] Deploy complete!")
    print(json.dumps(resources, indent=2))
    return resources


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy AgentCore resources")
    parser.add_argument("--env", default="demo", help="Environment name")
    parser.add_argument("--region", default=REGION, help="AWS region")
    args = parser.parse_args()
    deploy(args.env, args.region)


if __name__ == "__main__":
    main()
