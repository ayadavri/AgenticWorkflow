# Optional: adopt CloudWatch log groups if Lambda/EventBridge created them before Terraform (ResourceAlreadyExists).
# Remove leading # and run terraform plan once the log group exists in AWS:
#
# import {
#   to = module.dispute_judgment_lambda.aws_cloudwatch_log_group.judgment[0]
#   id = "/aws/lambda/dispute-agent-judgment"
# }
#
# import {
#   to = module.dispute_core_dynamodb.aws_cloudwatch_log_group.ddb_stream_lambda[0]
#   id = "/aws/lambda/dispute-core-ddb-stream"
# }
#
# Event bus: import { to = module.dispute_event_bus.aws_cloudwatch_log_group.event_bus
#            id = "/aws/events/dispute-event-bus" }
