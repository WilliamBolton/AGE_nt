import re
import json
import asyncio
from typing import Annotated, Dict, List, Any
from typing_extensions import TypedDict

# Core LangGraph/LangChain Imports
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import tools_condition, ToolNode
from langgraph.graph.message import add_messages
from langchain_core.runnables import RunnableLambda, RunnableSerializable
from langchain_core.messages import AnyMessage, SystemMessage, ToolMessage, AIMessage, BaseMessage, HumanMessage

# Your Specific Imports
from src.utils.llm_setup import chat_model 
from src.modules.prompts import SYSTEM_PROMPT 

class AgentState(TypedDict):
    # add_messages is the reducer that handles the message list
    messages: Annotated[list[AnyMessage], add_messages]
    json_file_path: str
    extracted_params: Dict

class Agent:
    def __init__(self, checkpointer=None):
        # Use your imported constants directly
        self.system = SYSTEM_PROMPT
        self.model = chat_model
        
        # Build the graph
        workflow = StateGraph(AgentState)
        
        workflow.add_node("assistant", self.acall_model)
        workflow.add_node("msg_converter", self.transform_messages)

        workflow.set_entry_point("assistant")
        workflow.add_edge("assistant", "msg_converter")
        workflow.add_edge("msg_converter", END)
        
        self.graph = workflow.compile(checkpointer=checkpointer)

    def _clean_content(self, content: str) -> str:
        """Removes <think> blocks so history stays clean."""
        if not isinstance(content, str): return ""
        content = re.sub(r'(?i)<think>.*?</think>', '', content, flags=re.DOTALL)
        content = re.sub(r'(?i)^.*?</think>', '', content, flags=re.DOTALL)
        content = re.sub(r'(?i)<think>.*$', '', content, flags=re.DOTALL)
        return content.strip()

    def parse_tool_call(self, content: str):
        """Extracts JSON tool calls from strings."""
        try:
            clean_text = self._clean_content(content)
            match = re.search(r'\{.*\}', clean_text, re.DOTALL)
            if not match: return None
            
            tool_data = json.loads(match.group())
            tool_name = tool_data.pop("tool", None)
            if tool_name:
                return {
                    "name": tool_name,
                    "args": tool_data,
                    "id": f"call_{int(asyncio.get_event_loop().time())}"
                }
        except:
            return None
        return None

    async def acall_model(self, state: AgentState):
        """Invokes model and ensures role alternation."""
        # Prepend system prompt to current message list
        input_messages = [SystemMessage(content=self.system)] + state["messages"]
        
        try:
            loop = asyncio.get_event_loop()
            # Calling the model
            response = await loop.run_in_executor(None, self.model.invoke, input_messages)
            
            clean_text = self._clean_content(response.content)
            tool_call = self.parse_tool_call(response.content)
            
            if tool_call:
                # Return an AI message with the tool call
                return {"messages": [AIMessage(content=clean_text, tool_calls=[tool_call])]}
            
            # Return standard AI message
            return {"messages": [AIMessage(content=clean_text)]}
            
        except Exception as e:
            # IMPORTANT: Return AIMessage on error to keep roles alternating (User -> AI)
            return {"messages": [AIMessage(content=f"Error processing request: {str(e)}")]}

    def transform_messages(self, state: AgentState):
        """Prevents history loops and role errors."""
        if not state["messages"]:
            return {"messages": []}

        # Get the last message to process
        last_msg = state["messages"][-1]

        # 1. Convert ToolMessage to HumanMessage if it exists (fixes role issues)
        if isinstance(last_msg, ToolMessage):
            # We return a list with a single new message. 
            # add_messages will append this to the list.
            return {"messages": [HumanMessage(
                content=f"Tool '{last_msg.name}' response: {last_msg.content}",
                name=last_msg.name
            )]}
        
        # 2. Clean thinking from the final AI response to keep history readable
        if isinstance(last_msg, AIMessage) and isinstance(last_msg.content, str):
            last_msg.content = self._clean_content(last_msg.content)
            
        # Return only the single processed message to update the state
        return {"messages": [last_msg]}