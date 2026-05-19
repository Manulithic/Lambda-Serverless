#####COST-SAVER########
#This lambda stops non production ec2 instances(instances that doesn't required to be run 24*7) by it's tags "Autostop = Yes" thereby saving cost

import boto3
import logging
from botocore.exceptions import ClientError

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
  try:
    logger.info(f"stopping instances: {instanceids}")
    ec2.stop_instances(InstanceIds=instanceids,DryRun=True)
    logger.info("Successfully initiated stop request")
  except ClientError as e:
    if "DryRunOperation" in str(e):
      logger.info("Dry Run Successfull")
    else:
      logger.info("Dry Run UnSuccessfull")
  
def lambda_handler(event,context):
  logger.info("Lambda execution started")
  instanceids = get_autostop_instances()
  stop_autostop_instances(instanceids)
  logger.info("Lambda execution completed")
  return {
    "statusCode": "200",
    "body": "Lambda Execution completed"
  }

#this lambda function can be integrated with eventbridge trigger(cron) to trigger the lambda at a suitable timings.
