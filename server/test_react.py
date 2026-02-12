"""Test script for ReAct agent functionality.

This script tests the core ReAct functionality without requiring a running server.
"""

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Add server directory to path
server_dir = str(Path(__file__).resolve().parent)
sys.path.insert(0, server_dir)
sys.path.insert(0, str(Path(server_dir).parent))

from app.models.agent import Agent  # noqa: E402
from app.models.react import ReactTask  # noqa: E402
from app.orchestration.tool import get_tool_manager  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine, select  # noqa: E402


def test_tool_system():
    """Test tool system with OpenAI format."""
    print("\n" + "=" * 60)
    print("测试 1: Tool 系统")
    print("=" * 60)

    tool_manager = get_tool_manager()
    builtin_tools_dir = Path(__file__).parent / "app" / "orchestration" / "tool" / "builtin"
    tool_manager.refresh(builtin_tools_dir)

    tools = tool_manager.list_tools()
    print(f"\n✓ 已加载 {len(tools)} 个工具")

    if tools:
        print("\n工具列表:")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description}")

    # Test OpenAI format conversion
    openai_tools = tool_manager.to_openai_tools()
    print(f"\n✓ OpenAI 格式转换成功: {len(openai_tools)} 个工具")

    if openai_tools:
        print("\n示例工具 (OpenAI 格式):")
        print(json.dumps(openai_tools[0], indent=2, ensure_ascii=False))

    return True


def test_database_models():
    """Test database models."""
    print("\n" + "=" * 60)
    print("测试 2: 数据库模型")
    print("=" * 60)

    # Create in-memory database for testing
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        # Create test agent
        agent = Agent(
            name="test_agent",
            description="Test agent",
            model_name="test_model",
            max_iteration=10,
        )
        session.add(agent)
        session.commit()
        session.refresh(agent)

        print(f"\n✓ Agent 创建成功: ID={agent.id}, max_iteration={agent.max_iteration}")

        # Create test task
        task = ReactTask(
            task_id=str(uuid.uuid4()),
            agent_id=agent.id or 0,
            user="test_user",
            user_message="测试任务",
            objective="测试 ReAct 系统",
            status="pending",
            iteration=0,
            max_iteration=10,
        )
        session.add(task)
        session.commit()
        session.refresh(task)

        print(f"✓ ReactTask 创建成功: task_id={task.task_id}")

        # Query tasks
        stmt = select(ReactTask).where(ReactTask.agent_id == agent.id)
        tasks = session.exec(stmt).all()
        print(f"✓ 查询成功: 找到 {len(tasks)} 个任务")

    return True


def test_llm_response_structure():
    """Test LLM response structure with tool_calls."""
    print("\n" + "=" * 60)
    print("测试 3: LLM Response 结构")
    print("=" * 60)

    from app.llm.abstract_llm import ChatMessage

    # Test ChatMessage with tool_calls
    message = ChatMessage(
        role="assistant",
        content=None,
        tool_calls=[
            {
                "id": "call_123",
                "type": "function",
                "function": {"name": "add", "arguments": '{"a": 3, "b": 5}'},
            }
        ],
    )

    print("\n✓ ChatMessage 创建成功")
    print(f"  - role: {message.role}")
    print(f"  - content: {message.content}")
    print(f"  - tool_calls: {len(message.tool_calls or [])} 个")

    if message.tool_calls:
        print("\n工具调用详情:")
        for tc in message.tool_calls:
            print(f"  - {tc['function']['name']}: {tc['function']['arguments']}")

    return True


def test_schemas():
    """Test ReAct schemas."""
    print("\n" + "=" * 60)
    print("测试 4: ReAct Schemas")
    print("=" * 60)

    from app.schemas.react import (
        ReactChatRequest,
        ReactStreamEvent,
        ReactStreamEventType,
    )

    # Test request
    request = ReactChatRequest(
        agent_id=1, message="帮我计算 (3 + 5) * 2", user="test_user"
    )
    print("\n✓ ReactChatRequest 创建成功")
    print(f"  - agent_id: {request.agent_id}")
    print(f"  - message: {request.message}")

    # Test event
    event = ReactStreamEvent(
        type=ReactStreamEventType.RECURSION_START,
        task_id="test_task_123",
        trace_id="trace_456",
        iteration=1,
        delta=None,
        data={"info": "开始执行"},
        timestamp=datetime.now(timezone.utc),
    )
    print("\n✓ ReactStreamEvent 创建成功")
    print(f"  - type: {event.type.value}")
    print(f"  - task_id: {event.task_id}")

    # Test JSON serialization
    json_str = event.json()
    print(f"\n✓ JSON 序列化成功: {len(json_str)} 字节")

    return True


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("ReAct Agent 系统测试")
    print("=" * 60)

    tests = [
        ("Tool 系统", test_tool_system),
        ("数据库模型", test_database_models),
        ("LLM Response 结构", test_llm_response_structure),
        ("ReAct Schemas", test_schemas),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            success = test_func()
            results.append((test_name, success, None))
        except Exception as e:
            print(f"\n✗ {test_name} 测试失败: {e}")
            import traceback

            traceback.print_exc()
            results.append((test_name, False, str(e)))

    # Print summary
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    passed = sum(1 for _, success, _ in results if success)
    total = len(results)

    print(f"\n通过: {passed}/{total}")

    for test_name, success, error in results:
        status = "✓ 通过" if success else "✗ 失败"
        print(f"  {status}: {test_name}")
        if error:
            print(f"    错误: {error}")

    if passed == total:
        print("\n🎉 所有测试通过!")
        return 0
    else:
        print(f"\n⚠️  有 {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
