from config import *
from agents.agent import bio_pipeline
import asyncio


async def main():
    print("--- Starting LangGraph BioPipeline")

    user_query = "metformin for aging intervention"

    result = await bio_pipeline.ainvoke({"query": user_query})

    # graph = bio_pipeline.get_graph()
    # graph.draw_png("results/bio_pipeline.png")

    print("Final raw findings:\n", result.get("raw_findings", ""))
    print("\nFinal analysis:\n", result.get("analysis", ""))


if __name__ == '__main__':
    asyncio.run(main())
