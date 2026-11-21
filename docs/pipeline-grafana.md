# Pipeline runs in Grafana

Pipeline runs are counted in CloudWatch namespace `Panther/Pipelines`, in `us-west-2`.
The samples come from the same workshop records the session page lists, including
transcription, audio assembly, 3D modeling, narration, asset and video generation,
scene video, episode assembly, and video finishing. Step Functions executions are not
the source. A run id or session id is never a dimension.

Metrics, each with one dimension `Pipeline` (the run kind):

- `RunsStarted`, `RunsSucceeded`, `RunsFailed` — count, emitted when a run is first
  recorded or when it reaches that status
- `RunDuration` — milliseconds from creation to the terminal update, average and p90

Game is not a dimension. Each extra game would bill another metric per pipeline.
A finished run from the last 14 days is published once by the existing 10-minute
watcher. CloudWatch rejects older timestamps. Later status changes publish themselves.

Import [`infra/grafana/pipeline-runs.json`](../infra/grafana/pipeline-runs.json).
The dashboard time range is 30 days. Stat panels also show the last 24 hours and 7 days.
The CloudWatch data source is the `datasource` variable. Region defaults to `us-west-2`.
Re-import replaces the previous Step Functions panels.

## Read-only data source

CDK creates IAM user `panther-grafana-readonly` and one access key. The key is written
only to Secrets Manager secret `panther/grafana-cloudwatch-readonly`.
`PantherWatchdogReadOnly` can call `secretsmanager:GetSecretValue` on that secret's ARN
and on `panther/viewer-credentials`. It cannot read other secrets. Do not create another
user or key, and do not print the secret value. Do not rotate the key for a policy change.

The user's policy is:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CloudWatchMetricsRead",
      "Effect": "Allow",
      "Action": [
        "cloudwatch:DescribeAlarms",
        "cloudwatch:DescribeAlarmsForMetric",
        "cloudwatch:GetMetricData",
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:ListMetrics"
      ],
      "Resource": "*"
    },
    {
      "Sid": "RegionsAndResourceTags",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeRegions",
        "ec2:DescribeTags",
        "tag:GetResources"
      ],
      "Resource": "*"
    },
    {
      "Sid": "LogGroupList",
      "Effect": "Allow",
      "Action": ["logs:DescribeLogGroups"],
      "Resource": "*"
    }
  ]
}
```

`logs:DescribeLogGroups` is only the list Grafana's data-source health check calls.
It is not permission to read log events. This dashboard does not query logs, and it
does not need `states:StartExecution` or any write.
