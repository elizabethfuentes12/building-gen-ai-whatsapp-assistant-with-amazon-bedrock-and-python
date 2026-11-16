#####################################################################
## Image assistant: Amazon Bedrock Converse API with DynamoDB memory ##
#####################################################################

import os
import sys
import time

import boto3
from boto3.dynamodb.conditions import Key

from bedrock_utils import converse, image_block, image_format_from_mime, text_block
from db_utils import (update_items_out, save_item_ddb, query, update_item_session)
from file_utils import (get_media_url, get_whats_media, put_file)
from utils import whats_reply

BucketName = os.environ.get('BucketName')
ImageKeyName = os.environ.get('ImageKeyName')
model_id = os.environ.get('ENV_MODEL_ID')
MAX_TOKENS = int(os.environ.get('ENV_MAX_TOKENS', '500'))
SESSION_SECONDS = int(os.environ.get('ENV_SESSION_SECONDS', '240'))

SYSTEM_PROMPT = "You are an AI Assistant, always reply in the original user text language."

whatsapp_out_lambda = os.environ.get('WHATSAPP_OUT')
table_name_active_connections = os.environ.get('whatsapp_MetaData')
table_name_session = os.environ.get('session_table_history')

dynamodb_resource = boto3.resource('dynamodb')
table = dynamodb_resource.Table(table_name_active_connections)
table_session_active = dynamodb_resource.Table(os.environ['user_sesion_metadata'])

base_path = "/tmp/"


def save_history(table_name, item):
    print("put item")
    response = dynamodb_resource.Table(table_name).put_item(Item=item)
    print(response)
    return True


def query_history(key, table_name, keyvalue):
    print("Query History")
    response = dynamodb_resource.Table(table_name).query(
        KeyConditionExpression=Key(key).eq(keyvalue)
    )
    print(response)
    return response['Items'][0]


def process_image(messageType, whats_token, ImageKeyName, whats_message):
    """Download the WhatsApp image, keep a copy in S3 and return (local_file, caption, mime_type)."""
    print(f"messageType:{messageType}")
    fileType = whats_message['mime_type']
    print(f"fileType:{fileType}")
    fileExtension = fileType.split('/')[-1]
    fileId = whats_message['id']
    print(f"fileId:{fileId}")
    fileName = f'{fileId}.{fileExtension}'
    print(f"fileName:{fileName}")
    caption = whats_message.get('caption', '')
    print(f"caption:{caption}")

    fileUrl = get_media_url(fileId, whats_token)
    if not fileUrl:
        return None
    fileContents = get_whats_media(fileUrl, whats_token)
    fileSize = sys.getsizeof(fileContents) - 33  # Removing BYTES overhead
    print(f"fileSize:{fileSize}")
    print("Image Ready!")

    LOCAL_FILE = f"image_{fileName}"
    print(f"LOCAL_FILE:{LOCAL_FILE}")

    with open(f"{base_path}{LOCAL_FILE}", "wb") as binary_file:
        binary_file.write(fileContents)

    put_file(base_path, LOCAL_FILE, BucketName, ImageKeyName + "/")
    return LOCAL_FILE, caption, fileType


def agent_image(model_id, max_tokens, image_path, mime_type, text, history):
    """Ask the model about an image (plus caption) with the conversation history."""
    with open(image_path, "rb") as image_file:
        image_bytes = image_file.read()
    content = [image_block(image_bytes, image_format_from_mime(mime_type))]
    if text:
        content.append(text_block(text))
    # If there is no caption, the Converse API makes the model describe the image.
    return converse(model_id, SYSTEM_PROMPT, history, content, max_tokens)


def lambda_handler(event, context):
    print(event)

    whats_message = event['whats_message']
    print('REQUEST RECEIVED:', event)
    print('REQUEST CONTEXT:', context)
    print("PROMPT: ", whats_message)

    messageType = event['type']
    print("type: ", messageType)

    whats_token = event['whats_token']
    messages_id = event['messages_id']
    phone = event['phone']
    phone_id = event['phone_id']
    phone_number = phone.replace("+", "")

    try:
        session_data = query("phone_number", table_session_active, phone_number)
        now = int(time.time())
        diferencia = now - session_data["session_time"]
        if diferencia > SESSION_SECONDS:
            print(f"Session older than {SESSION_SECONDS}s, starting a new one")
            update_item_session(table_session_active, phone_number, now)
            id = str(phone_number) + "_" + str(now)
            history = []
        else:
            print("Continuing session")
            id = str(phone_number) + "_" + str(session_data["session_time"])
            history = query_history("SessionId", table_name_session, id)["History"]
            print(history)

    except Exception:
        print("Nuevo")
        now = int(time.time())
        new_row = {"phone_number": phone_number, "session_time": now}
        save_item_ddb(table_session_active, new_row)
        history = []
        id = str(phone_number) + "_" + str(now)

    try:
        print(messageType)
        print(whats_message["image"])
        LOCAL_FILE, prompt, mime_type = process_image(messageType, whats_token, ImageKeyName, whats_message["image"])
        print(LOCAL_FILE)
        response, history = agent_image(model_id, MAX_TOKENS, f"{base_path}{LOCAL_FILE}", mime_type, prompt, history)
        print(response)

        whats_reply(whatsapp_out_lambda, phone, whats_token, phone_id, f"{response}", messages_id)
        end = int(time.time())
        update_items_out(table, messages_id, response, end)
        item = {"SessionId": id, "History": history}
        save_history(table_name_session, item)

        return {"body": response}

    except Exception as error:
        print('FAILED!', error)
        return {"body": "Cuek! I dont know"}
