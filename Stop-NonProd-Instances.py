#####COST-SAVER########
#This lambda stops non production ec2 instances(instances that doesn't required to be run 24*7) by it's tags "Autostop = Yes" thereby saving cost

import boto3
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()
ec2 = boto3.client('ec2')

def get_autostop_instances():
  logger.info("Fetching EC2 instances with Autostop=Yes")
  instanceids = []
  response = ec2.describe_instances()
  for reservation in response['Reservations']:
    for instance in reservation['Instances']:
      instance_id = instance['InstanceId']
      tags = instance.get('Tags', [])
      for tag in tags:
        if tag['Key'] == "Autostop" and tag['Value'] == "Yes":
          instanceids.append(instance_id)
  logger.info(f"Found instances with autostop tags: {instance_id}")
  return instanceids

def stop_autostop_instances(instanceids):
  if not instanceids:
    logger.info("No instances found to stop")
    return
  logger.info("stopping instances: {instanceids}")
  ec2.stop_instances(InstanceIds=instanceids)
  logger.info("Successfully initiated stop request")
  
def lambda_handler(event,context):
  logger.info("Lambda execution started")
  instanceids = get_autostop_instances()
  stop_autostop_instances(instanceids)
  logger.info("Lambda execution ]completed")
  return {
    "statusCode": "200",
    "body": "Lambda Execution completed"
  }
