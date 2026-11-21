import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import assert from "node:assert/strict";
import test from "node:test";
import { PIPELINE_COUNT_METRICS, PIPELINE_DURATION_METRIC, PIPELINE_NAMESPACE, pipelineDashboard } from "../lib/pipeline-metrics";

test("pipeline dashboard graphs workshop run counts and durations", () => {
  const app = new App();
  const stack = new Stack(app, "Pipelines", { env: { account: "223663280572", region: "us-west-2" } });
  pipelineDashboard(stack, "PipelineRuns");
  const body = JSON.stringify(Template.fromStack(stack).findResources("AWS::CloudWatch::Dashboard"));
  assert.match(body, /PantherPipelineRuns/);
  assert.match(body, new RegExp(PIPELINE_NAMESPACE.replace("/", "\\/")));
  for (const name of PIPELINE_COUNT_METRICS) assert.match(body, new RegExp(name));
  assert.match(body, new RegExp(PIPELINE_DURATION_METRIC));
  assert.match(body, /Runs by status/);
  assert.match(body, /Failures/);
  assert.match(body, /-P30D/);
  assert.match(body, /-PT24H/);
  assert.match(body, /-P7D/);
  assert.doesNotMatch(body, /AWS::Grafana/);
  assert.doesNotMatch(body, /StateMachineArn/);
});
