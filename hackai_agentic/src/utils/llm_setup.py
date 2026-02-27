
import langchain_core
from langchain_core.caches import BaseCache




from langchain_community.cache import InMemoryCache 

from langchain_huggingface import ChatHuggingFace, HuggingFacePipeline
from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline

# Set BaseCache globally
langchain_core.caches.BaseCache = InMemoryCache

# Create a singleton ChatHuggingFace instance
def get_chat_model(model_path="google/medgemma-1.5-4b-it") -> ChatHuggingFace:
    tokenizer = AutoTokenizer.from_pretrained(model_path, token="")
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        dtype="bfloat16",      # uses bfloat16/float16 automatically
        device_map="auto",       # spreads across available GPUs/CPU
        token=""
    )
    pipe = pipeline(
        "text-generation",
        model=model,
        tokenizer=tokenizer,
        max_new_tokens=4096,
        return_full_text=False,  # only return generated tokens, not the prompt
        token=""
    )
    llm = HuggingFacePipeline(pipeline=pipe)
    return ChatHuggingFace(llm=llm)


chat_model = get_chat_model()

