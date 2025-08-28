import boto3, json, os
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TABLE_NAME"])
ec2 = boto3.client("ec2")
lambda_client = boto3.client("lambda")

class VPCManager:
    def start(self, event):
        body = json.loads(event.get("body", "{}"))
        vpc_cidr = body.get("vpc_cidr")
        subnets = body.get("subnets")

        if not vpc_cidr or not isinstance(subnets, list):
            return {"statusCode": 400, "body": json.dumps({"error": "Invalid input"})}

        vpc = ec2.create_vpc(CidrBlock=vpc_cidr)
        vpc_id = vpc["Vpc"]["VpcId"]

        table.put_item(Item={
            "vpc_id": vpc_id,
            "vpc_cidr": vpc_cidr,
            "status": "CREATING"
        })

        # async call to continue vpc setup
        lambda_client.invoke(
            FunctionName=os.environ["CONTINUE_LAMBDA_NAME"],
            InvocationType="Event",
            Payload=json.dumps({
                "vpc_id": vpc_id,
                "subnets": subnets
            })
        )

        return {"statusCode": 202, "body": json.dumps({"vpc_id": vpc_id, "status": "CREATING"})}

    #Get API call to fetch the status and details of VPC
    def get_status(self, vpc_id):
        try:
            resp = table.get_item(Key={"vpc_id": vpc_id})
            item = resp.get("Item")
            if not item:
                return {"statusCode": 404, "body": json.dumps({"error": "Not found"})}
            return {"statusCode": 200, "body": json.dumps(item)}
        except ClientError as e:
            return {"statusCode": 500, "body": json.dumps({"error": str(e)})}

def lambda_handler(event, context):
    manager = VPCManager()
    path = event.get("path", "")
    http_method = event.get("httpMethod", "")

    if path.startswith("/vpc/create") and http_method == "POST":
        return manager.start(event)
    elif path.startswith("/vpc/status") and http_method == "GET":
        vpc_id = event.get("pathParameters", {}).get("vpc_id")
        return manager.get_status(vpc_id)
    else:
        return {"statusCode": 400, "body": json.dumps({"error": "Unsupported operation"})}
