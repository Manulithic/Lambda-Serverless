#this lambda function helps you create s3 bucket for each one of your customer, if you intend to store their logs separately.

import sys
import boto3
import hashlib
import random
import logging
import json

s3 = boto3.client('s3')

logging.basicConfig(level=logging.INFO)
logger=logging.getLogger()

def get_customer_name():
    with open("input.json", "r") as file:
        data = json.load(file)
        customer_name = data['customer'].lower()
        customer_id = data['id']
        customer_region = data['region']
        logger.info(f"customer name is: {customer_name}")
        logger.info(f"customer id is: {customer_id}")
        logger.info(f"customer region is: {customer_region}")
    return customer_name,customer_id,customer_region

def bucket_name(customer_name, customer_id):
    random_number = random.randint(1000, 999999)
    hashobj = hashlib.md5(str(random_number).encode())
    randid = hashobj.hexdigest()[:6]
    logger.info(f"fecting bucket name to be created for customer {customer_name} with id {customer_id}")
    bucket = f"cust-{customer_name}-{customer_id}-{randid}"
    return bucket

def create_customer_bucket(bucket, customer_region):
    logger.info(f"creating bucket: {bucket}")
    s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={'LocationConstraint': customer_region})
    logger.info(f"bucket {bucket} is created")

def lambda_handler(event, context):
    customer_name,customer_id,customer_region = get_customer_name()
    bucket = bucket_name(customer_name, customer_id)
    create_customer_bucket(bucket, customer_region)
    return { "status" : 200, "body": "bucket created successfully" }
