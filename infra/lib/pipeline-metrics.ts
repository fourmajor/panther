import { Duration } from "aws-cdk-lib";
import { Construct } from "constructs";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as sfn from "aws-cdk-lib/aws-stepfunctions";

/** Built-in Step Functions metrics. No custom metric series and no new service. */
export const PIPELINE_COUNT_METRICS = [
  "ExecutionsStarted",
  "ExecutionsSucceeded",
  "ExecutionsFailed",
  "ExecutionsAborted",
  "ExecutionsTimedOut",
] as const;

export const PIPELINE_DURATION_METRIC = "ExecutionTime";

export interface PipelineMachine {
  readonly type: string;
  readonly label: string;
  readonly machine: sfn.IStateMachine;
}

function metric(name: string, machine: sfn.IStateMachine, statistic: string): cloudwatch.Metric {
  return new cloudwatch.Metric({
    namespace: "AWS/States",
    metricName: name,
    dimensionsMap: { StateMachineArn: machine.stateMachineArn },
    statistic,
    period: Duration.hours(1),
  });
}

/** CloudWatch dashboard for the state machines Panther already runs. */
export function pipelineDashboard(scope: Construct, id: string, pipelines: readonly PipelineMachine[]): cloudwatch.Dashboard {
  const dashboard = new cloudwatch.Dashboard(scope, id, { dashboardName: "PantherPipelineRuns" });
  for (const pipeline of pipelines) {
    dashboard.addWidgets(new cloudwatch.GraphWidget({
      title: `${pipeline.label} runs by status`,
      width: 12,
      left: PIPELINE_COUNT_METRICS.map(name => metric(name, pipeline.machine, "Sum")),
    }));
    dashboard.addWidgets(new cloudwatch.GraphWidget({
      title: `${pipeline.label} duration`,
      width: 12,
      left: [
        metric(PIPELINE_DURATION_METRIC, pipeline.machine, "Average"),
        metric(PIPELINE_DURATION_METRIC, pipeline.machine, "p90"),
      ],
    }));
  }
  return dashboard;
}
