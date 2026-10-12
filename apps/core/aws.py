"""AWS helpers. boto3 picks credentials from the IAM role attached to the ECS
task / EKS service account (IRSA) — never hard-code access keys."""

import json
import logging
import os
from functools import cache

logger = logging.getLogger(__name__)


@cache  # fetch once per process
def get_secret(secret_id: str, region: str | None = None) -> dict[str, str]:
    import boto3

    client = boto3.client("secretsmanager", region_name=region or os.getenv("AWS_REGION"))
    return json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])


def load_secrets_into_environ() -> None:
    """If AWS_SECRETS_ID is set, copy its JSON keys into os.environ (without
    overriding values already set), so settings read them like any env var.

    Secret example: {"SECRET_KEY": "...", "DATABASE_URL": "postgres://...@rds..."}
    """
    secret_id = os.getenv("AWS_SECRETS_ID")
    if not secret_id:
        return
    for key, value in get_secret(secret_id).items():
        os.environ.setdefault(key, value)
    logger.info("Loaded secrets from AWS Secrets Manager", extra={"secret_id": secret_id})
