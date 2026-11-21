# Pipeline runs in Grafana

Panther's Editorial, Model, and Playback state machines already publish run metrics to
CloudWatch in `us-west-2` under the `AWS/States` namespace. No custom metric series is
added for this dashboard. Grafana is not part of the AWS deployment. Import
[`infra/grafana/pipeline-runs.json`](../infra/grafana/pipeline-runs.json) into the
self-hosted Grafana that already has a CloudWatch data source.

The dashboard graphs, for each of those three pipelines:

- runs by status: `ExecutionsStarted`, `ExecutionsSucceeded`, `ExecutionsFailed`,
  `ExecutionsAborted`, `ExecutionsTimedOut` (sum, one hour)
- duration: `ExecutionTime` average and p90, in milliseconds
- failures: `ExecutionsFailed`, `ExecutionsTimedOut`, and `ExecutionsAborted`

`ExecutionTime` is the Step Functions interval from start to close. A run that has not
closed yet does not contribute a duration.

## Import

In Grafana: Dashboards, New, Import, and upload `infra/grafana/pipeline-runs.json`.
When asked for **CloudWatch data source**, choose the existing CloudWatch data source.
That choice fills the `datasource` variable. Region defaults to `us-west-2`.

The Editorial, Model, and Playback variables list `StateMachineArn` values from
`ExecutionsStarted` and keep the ARN whose name contains `EditorialProcessing`,
`ModelProcessing`, or `PlaybackProcessing`. Those strings are the CDK construct ids.
If a variable is empty, the machine has not emitted that metric yet, or the generated
state-machine name does not contain the construct id. Open the variable and select the
ARN. Do not rename a state machine to satisfy the filter.

## Read-only data source permissions

Attach this policy to the IAM role the existing Grafana CloudWatch data source already
assumes. Do not create an IAM user, an access key, or a new role for this dashboard.
This repository does not provision those credentials.

CloudWatch metric reads cannot be limited to a state-machine ARN. `Resource` is `*`.
The actions are read-only. This dashboard does not query logs, and it does not need
`states:StartExecution` or any write.

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
        "cloudwatch:DescribeAlarmHistory",
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
    }
  ]
}
```

`cloudwatch:GetMetricData` and `cloudwatch:ListMetrics` are what the panels and the
state-machine variables call. `GetMetricStatistics` remains because older Grafana
CloudWatch plugin builds still use it. The describe-alarm and EC2/tag actions are the
plugin's metric-browser calls, not a request to read game data. `states:ListStateMachines`
is not required. The variable values come from `ListMetrics`.
