# AGENTS.md

Two independent CDK (Python) sample apps that connect WhatsApp (Meta Cloud API webhooks) to Amazon Bedrock:

| App | Status | Details |
|---|---|---|
| `private-assistant/` | Updated 2026-11: Claude Haiku 5.5 via the Converse API, python3.13, aws-cdk-lib 2.277.0, no LangChain | [private-assistant/AGENTS.md](private-assistant/AGENTS.md) |
| `private-assistant-v2/` | Unchanged: Amazon Bedrock Agents + `amazon.nova-pro-v1:0` (ACTIVE as of 2026-11), python3.11/3.12, aws-cdk-lib 2.172.0 | see `private-assistant-v2/README.md` |

Each app is deployed on its own (`cd <app> && cdk deploy`). Both create real AWS resources (Lambda, DynamoDB, API Gateway, S3, Secrets Manager).
