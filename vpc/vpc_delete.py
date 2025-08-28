import boto3, os, botocore, time
import logging


logger = logging.getLogger()
logger.setLevel(logging.INFO)
ec2 = boto3.client("ec2")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TABLE_NAME"])

class VPCDeleter:
    def get_vpc(self, vpc_id):
        response = table.get_item(Key={"vpc_id": vpc_id})
        return response.get("Item")

    #Method to wait for nat gateway deletion
    def wait_for_nat_gateway_deletion(self, nat_gw_id, timeout=120, poll_interval=10):
        start_time = time.time()
        while True:
            try:
                response = ec2.describe_nat_gateways(NatGatewayIds=[nat_gw_id])
                nat_gateway = response['NatGateways'][0]
                state = nat_gateway['State']
                if state == 'deleted':
                    logger.info(f"NAT Gateway {nat_gw_id} deleted.")
                    break
                elif state == 'deleting':
                    logger.info(f"NAT Gateway {nat_gw_id} is deleting... waiting.")
                else:
                    logger.info(f"NAT Gateway {nat_gw_id} state: {state}. Waiting for deletion.")
            except botocore.exceptions.ClientError as e:
                if 'NatGatewayNotFound' in str(e):
                    logger.info(f"NAT Gateway {nat_gw_id} no longer exists.")
                    break
                else:
                    raise

            if time.time() - start_time > timeout:
                raise TimeoutError(f"Timeout waiting for NAT Gateway {nat_gw_id} to be deleted")

            time.sleep(poll_interval)

    #Method to wait for deletion of Network Interface
    def wait_for_eni_deletion(self, eni_id, max_wait=60, interval=5):
        """Waits for ENI to be fully deleted (up to max_wait seconds)."""
        start_time = time.time()
        
        while True:
            try:
                ec2.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
                if time.time() - start_time > max_wait:
                    raise TimeoutError(f"Timed out waiting for ENI {eni_id} to delete.")
                time.sleep(interval)
            except botocore.exceptions.ClientError as e:
                if e.response['Error']['Code'] == 'InvalidNetworkInterfaceID.NotFound':
                    return
                else:
                    raise

    #Method to wait for Internet Gateway deletion
    def wait_for_igw_deletion(self, igw_id, timeout=60):
        start = time.time()
        while True:
            try:
                ec2.describe_internet_gateways(InternetGatewayIds=[igw_id])
                if time.time() - start > timeout:
                    logger.info(f"Timeout waiting for IGW {igw_id} to be deleted")
                    break
                time.sleep(3)  
            except botocore.exceptions.ClientError as e:
                if "InvalidInternetGatewayID.NotFound" in str(e):
                    logger.info(f"Internet Gateway {igw_id} deleted")
                    break
                else:
                    raise
    
    def handle(self, event):
        vpc_id = event.get("vpc_id")

        try:
            # Get VPC details from DynamoDB
            record = self.get_vpc(vpc_id)
            if not record:
                raise Exception("VPC not found")


            # Delete NAT Gateway and release Elastic IP
            nat_gw_id = record.get("nat_gateway_id")
            eip_allocation_id = record.get("elastic_ip_allocation_id")

            if nat_gw_id:
                ec2.delete_nat_gateway(NatGatewayId=nat_gw_id)
                self.wait_for_nat_gateway_deletion(nat_gw_id)



            if eip_allocation_id:
                ec2.release_address(AllocationId=eip_allocation_id)

            # Delete subnets
            for subnet in record.get("subnet_ids", []):
                subnet_id = subnet["subnet_id"]
                enis = ec2.describe_network_interfaces(Filters=[{'Name': 'subnet-id', 'Values': [subnet_id]}])["NetworkInterfaces"]
                for eni in enis:
                    eni_id = eni["NetworkInterfaceId"]
                    ec2.delete_network_interface(NetworkInterfaceId=eni_id)
                    self.wait_for_eni_deletion(ec2, eni_id)
                ec2.delete_subnet(SubnetId=subnet_id)
                logger.info(f"Subnet id {subnet_id} deleted")

            # Delete route tables associated with the VPC (except main route table)
            rts = ec2.describe_route_tables(Filters=[{'Name':'vpc-id', 'Values':[vpc_id]}])["RouteTables"]
            for rt in rts:
                # Skip main route table
                rt_id = rt["RouteTableId"]
                if rt.get("Associations"):
                    main_association = any(a.get("Main") for a in rt["Associations"])
                    if main_association:
                        continue
                    # Disassociate non-main associations
                    for assoc in rt["Associations"]:
                        if not assoc.get("Main"):
                            assoc_id = assoc.get("RouteTableAssociationId")
                            if assoc_id:
                                ec2.disassociate_route_table(AssociationId=assoc_id)  
                ec2.delete_route_table(RouteTableId=rt_id)

            # Detach and delete Internet Gateway
            igw_id = record.get("internet_gateway_id")
            if igw_id:
                ec2.detach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
                ec2.delete_internet_gateway(InternetGatewayId=igw_id)
                self.wait_for_igw_deletion(igw_id)

            #Delete VPC
            ec2.delete_vpc(VpcId=vpc_id)

            #Set status to deleted in dynamodb and remove the vpc metadata
            table.update_item(
                Key={"vpc_id": vpc_id},
                UpdateExpression="SET #s = :s REMOVE vpc_cidr, subnet_ids, internet_gateway_id, nat_gateway_id, elastic_ip_allocation_id",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "DELETED"}
            )

        except Exception as e:
            logger.info(e)
            #Set status in Dynamodb as delete_failed
            table.update_item(
                Key={"vpc_id": vpc_id},
                UpdateExpression="SET #s = :s",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "DELETE_FAILED"}
            )

def lambda_handler(event, context):
    VPCDeleter().handle(event)
