from constructs import Construct

from aws_cdk import (
    aws_lambda
)

# All layers are built for the same runtime as the functions (python3.13).
# Rebuild the zips with the documented method if the runtime changes:
# https://docs.aws.amazon.com/lambda/latest/dg/python-layers.html
#   pip install -r requirements.txt --platform manylinux2014_x86_64 --only-binary=:all: -t python/
#   zip -r <layer>.zip python requirements.txt
LAYER_RUNTIMES = [aws_lambda.Runtime.PYTHON_3_13]


class Layers(Construct):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # requests + beautifulsoup4 (WhatsApp media download)
        self.bs4_requests = aws_lambda.LayerVersion(
            self, "Bs4Requests", code=aws_lambda.Code.from_asset("./layers/bs4_requests.zip"),
            compatible_runtimes=LAYER_RUNTIMES,
            description='requests 2.34 + beautifulsoup4 4.15 (python3.13)')

        # Shared helpers: utils.py, db_utils.py, file_utils.py, bedrock_utils.py
        self.common = aws_lambda.LayerVersion(
            self, "common-layer", code=aws_lambda.Code.from_asset("./layers/common/"),
            compatible_runtimes=LAYER_RUNTIMES,
            description='librerias adicionales', layer_version_name="librerias-adicionales"
        )

        # Pinned boto3 so the Converse API version does not depend on the runtime-included SDK
        self.boto3 = aws_lambda.LayerVersion(
            self, "Boto3+Bedrock", code=aws_lambda.Code.from_asset("./layers/boto3.zip"),
            compatible_runtimes=LAYER_RUNTIMES,
            description='boto3 1.44.3 (python3.13)')
