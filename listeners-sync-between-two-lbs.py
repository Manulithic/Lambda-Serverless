import boto3
import pg8000
import csv
import json
import os
import logging
from botocore.exceptions import ClientError
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SES_REGION = "us-east-1"

ELB_REGIONS = [
    "ap-south-1",
    "us-north-1"
]

ses = boto3.client("ses", region_name=SES_REGION)

DB_CONFIG = {
    "host": os.environ["DB_HOST"],
    "database": os.environ["DB_NAME"],
    "user": os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
    "port": 5432
}

MAIL_SENDER = os.environ["MAIL_SENDER"]
MAIL_RECIPIENTS = [mail.strip() for mail in os.environ["MAIL_RECIPIENTS"].split(",")]


def db_connect():
    return pg8000.connect(**DB_CONFIG)


def fetch_preprod_lbs():
    logger.info("Fetching preprod load balancers from DB")
    conn = cursor = None

    try:
        conn = db_connect()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT name FROM saas_lb ORDER BY name ASC;")

        preprod_lbs = [row[0] for row in cursor.fetchall() if row[0]]

        logger.info("Fetched %s preprod load balancers", len(preprod_lbs))
        return preprod_lbs

    except Exception:
        logger.exception("Failed fetching preprod load balancers")
        raise

    finally:
        if cursor: cursor.close()
        if conn: conn.close()
        logger.info("Closed DB connection for fetch_preprod_lbs")


def fetch_prod_mapping(preprod_lbs):
    logger.info("Fetching prod LB mappings")
    conn = cursor = None
    mappings = []

    try:
        conn = db_connect()
        cursor = conn.cursor()
        query = "SELECT metadata FROM saas_lb WHERE name = %s;"

        for preprod_lb in preprod_lbs:
            cursor.execute(query, (preprod_lb,))
            result = cursor.fetchone()

            mappings.append({"preprod_lb": preprod_lb, "prod_lb": result[0].strip() if result and result[0] else None})

        logger.info("Generated %s preprod ↔ prod mappings", len(mappings))
        return mappings

    except Exception:
        logger.exception("Failed fetching prod mappings")
        raise

    finally:
        if cursor: cursor.close()
        if conn: conn.close()
        logger.info("Closed DB connection for fetch_prod_mapping")


def get_lb_arn_map():
    logger.info("Fetching load balancer ARN mapping across %s regions", len(ELB_REGIONS))
    lb_map = {}

    try:
        for region in ELB_REGIONS:
            logger.info("Fetching load balancers | Region=%s", region)

            regional_elbv2 = boto3.client("elbv2", region_name=region)
            paginator = regional_elbv2.get_paginator("describe_load_balancers")

            region_count = 0

            for page in paginator.paginate():
                lbs = page.get("LoadBalancers", [])
                region_count += len(lbs)

                for lb in lbs:
                    lb_map[lb["LoadBalancerName"]] = {"arn": lb["LoadBalancerArn"], "region": region}

            logger.info("Fetched %s load balancers | Region=%s", region_count, region)

        logger.info("Fetched total %s load balancers across all regions", len(lb_map))
        return lb_map

    except ClientError:
        logger.exception("Failed fetching load balancer ARNs")
        raise


def get_listener_ports(elbv2_client, lb_arn):
    return {
        l["Port"]
        for l in elbv2_client.describe_listeners(LoadBalancerArn=lb_arn).get("Listeners", [])}


def compare_listener_ports(mappings, lb_arn_map):
    logger.info("Starting listener comparison for %s mappings", len(mappings))
    report = []

    for item in mappings:
        preprod_lb, prod_lb = item["preprod_lb"], item["prod_lb"]

        source_lb = lb_arn_map.get(preprod_lb)
        target_lb = lb_arn_map.get(prod_lb)

        source_arn = source_lb["arn"] if source_lb else None
        target_arn = target_lb["arn"] if target_lb else None

        if not source_arn:
            logger.warning("Source ARN missing | preprodLB=%s", preprod_lb)

        if not target_arn:
            logger.warning("Target ARN missing | prod=%s", prod_lb)

        if not source_arn or not target_arn:
            continue

        try:
            source_client = boto3.client("elbv2", region_name=source_lb["region"])
            target_client = boto3.client("elbv2", region_name=target_lb["region"])

            missing_ports = sorted(get_listener_ports(source_client, source_arn) - get_listener_ports(target_client, target_arn))

            if missing_ports:
                logger.warning("Missing ports | preprodLB=%s | prod=%s | PORTS=%s", preprod_lb, prod_lb, missing_ports)
                report.append({"preprodLB": preprod_lb, "prod LB": prod_lb, "MISSING PORTS": "'" + ",".join(map(str, missing_ports))})

        except Exception:
            logger.exception("Listener comparison failed | preprodLB=%s | prod=%s", preprod_lb, prod_lb)

    logger.info("Listener comparison completed | Issues found=%s", len(report))
    return report


def generate_csv(report):
    file_path = "/tmp/prod-ports-mismatch.csv"

    with open(file_path, "w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=["preprodLB", "prod LB", "MISSING PORTS"])
        writer.writeheader()
        writer.writerows(report)

    logger.info("CSV report generated | Path=%s | Records=%s", file_path, len(report))
    return file_path


def send_email(csv_path):
    logger.info("Sending mismatch report email")

    try:
        msg = MIMEMultipart()
        msg["Subject"] = "prod Ports Mismatch Report"
        msg["From"] = MAIL_SENDER
        msg["To"] = ",".join(MAIL_RECIPIENTS)

        msg.attach(MIMEText("Hello Team,\n\nPlease find attached the prod ports mismatch report.\n\nRegards,\nAWS Lambda", "plain"))

        with open(csv_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())

        encoders.encode_base64(part)

        part.add_header("Content-Disposition", "attachment; filename=prod-ports-mismatch.csv")

        msg.attach(part)

        ses.send_raw_email(Source=MAIL_SENDER, Destinations=MAIL_RECIPIENTS, RawMessage={"Data": msg.as_string()})

        logger.info("Email sent successfully | Recipients=%s", MAIL_RECIPIENTS)

    except ClientError:
        logger.exception("Failed sending email")
        raise


def lambda_handler(event, context):
    logger.info("Starting preprod prod listener validation")

    try:
        report = compare_listener_ports(fetch_prod_mapping(fetch_preprod_lbs()), get_lb_arn_map())

        if not report:
            logger.info("No listener mismatch found | Skipping CSV generation and email")

            return {
                "statusCode": 200,
                "body": json.dumps({
                    "status": "success",
                    "message": "No listener port mismatch found"
                })
            }

        csv_path = generate_csv(report)
        send_email(csv_path)

        logger.info("Lambda execution completed successfully | Issues found=%s", len(report))

        return {
            "statusCode": 200,
            "body": json.dumps({
                "status": "success",
                "issues_found": len(report),
                "csv_report": csv_path
            })
        }

    except Exception as exc:
        logger.exception("Lambda execution failed")

        return {
            "statusCode": 500,
            "body": json.dumps({
                "status": "failed",
                "error": str(exc)
            })
        }
