"""
Manual smoke-test for MCP tool calls (prints, not a pytest module).
Run from the source/ directory: ../.venv/bin/python3 tests/manual_smoke_mcp_tools.py
"""

import asyncio
import sys
sys.path.insert(0, ".")

from lib.tools import handle_tool_call


async def test_tools():
    print("=" * 60)
    print("Duck Library MCP Tool Smoke Tests")
    print("=" * 60)

    tests = [
        ("search_academic", {"query": "machine learning", "limit": 3}),
        ("browse_library_databases", {"query": "psychology", "limit": 3}),
        ("check_library_access", {"name": "JSTOR"}),
    ]

    for name, args in tests:
        print(f"\n[{name}] args={args}")
        try:
            result = await handle_tool_call(name, args)
            print(result[0].text[:400])
        except Exception as e:
            print(f"  ERROR: {e}")

    print("\n" + "=" * 60)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(test_tools())
