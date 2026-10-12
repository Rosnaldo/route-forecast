# AWS deployment notes

```
Route 53 ─► CloudFront ─┬─► S3 (static + media, private, Origin Access Control)
                        └─► ALB ─► ECS Fargate / EKS
                                    ├─ web    (gunicorn + uvicorn workers)
                                    ├─ worker (celery)
                                    └─ beat   (celery beat, exactly 1)
                                         │
                     ┌───────────────────┼────────────────────┐
                RDS PostgreSQL     ElastiCache Redis     Secrets Manager
                (Multi-AZ, private)  (Celery broker,      (SECRET_KEY, DATABASE_URL...)
                                     cache)
```

| Service | How this project uses it |
|---|---|
| **EC2** | Simplest option: one VM running `docker compose`. Fine for learning; you patch/scale it yourself. |
| **ECS (Fargate)** | [deploy/aws/ecs-task-definition.json](../deploy/aws/ecs-task-definition.json): one service per process type (web/worker/beat), secrets injected from Secrets Manager, logs to CloudWatch, health check on `/health/`. |
| **EKS** | [deploy/k8s/app.yaml](../deploy/k8s/app.yaml): Deployments, a migration Job, HPA, ALB Ingress, IRSA service account, External Secrets. |
| **RDS PostgreSQL** | `DATABASE_URL` points at the RDS endpoint; `sslmode=require` in [prod.py](../config/settings/prod.py). Use RDS Proxy or pgbouncer when many tasks open connections. |
| **S3** | `django-storages` `S3Storage` for media + `S3ManifestStaticStorage` for static ([prod.py](../config/settings/prod.py)). Bucket is private. |
| **CloudFront** | `AWS_S3_CUSTOM_DOMAIN` makes Django generate CDN URLs; CloudFront reads S3 via OAC. |
| **Secrets Manager** | Either ECS `secrets` injection (task def) or the app pulls them at startup: [core/aws.py](../apps/core/aws.py) `load_secrets_into_environ()` (set `AWS_SECRETS_ID`). |
| **IAM** | No access keys anywhere. ECS task role / EKS IRSA grant least-privilege access ([iam-task-role-policy.json](../deploy/aws/iam-task-role-policy.json)); GitHub Actions assumes a role via OIDC ([ci.yml](../.github/workflows/ci.yml)). |

## Release flow
1. CI: lint → tests (Postgres + Redis services) → build image → push to ECR (`:git-sha`).
2. Run migrations once (ECS one-off task / K8s Job) **before** rolling out web.
   Migrations must be backwards compatible with the running version
   (expand → deploy → contract).
3. Rolling deploy of web/worker; beat is `Recreate` with 1 replica.

## Gotchas
- `ALLOWED_HOSTS` must include the ALB health-check host, or have the probe send the right `Host` header.
- Celery workers need a `terminationGracePeriodSeconds` / ECS `stopTimeout` long enough to finish tasks (`acks_late=True` re-delivers otherwise).
