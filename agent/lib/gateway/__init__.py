"""AgentCore Gateway — common MCP tool invocation layer.

Provides ``AgentCoreGatewayClient`` used by Cost, Architecture,
Formatter, and Parent agents to call Gateway-registered MCP tools.
"""

from agent.lib.gateway.agentcore_gateway import AgentCoreGatewayClient

__all__ = ["AgentCoreGatewayClient"]
