import json

from analytics.mcp_agent import run_mcp_analytics_agent


def main() -> None:
    question = input("Ask a commerce analytics question: ")
    response = run_mcp_analytics_agent(question)

    print("\nFinal Answer:")
    print(response["answer"])

    print("\nExecution Trace:")
    print(json.dumps(response["execution_trace"], indent=2, default=str))


if __name__ == "__main__":
    main()