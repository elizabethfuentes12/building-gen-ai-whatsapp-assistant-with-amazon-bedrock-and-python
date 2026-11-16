####################################################################
## Text assistant: Amazon Bedrock Converse API with DynamoDB memory ##
####################################################################

import os
import time

import boto3
from boto3.dynamodb.conditions import Key

from bedrock_utils import converse, text_block
from db_utils import (update_items_out, save_item_ddb, query, update_item_session)
from utils import whats_reply

model_id = os.environ.get('ENV_MODEL_ID_V3')
MAX_TOKENS = int(os.environ.get('ENV_MAX_TOKENS', '1000'))
SESSION_SECONDS = int(os.environ.get('ENV_SESSION_SECONDS', '240'))

SYSTEM_PROMPT = """The following is a friendly conversation between a human and an AI.
The AI is talkative and provides lots of specific details from its context.
If the AI does not know the answer to a question, it truthfully says it does not know.
Always reply in the original user language.
"""

whatsapp_out_lambda = os.environ.get('WHATSAPP_OUT')
table_name_active_connections = os.environ.get('whatsapp_MetaData')
table_name_session = os.environ.get('session_table_history')

dynamodb_resource = boto3.resource('dynamodb')
table = dynamodb_resource.Table(table_name_active_connections)
table_session_active = dynamodb_resource.Table(os.environ['user_sesion_metadata'])


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


def agent_text(model_id, text, max_tokens, history):
    """Ask the model with the conversation history. Returns (reply, new_history)."""
    return converse(model_id, SYSTEM_PROMPT, history, [text_block(text)], max_tokens)


def lambda_handler(event, context):
    print(event)

    whats_message = event['whats_message']
    print('REQUEST RECEIVED:', event)
    print('REQUEST CONTEXT:', context)
    print("PROMPT: ", whats_message)

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
        response, history = agent_text(model_id, whats_message, MAX_TOKENS, history)
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
