import asyncio
import sys
import os


from src.modules.agent import Agent
from langgraph.checkpoint.memory import MemorySaver


async def chat():
    checkpointer = MemorySaver()
    print("checkpointer", checkpointer) # Added print statement to verify checkpointer initialization.
    agent = Agent(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "1"}}
    
    print("Agent ready. Type 'exit' to quit.")
    
    while True:
        user_input = input("You: ")
        if user_input.lower() in ("exit", "quit"):
            break
        async for event in agent.graph.astream(
            {"messages": [("user", user_input)]}, config
        ):
            for value in event.values():
                if value.get("messages"):
                    content = value["messages"][-1].content
                    # Strip <tool_call> tags
                    # if "<tool_call>" in content and "<tool_call>" in content:
                    #     content = content.split("<tool_call>", 1)[1].strip()
                    print("Agent:", content)


def main():
    asyncio.run(chat())


if __name__ == "__main__":
    main()