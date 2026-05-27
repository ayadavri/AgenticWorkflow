import json
import boto3
import os

agentcore = boto3.client("bedrock-agentcore", region_name="us-east-1")

def invoke_agentcore(payload: dict) -> dict:
    resp = agentcore.invoke_agent_runtime(
        agentRuntimeArn=os.environ["DISPUTE_ANALYSIS_AGENTCORE_RUNTIME_ARN"],
        qualifier=os.environ.get("DISPUTE_ANALYSIS_AGENTCORE_QUALIFIER", "DEFAULT"),
        payload=json.dumps(payload).encode("utf-8"),
    )
    return json.loads(resp["response"].read())