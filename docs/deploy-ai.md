# Deploy the AI service

`.github/workflows/deploy-ai.yml` lints and tests every pull request. A push to `Production` or `release` builds the Fargate image, runs migrations, and updates the ECS service.

The workflow assumes an IAM role with GitHub OIDC in `ap-south-1`. Set these repository variables (Settings → Secrets and variables → Actions → Variables):

| Variable | Required | Purpose |
| --- | --- | --- |
| `AWS_AI_ROLE_ARN` | yes | Role assumed via OIDC. Use `arn:aws:iam::213433448375:role/sybeez-school-gha-ai`. |
| `AWS_AI_SUBNETS` | yes | Comma-separated subnet IDs for the one-off Alembic task. Example: `subnet-aaa,subnet-bbb`. |
| `AWS_AI_SECURITY_GROUP` | yes | Security group for that task. It must reach Postgres. |
| `AWS_AI_ASSIGN_PUBLIC_IP` | no | `ENABLED` or `DISABLED`. Defaults to `DISABLED` (private subnets with a NAT). |
| `AWS_AI_CONTAINER` | no | Container name inside task definition `sybeez-school-ai`. Defaults to `sybeez-school-ai`. |

Deploy steps, in order:

1. Assume `AWS_AI_ROLE_ARN` in `ap-south-1`.
2. Build `infra/docker/ai.Dockerfile` and push it to ECR repository `sybeez-school-ai`, tagged with the git SHA and `latest`.
3. Register a new revision of task definition `sybeez-school-ai` that uses the SHA image.
4. Run that revision once with command `alembic upgrade head`. Subnets, security group, and public IP come from the variables above. The deploy stops if the task exits non-zero.
5. Update ECS service `sybeez-school-ai` on cluster `sybeez-school-cluster` to that revision. If the desired count is below 1, it is raised to 1. The workflow waits until the service is stable.

The task role still needs `secretsmanager:GetSecretValue` when the service loads `AWS_SECRETS_MANAGER_SECRET_ID`. The workflow does not read secret values. `JWT_SECRET` in that secret must be the same value the School backend uses to sign session tokens.
