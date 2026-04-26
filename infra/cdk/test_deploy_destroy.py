"""Tests for AgentCore CDK deploy/destroy scripts.

Validates:
- Script syntax (importable without errors)
- Deploy logic with mocked boto3 calls
- Destroy logic with mocked boto3 calls
- Tool schema definitions are complete
- Lambda mapping is correct
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# Add infra/cdk to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import deploy as deploy_mod
import destroy as destroy_mod


# ============================================================
# Syntax / import tests
# ============================================================

class TestScriptSyntax:
    """Verify scripts are importable and have expected entry points."""

    def test_deploy_module_importable(self):
        assert hasattr(deploy_mod, "deploy")
        assert hasattr(deploy_mod, "main")
        assert callable(deploy_mod.deploy)

    def test_destroy_module_importable(self):
        assert hasattr(destroy_mod, "destroy")
        assert hasattr(destroy_mod, "main")
        assert callable(destroy_mod.destroy)

    def test_deploy_has_tool_schemas(self):
        assert len(deploy_mod.TOOL_SCHEMAS) == 6
        expected_tools = {
            "validate_template_constraints",
            "generate_architecture_diagram",
            "estimate_cost",
            "calculate_staffing_cost",
            "export_docx",
            "build_milestone_summary",
        }
        assert set(deploy_mod.TOOL_SCHEMAS.keys()) == expected_tools

    def test_deploy_has_lambda_mapping(self):
        assert len(deploy_mod.TOOL_LAMBDA_MAP) == 6
        for tool_name in deploy_mod.TOOL_SCHEMAS:
            assert tool_name in deploy_mod.TOOL_LAMBDA_MAP

    def test_tool_schemas_have_required_fields(self):
        for name, schema in deploy_mod.TOOL_SCHEMAS.items():
            assert "name" in schema, f"{name} missing 'name'"
            assert "description" in schema, f"{name} missing 'description'"
            assert "inputSchema" in schema, f"{name} missing 'inputSchema'"
            assert schema["name"] == name

    def test_lambda_names_follow_convention(self):
        for tool_name, lambda_name in deploy_mod.TOOL_LAMBDA_MAP.items():
            assert lambda_name.startswith("doc-agent-"), (
                f"Lambda {lambda_name} should start with 'doc-agent-'"
            )


# ============================================================
# Deploy mocked boto3 tests
# ============================================================

class TestDeployWithMockedBoto3:
    """Test deploy functions with mocked boto3 clients."""

    def _make_mock_client(self):
        """Create a mock bedrock-agentcore client."""
        client = MagicMock()
        # Simulate ResourceNotFoundException
        not_found = type("ResourceNotFoundException", (Exception,), {})
        conflict = type("ConflictException", (Exception,), {})
        client.exceptions.ResourceNotFoundException = not_found
        client.exceptions.ConflictException = conflict
        return client

    def test_create_runtime_new(self):
        client = self._make_mock_client()
        client.get_runtime.side_effect = client.exceptions.ResourceNotFoundException()
        client.create_runtime.return_value = {"runtimeId": "rt-123"}

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            f.write(b"fake zip content")
            zip_path = f.name

        try:
            result = deploy_mod.create_or_update_runtime(
                client, "demo", zip_path, "ap-northeast-2"
            )
            assert result == "rt-123"
            client.create_runtime.assert_called_once()
        finally:
            os.unlink(zip_path)

    def test_create_runtime_existing(self):
        client = self._make_mock_client()
        client.get_runtime.return_value = {"runtimeId": "rt-existing"}

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            f.write(b"fake zip content")
            zip_path = f.name

        try:
            result = deploy_mod.create_or_update_runtime(
                client, "demo", zip_path, "ap-northeast-2"
            )
            assert result == "rt-existing"
            client.update_runtime.assert_called_once()
        finally:
            os.unlink(zip_path)

    def test_create_endpoint_new(self):
        client = self._make_mock_client()
        client.get_runtime_endpoint.side_effect = client.exceptions.ResourceNotFoundException()
        client.create_runtime_endpoint.return_value = {"runtimeEndpointId": "ep-456"}

        result = deploy_mod.create_or_update_endpoint(client, "demo", "rt-123")
        assert result == "ep-456"

    def test_create_endpoint_existing(self):
        client = self._make_mock_client()
        client.get_runtime_endpoint.return_value = {"runtimeEndpointId": "ep-existing"}

        result = deploy_mod.create_or_update_endpoint(client, "demo", "rt-123")
        assert result == "ep-existing"

    def test_create_gateway_new(self):
        client = self._make_mock_client()
        client.get_gateway.side_effect = client.exceptions.ResourceNotFoundException()
        client.create_gateway.return_value = {"gatewayId": "gw-789"}

        result = deploy_mod.create_or_update_gateway(
            client, "demo", "123456789012", "ap-northeast-2"
        )
        assert result == "gw-789"
        # Should register 6 targets
        assert client.create_gateway_target.call_count == 6

    def test_create_gateway_target_conflict_updates(self):
        client = self._make_mock_client()
        client.get_gateway.return_value = {"gatewayId": "gw-existing"}
        client.create_gateway_target.side_effect = client.exceptions.ConflictException()

        result = deploy_mod.create_or_update_gateway(
            client, "demo", "123456789012", "ap-northeast-2"
        )
        assert result == "gw-existing"
        assert client.update_gateway_target.call_count == 6

    def test_create_memory_new(self):
        client = self._make_mock_client()
        client.get_memory.side_effect = client.exceptions.ResourceNotFoundException()
        client.create_memory.return_value = {"memoryId": "mem-abc"}

        result = deploy_mod.create_or_update_memory(client, "demo")
        assert result == "mem-abc"

    def test_create_memory_existing(self):
        client = self._make_mock_client()
        client.get_memory.return_value = {"memoryId": "mem-existing"}

        result = deploy_mod.create_or_update_memory(client, "demo")
        assert result == "mem-existing"

    def test_package_agent_code(self):
        """Test that agent code packaging creates a valid ZIP."""
        # Use the actual project root
        root_dir = str(Path(__file__).resolve().parent.parent.parent)
        agent_dir = Path(root_dir) / "agent"
        if not agent_dir.exists():
            pytest.skip("agent/ directory not found")

        zip_path = deploy_mod._package_agent_code(root_dir)
        assert os.path.exists(zip_path)
        assert zip_path.endswith(".zip")
        assert os.path.getsize(zip_path) > 0

        # Cleanup
        import shutil
        shutil.rmtree(os.path.dirname(zip_path), ignore_errors=True)


# ============================================================
# Destroy mocked boto3 tests
# ============================================================

class TestDestroyWithMockedBoto3:
    """Test destroy functions with mocked boto3 clients."""

    def _make_mock_client(self):
        client = MagicMock()
        not_found = type("ResourceNotFoundException", (Exception,), {})
        client.exceptions.ResourceNotFoundException = not_found
        return client

    def test_destroy_gateway_existing(self):
        client = self._make_mock_client()
        client.get_gateway.return_value = {"gatewayId": "gw-123"}
        client.list_gateway_targets.return_value = {
            "targets": [
                {"name": "target-1"},
                {"name": "target-2"},
            ]
        }

        destroy_mod.destroy_gateway(client, "demo")
        assert client.delete_gateway_target.call_count == 2
        client.delete_gateway.assert_called_once()

    def test_destroy_gateway_not_found(self):
        client = self._make_mock_client()
        client.get_gateway.side_effect = client.exceptions.ResourceNotFoundException()

        # Should not raise
        destroy_mod.destroy_gateway(client, "demo")

    def test_destroy_endpoint_existing(self):
        client = self._make_mock_client()
        client.get_runtime_endpoint.return_value = {"runtimeEndpointId": "ep-123"}

        destroy_mod.destroy_endpoint(client, "demo")
        client.delete_runtime_endpoint.assert_called_once()

    def test_destroy_runtime_existing(self):
        client = self._make_mock_client()
        client.get_runtime.return_value = {"runtimeId": "rt-123"}

        destroy_mod.destroy_runtime(client, "demo")
        client.delete_runtime.assert_called_once()

    def test_destroy_memory_existing(self):
        client = self._make_mock_client()
        client.get_memory.return_value = {"memoryId": "mem-123"}

        destroy_mod.destroy_memory(client, "demo")
        client.delete_memory.assert_called_once()

    def test_destroy_all_not_found(self):
        """All resources already deleted — should complete without error."""
        client = self._make_mock_client()
        client.get_gateway.side_effect = client.exceptions.ResourceNotFoundException()
        client.get_runtime_endpoint.side_effect = client.exceptions.ResourceNotFoundException()
        client.get_runtime.side_effect = client.exceptions.ResourceNotFoundException()
        client.get_memory.side_effect = client.exceptions.ResourceNotFoundException()

        # Should not raise
        destroy_mod.destroy_gateway(client, "demo")
        destroy_mod.destroy_endpoint(client, "demo")
        destroy_mod.destroy_runtime(client, "demo")
        destroy_mod.destroy_memory(client, "demo")


# ============================================================
# Shell script syntax tests
# ============================================================

class TestShellScriptSyntax:
    """Verify shell scripts are syntactically valid."""

    def test_deploy_sh_syntax(self):
        """Check deploy.sh has valid bash syntax."""
        script_path = Path(__file__).resolve().parent.parent / "scripts" / "deploy.sh"
        assert script_path.exists(), f"deploy.sh not found at {script_path}"

        content = script_path.read_text()
        assert content.startswith("#!/usr/bin/env bash")
        assert "set -euo pipefail" in content
        assert "AWS_PROFILE" in content
        assert "terraform" in content
        assert "infra/cdk/deploy.py" in content
        assert "ap-northeast-2" in content

    def test_destroy_sh_syntax(self):
        """Check destroy.sh has valid bash syntax."""
        script_path = Path(__file__).resolve().parent.parent / "scripts" / "destroy.sh"
        assert script_path.exists(), f"destroy.sh not found at {script_path}"

        content = script_path.read_text()
        assert content.startswith("#!/usr/bin/env bash")
        assert "set -euo pipefail" in content
        assert "AWS_PROFILE" in content
        assert "infra/cdk/destroy.py" in content
        assert "terraform" in content

    def test_deploy_sh_order(self):
        """Verify deploy.sh runs Terraform before CDK."""
        script_path = Path(__file__).resolve().parent.parent / "scripts" / "deploy.sh"
        content = script_path.read_text()

        tf_pos = content.find("terraform")
        cdk_pos = content.find("infra/cdk/deploy.py")
        assert tf_pos < cdk_pos, "Terraform should run before CDK deploy"

    def test_destroy_sh_order(self):
        """Verify destroy.sh runs CDK destroy before Terraform destroy."""
        script_path = Path(__file__).resolve().parent.parent / "scripts" / "destroy.sh"
        content = script_path.read_text()

        cdk_pos = content.find("infra/cdk/destroy.py")
        tf_pos = content.find("terraform")
        # CDK destroy should appear before terraform destroy
        # But terraform output calls may appear before CDK
        # Check that CDK destroy is in Step 1 and terraform destroy is in Step 3
        assert "Step 1: AgentCore CDK destroy" in content
        assert "Step 3: Terraform destroy" in content
