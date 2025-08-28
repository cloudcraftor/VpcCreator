import boto3
import os
import json

lambda_client = boto3.client("lambda")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TABLE_NAME"])

#lambda  to invoke the deletion of VPC

class VPCDeleteInvoker:
    def handle(self, event):
        vpc_id = event.get("pathParameters", {}).get("vpc_id")
        if not vpc_id:
            return {"statusCode": 400, "body": json.dumps({"error": "Missing vpc_id"})}

        lambda_client.invoke(
            FunctionName=os.environ["DELETE_LAMBDA_NAME"],
            InvocationType="Event",
            Payload=json.dumps({"vpc_id": vpc_id})
        )

        table.update_item(
                Key={"vpc_id": vpc_id},
                UpdateExpression="SET #s = :s",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "DELETE_INPROGRESS"}
            )

        return {
            "statusCode": 202,
            "body": json.dumps({"message": f"Deletion triggered for VPC {vpc_id}"})
        }

def lambda_handler(event, context):
    return VPCDeleteInvoker().handle(event)
