"""Helpers to talk to Amazon Bedrock through the Converse API and to keep the
conversation history in DynamoDB.

Converse API reference:
https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html

History is stored in DynamoDB using the Converse ``Message`` shape
(``{"role": ..., "content": [ContentBlock, ...]}``). The only transformation
applied for storage is that image bytes are base64-encoded strings (DynamoDB
items are JSON-like and the Lambda passes history around as JSON).
"""

import base64
import os

import boto3

# Claude 5.x models run adaptive thinking by default. For a chat assistant we
# turn it off to keep latency and cost low. Only models that support
# ``{"type": "disabled"}`` accept this field, see "Thinking configuration by
# model" in https://docs.aws.amazon.com/bedrock/latest/userguide/claude-messages-adaptive-thinking.html
# Set ENV_DISABLE_THINKING=false to leave the model default (adaptive).
DISABLE_THINKING = os.environ.get("ENV_DISABLE_THINKING", "true").lower() == "true"

# Image formats accepted by the Converse ImageBlock:
# https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ImageBlock.html
IMAGE_FORMATS = {"png", "jpeg", "gif", "webp"}

_bedrock_runtime = None


def bedrock_runtime():
    global _bedrock_runtime
    if _bedrock_runtime is None:
        _bedrock_runtime = boto3.client("bedrock-runtime")
    return _bedrock_runtime


def image_format_from_mime(mime_type):
    """'image/jpeg' -> 'jpeg'; 'image/jpg' -> 'jpeg'."""
    fmt = (mime_type or "").split("/")[-1].lower()
    if fmt == "jpg":
        fmt = "jpeg"
    if fmt not in IMAGE_FORMATS:
        raise ValueError(f"Unsupported image format for Converse: {mime_type}")
    return fmt


def text_block(text):
    return {"text": text}


def image_block(image_bytes, image_format):
    return {"image": {"format": image_format, "source": {"bytes": image_bytes}}}


def _to_api(content):
    """Storage shape -> Converse request shape (base64 string -> bytes)."""
    blocks = []
    for block in content:
        if "image" in block:
            img = block["image"]
            data = img["source"]["bytes"]
            if isinstance(data, str):
                data = base64.b64decode(data)
            blocks.append({"image": {"format": img["format"], "source": {"bytes": data}}})
        elif "text" in block:
            blocks.append({"text": block["text"]})
        # anything else (reasoningContent, etc.) is not replayed
    return blocks


def _to_storage(content):
    """Converse shape -> storage shape (bytes -> base64 string), text and image only."""
    blocks = []
    for block in content:
        if "image" in block:
            img = block["image"]
            data = img["source"]["bytes"]
            if isinstance(data, (bytes, bytearray)):
                data = base64.b64encode(data).decode("utf8")
            blocks.append({"image": {"format": img["format"], "source": {"bytes": data}}})
        elif "text" in block:
            blocks.append({"text": block["text"]})
    return blocks


def converse(model_id, system_prompt, history, user_content, max_tokens):
    """Send ``history + user_content`` to the model and return (reply_text, new_history).

    ``history`` and the returned ``new_history`` use the storage shape described
    in the module docstring, so they can be written to DynamoDB as they are.
    """
    messages = [{"role": m["role"], "content": _to_api(m["content"])} for m in history]
    messages.append({"role": "user", "content": _to_api(user_content)})

    kwargs = dict(
        modelId=model_id,
        system=[{"text": system_prompt}],
        messages=messages,
        inferenceConfig={"maxTokens": max_tokens},
    )
    if DISABLE_THINKING:
        kwargs["additionalModelRequestFields"] = {"thinking": {"type": "disabled"}}

    response = bedrock_runtime().converse(**kwargs)
    output = response["output"]["message"]["content"]
    reply_text = "".join(block["text"] for block in output if "text" in block)

    new_history = list(history)
    new_history.append({"role": "user", "content": _to_storage(user_content)})
    new_history.append({"role": "assistant", "content": [text_block(reply_text)]})
    return reply_text, fit_history_in_dynamodb_item(new_history)


# DynamoDB items are limited to 400 KB. A base64 image adds ~1.33x its size to
# the history item, so older images are replaced by a text placeholder when the
# serialized history gets close to the limit. The current turn's image is kept
# whenever possible so follow-up questions about it still work.
# https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/ServiceQuotas.html#limits-items
HISTORY_MAX_BYTES = int(os.environ.get("ENV_HISTORY_MAX_BYTES", str(350 * 1024)))
IMAGE_PLACEHOLDER = "[image sent earlier in this conversation]"


def fit_history_in_dynamodb_item(history, max_bytes=HISTORY_MAX_BYTES):
    import json

    history = [dict(m, content=list(m["content"])) for m in history]
    while len(json.dumps(history)) > max_bytes:
        replaced = False
        for message in history:
            for i, block in enumerate(message["content"]):
                if "image" in block:
                    message["content"][i] = text_block(IMAGE_PLACEHOLDER)
                    replaced = True
                    break
            if replaced:
                break
        if not replaced:
            break  # only text left; nothing more to shrink
    return history
