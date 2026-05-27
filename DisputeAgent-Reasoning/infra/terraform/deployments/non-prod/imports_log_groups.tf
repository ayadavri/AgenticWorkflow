# Adopt log groups Lambda created automatically (ResourceAlreadyExists on first Terraform create).
# Safe to keep: import is a no-op once resources are in state.

import {
  to = module.dispute_judgment_lambda.aws_cloudwatch_log_group.judgment[0]
  id = "/aws/lambda/dispute-agent-judgment"
}

import {
  to = module.dispute_core_dynamodb.aws_cloudwatch_log_group.ddb_stream_lambda[0]
  id = "/aws/lambda/dispute-core-ddb-stream"
}

# Event bus log group (/aws/events/dispute-event-bus): no import block — create via apply.
# If AWS already created it (after bus logging was enabled), add:
#   import { to = module.dispute_event_bus.aws_cloudwatch_log_group.event_bus
#            id = "/aws/events/dispute-event-bus" }
