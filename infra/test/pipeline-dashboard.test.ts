import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import * as sfn from "aws-cdk-lib/aws-stepfunctions";
import assert from "node:assert/strict";
import test from "node:test";
import { PIPELINE_COUNT_METRICS, PIPELINE_DURATION_METRIC, pipelineDashboard } from "../lib/pipeline-metrics";

test("pipeline dashboard graphs built-in status counts and durations", () => {
  const app = new App();
  const stack = new Stack(app, "Pipelines", { env: { account: "223663280572", region: "us-west-2" } });
  const machine = (id: string) => new sfn.StateMachine(stack, id, {
    definitionBody: sfn.DefinitionBody.fromChainable(new sfn.Pass(stack, id + "Pass")),
  });
  pipelineDashboard(stack, "PipelineRuns", [
    { type: "editorial", label: "Editorial", machine: machine("Editorial") },
    { type: "model", label: "Model", machine: machine("Model") },
    { type: "playback", label: "Playback", machine: machine("Playback") },
  ]);
  const body = JSON.stringify(Template.fromStack(stack).findResources("AWS::CloudWatch::Dashboard"));
  assert.match(body, /PantherPipelineRuns/);
  for (const name of PIPELINE_COUNT_METRICS) assert.match(body, new RegExp(name));
  assert.match(body, new RegExp(PIPELINE_DURATION_METRIC));
  assert.match(body, /Editorial runs by status/);
  assert.match(body, /Model duration/);
  assert.match(body, /Playback runs by status/);
  assert.doesNotMatch(body, /AWS::Grafana/);
  assert.doesNotMatch(body, /PutMetricData/);
});
