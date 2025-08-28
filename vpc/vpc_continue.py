import boto3, os, json
from botocore.exceptions import ClientError
import logging


ec2 = boto3.client("ec2")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TABLE_NAME"])
lambda_client = boto3.client("lambda")
logger = logging.getLogger()
logger.setLevel(logging.INFO)

class VPCContinuation:

    #Method to wait for a resource creation to complete
    def wait_for_resource(self, waiter_name, params, delay=15, max_attempts=25):
        waiter = ec2.get_waiter(waiter_name)
        waiter.wait(**params, WaiterConfig={'Delay': delay, 'MaxAttempts': max_attempts})

    def handle(self, event):
        vpc_id = event.get("vpc_id")
        subnets = event.get("subnets")

        try:
            # Create Internet Gateway
            logger.info("Creating internet gateway")
            igw_response = ec2.create_internet_gateway()
            igw = igw_response["InternetGateway"]['InternetGatewayId']

            #Waiting for VPC to be available before setting attributes and attaching IG
            self.wait_for_resource('vpc_available', {'VpcIds': [vpc_id]})
            ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={"Value": True})
            ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={"Value": True})
            ec2.attach_internet_gateway(InternetGatewayId=igw, VpcId=vpc_id)

            subnet_records = []
            nat_subnet = None
            eip_id = None
            nat_gw_id = None

            #Initiating subnet creation
            for subnet in subnets:
                cidr = subnet.get("cidr")
                s_type = subnet.get("type", "private")
                sn = ec2.create_subnet(CidrBlock=cidr, VpcId=vpc_id)
                subnet_id = sn["Subnet"]["SubnetId"]

                # Create and associate Route Table
                rt = ec2.create_route_table(VpcId=vpc_id)
                rtid = rt["RouteTable"]["RouteTableId"]

                if s_type == "public":
                    ec2.create_route(RouteTableId=rtid, DestinationCidrBlock="0.0.0.0/0", GatewayId=igw)
                else:
                    if not nat_gw_id:
                        nat_subnet = subnet_id
                        eip = ec2.allocate_address(Domain="vpc")
                        eip_id = eip["AllocationId"]
                        nat = ec2.create_nat_gateway(SubnetId=nat_subnet, AllocationId=eip_id)
                        nat_gw_id = nat["NatGateway"]["NatGatewayId"]
                        self.wait_for_resource('nat_gateway_available', {'NatGatewayIds': [nat_gw_id]})
                    ec2.create_route(RouteTableId=rtid, DestinationCidrBlock="0.0.0.0/0", NatGatewayId=nat_gw_id)

                ec2.associate_route_table(RouteTableId=rtid, SubnetId=subnet_id)

                subnet_records.append({
                    "cidr": cidr,
                    "type": s_type,
                    "subnet_id": subnet_id
                })

            #Adding VPC metadata to dynamodb
            table.update_item(
                Key={"vpc_id": vpc_id},
                UpdateExpression="SET #s = :s, subnet_ids = :subnets, internet_gateway_id = :igw, nat_gateway_id = :natgw, elastic_ip_allocation_id = :eipalloc",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":s": "COMPLETED",
                    ":subnets": subnet_records,        
                    ":igw": igw,         
                    ":natgw": nat_gw_id,
                    ":eipalloc": eip_id         
    }
            )
        except Exception as e:
            logger.info(e)
            #Deleting the created VPC in case of error during VPC creation
            lambda_client.invoke(
                FunctionName=os.environ["DELETE_LAMBDA_NAME"],
                InvocationType="Event",
                Payload=json.dumps({"vpc_id": vpc_id})
            )
            #Adding status in Dynamodb as VPC creation ended up in error state
            table.update_item(
                Key={"vpc_id": vpc_id},
                UpdateExpression="SET #s = :s",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "VPC_CREATION_ERROR"}
            )

def lambda_handler(event, context):
    VPCContinuation().handle(event)
