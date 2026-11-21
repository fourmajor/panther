import { Duration } from "aws-cdk-lib";
import { Construct } from "constructs";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";

/** Workshop run counters. One series per pipeline kind, not per session or job. */
export const PIPELINE_NAMESPACE = "Panther/Pipelines";
export const PIPELINE_COUNT_METRICS = ["RunsStarted", "RunsSucceeded", "RunsFailed"] as const;
export const PIPELINE_DURATION_METRIC = "RunDuration";

function search(metricName: string, statistic: string): cloudwatch.MathExpression {
  return new cloudwatch.MathExpression({
    expression: `SEARCH('{${PIPELINE_NAMESPACE},Pipeline} MetricName="${metricName}"', '${statistic}', 3600)`,
    usingMetrics: {},
    period: Duration.hours(1),
    label: "${PROP('Dim.Pipeline')}",
  });
}

/** CloudWatch view of the same runs the session page lists. */
export function pipelineDashboard(scope: Construct, id: string): cloudwatch.Dashboard {
  const dashboard = new cloudwatch.Dashboard(scope, id, {
    dashboardName: "PantherPipelineRuns",
    start: "-P30D",
  });
  const totals: Array<[string, string, string]> = [
    ["Runs started, 24 hours", "RunsStarted", "-PT24H"],
    ["Runs succeeded, 24 hours", "RunsSucceeded", "-PT24H"],
    ["Runs failed, 24 hours", "RunsFailed", "-PT24H"],
    ["Runs started, 7 days", "RunsStarted", "-P7D"],
    ["Runs succeeded, 7 days", "RunsSucceeded", "-P7D"],
    ["Runs failed, 7 days", "RunsFailed", "-P7D"],
  ];
  dashboard.addWidgets(...totals.map(([title, metric, start]) => new cloudwatch.SingleValueWidget({
    title,
    width: 4,
    height: 4,
    start,
    metrics: [search(metric, "Sum")],
    setPeriodToTimeRange: true,
  })));
  dashboard.addWidgets(
    new cloudwatch.GraphWidget({
      title: "Runs by status",
      width: 12,
      left: PIPELINE_COUNT_METRICS.map(name => search(name, "Sum")),
    }),
    new cloudwatch.GraphWidget({
      title: "Failures",
      width: 12,
      left: [search("RunsFailed", "Sum")],
    }),
  );
  dashboard.addWidgets(new cloudwatch.GraphWidget({
    title: "Duration",
    width: 24,
    left: [search(PIPELINE_DURATION_METRIC, "Average"), search(PIPELINE_DURATION_METRIC, "p90")],
  }));
  return dashboard;
}
