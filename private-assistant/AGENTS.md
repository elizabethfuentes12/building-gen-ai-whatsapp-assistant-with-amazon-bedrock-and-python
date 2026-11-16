# AGENTS.md — private-assistant

## What this is
WhatsApp assistant on AWS: API Gateway webhook -> `whatsapp_in` Lambda -> DynamoDB (`whatsapp-MetaData`, stream) -> `process_stream` routes by message type: text -> `agent_text_v3`, image -> `agent_image_v3`, audio -> `audio_job_transcriptor` (Amazon Transcribe) -> `transcriber_done`. Model calls go through the Amazon Bedrock Converse API (Claude Haiku 5.5 by default); conversation memory lives in DynamoDB (`sessionTable` + `user_metadata`, 240 s session window). Replies go back through `whatsapp_out`.

## Structure
- `app.py` -> `private_assistant/private_assistant_stack.py` (model id `model_id_v3`, secrets, env wiring, IAM).
- `lambdas/project_lambdas.py` – 7 functions, runtime `python3.13`. Code in `lambdas/code/<name>/lambda_function.py`.
- `layers/project_layers.py` – `bs4_requests.zip` (requests 2.34 + bs4 4.15), `boto3.zip` (boto3 1.44.3), `common/` (`utils.py`, `db_utils.py`, `file_utils.py`, `bedrock_utils.py`). Each zip ships its `requirements.txt`.
- `layers/common/python/bedrock_utils.py` – `converse()` helper: builds Converse `messages`, disables Claude adaptive thinking (`additionalModelRequestFields={"thinking": {"type": "disabled"}}`), converts image bytes <-> base64 for DynamoDB storage, trims old images so the history item stays under 400 KB.
- `apis/`, `databases/`, `s3_cloudfront/` – API Gateway, DynamoDB tables, S3 bucket for Transcribe output.

## Commands
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cdk synth
cdk deploy        # real resources; then fill the Secrets Manager values (WhatsApp token, verify token, phone id)
cdk destroy
```
Rebuild a layer (same method for all, per https://docs.aws.amazon.com/lambda/latest/dg/python-layers.html):
```bash
pip install -r requirements.txt --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.13 -t python/
zip -r <layer>.zip python requirements.txt
```

## Dependencies / config
- `aws-cdk-lib==2.277.0`, `constructs>=10,<11`, CDK CLI 2.x.
- Bedrock model access for `global.anthropic.claude-haiku-5-5` in the deployment account (cross-region inference profile; IAM `bedrock:InvokeModel` on `*`).
- Env vars on the agent functions: `ENV_MODEL_ID_V3` / `ENV_MODEL_ID` (model), `ENV_MAX_TOKENS` (1000 text / 500 image), `ENV_SESSION_SECONDS` (240), `ENV_DISABLE_THINKING` (`true`), `ENV_HISTORY_MAX_BYTES` (358400).

## Conventions / gotchas
- Functions are x86_64 (layers are built with `--platform manylinux2014_x86_64`); do not set `ARM_64` without rebuilding the layers for arm64.
- Claude 5.x rejects `temperature`/`top_p`/`top_k` and runs adaptive thinking unless disabled; Sonnet 5.5 needs `{"type": "between_tools"}` instead of `disabled` (see the adaptive-thinking doc linked in `bedrock_utils.py`). Nova models do not accept the `thinking` field: set `ENV_DISABLE_THINKING=false` if you switch to one.
- History shape in DynamoDB = Converse `Message` objects with base64 image bytes. Old items written by the 2024 code (Anthropic Messages shape) are not converted; sessions expire after 240 s so this is not an issue in practice.
- Never hardcode a new model id without checking its model card / lifecycle (`aws bedrock get-foundation-model`).

## Recent changes
- 2026-11: replaced EOL `anthropic.claude-3-5-sonnet-20240620-v1:0` and `anthropic.claude-instant-v1` with `global.anthropic.claude-haiku-5-5` via Converse; removed `langchain_agent_text`/`langchain_agent_audio`, `langchain.zip`, `aiofile-amazon-transcribe.zip`, `boto3.1.28.62.zip` and the stale duplicate `lambdas/layers/`; `transcriber_done` now points at `agent_text_v3`; runtime 3.11 -> 3.13; layers rebuilt for 3.13; IAM narrowed from `bedrock:*` to `bedrock:InvokeModel`; `aws-cdk-lib` 2.94.0 -> 2.277.0. Verified: `cdk synth` OK; both agent handlers executed live against Bedrock (text multi-turn memory, image + caption, image recalled in a later turn, session expiry) with an in-memory DynamoDB stand-in validated by boto3 `TypeSerializer`. WhatsApp webhook path not exercised end to end.
