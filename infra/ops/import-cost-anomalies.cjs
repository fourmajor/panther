// One-time, read-only discovery + CDK synthesis for native CloudFormation import.
// Never deploy this import-only app; normal updates use bin/panther.ts.
const { execFileSync } = require('node:child_process');
const { App, Stack, CfnResource, RemovalPolicy } = require('aws-cdk-lib');
const account = process.env.PANTHER_AWS_ACCOUNT_ID;
if (!/^\d{12}$/.test(account || '')) throw new Error('PANTHER_AWS_ACCOUNT_ID is required');
function aws(args) {
  return JSON.parse(execFileSync('aws', [...args, '--region', 'us-east-1', '--output', 'json', '--no-cli-pager'], { encoding: 'utf8' }));
}
if (aws(['sts', 'get-caller-identity']).Account !== account) throw new Error('AWS account mismatch');
const monitors = aws(['ce', 'get-anomaly-monitors']).AnomalyMonitors;
const service = monitors.filter(item => item.MonitorType === 'DIMENSIONAL' && item.MonitorDimension === 'SERVICE');
if (service.length !== 1) throw new Error('Expected exactly one existing SERVICE monitor; inspect manually');
const monitor = service[0];
const subscriptions = aws(['ce', 'get-anomaly-subscriptions']).AnomalySubscriptions.filter(item =>
  item.MonitorArnList.length === 1 && item.MonitorArnList[0] === monitor.MonitorArn);
if (subscriptions.length !== 1 || subscriptions[0].Frequency !== 'DAILY') {
  throw new Error('Expected exactly one existing daily subscription; inspect before import');
}
const daily = subscriptions[0];
const app = new App();
const stack = new Stack(app, 'PantherCostAnomalies', { env: { account, region: 'us-west-2' } });
const monitorTags = aws(['ce', 'list-tags-for-resource', '--resource-arn', monitor.MonitorArn]).ResourceTags;
const subscriptionTags = aws(['ce', 'list-tags-for-resource', '--resource-arn', daily.SubscriptionArn]).ResourceTags;
const resource = new CfnResource(stack, 'ServiceMonitor', { type: 'AWS::CE::AnomalyMonitor', properties: {
  MonitorName: monitor.MonitorName, MonitorType: monitor.MonitorType, MonitorDimension: monitor.MonitorDimension,
  ...(monitorTags.length ? { ResourceTags: monitorTags } : {}),
} });
const subscription = new CfnResource(stack, 'DailyAnomalySubscription', { type: 'AWS::CE::AnomalySubscription', properties: {
  SubscriptionName: daily.SubscriptionName, Frequency: daily.Frequency,
  MonitorArnList: [resource.ref], ThresholdExpression: JSON.stringify(daily.ThresholdExpression),
  Subscribers: daily.Subscribers.map(item => ({ Address: item.Address, Type: item.Type })),
  ...(subscriptionTags.length ? { ResourceTags: subscriptionTags } : {}),
} });
resource.applyRemovalPolicy(RemovalPolicy.RETAIN);
subscription.applyRemovalPolicy(RemovalPolicy.RETAIN);
app.synth();
// Identifiers only; private subscriber information remains in the ignored assembly.
console.error(JSON.stringify({ ServiceMonitor: { MonitorArn: monitor.MonitorArn },
  DailyAnomalySubscription: { SubscriptionArn: daily.SubscriptionArn } }));
