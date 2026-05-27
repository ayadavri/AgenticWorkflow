import {
  processDisputeCoreStreamEvents,
  type NormalizedStreamRecord,
} from "./streamProcessor";
import { unmarshall } from "@aws-sdk/util-dynamodb";
import type { AttributeValue } from "@aws-sdk/client-dynamodb";
import {
  entityTypeFromImages,
  envFlag,
  getStreamImages,
  isDisputeEntityType,
  publishDisputeStreamToEventBridge,
} from "./eventBridgeDisputePublish";

function logStreamKeys(label: string, record: NormalizedStreamRecord): void {
  if (!envFlag("STREAM_DEBUG", true)) return;
  try {
    const keys = unmarshall((record.dynamodbKeys || {}) as Record<string, AttributeValue>);
    console.log(label, JSON.stringify({ keys, pk: keys?.PK, sk: keys?.SK }));
  } catch (err) {
    console.error(
      JSON.stringify({
        msg: "dispute_core_stream_debug_keys_log_failed",
        label,
        eventName: record.eventName,
        eventID: record.eventID,
        error: err instanceof Error ? err.message : String(err),
      })
    );
  }
}

function logHandlerEvent(msg: string, fields: Record<string, unknown>, level: "info" | "error" = "info"): void {
  const line = JSON.stringify({ msg, component: "dispute-stream-lambda", ...fields });
  if (level === "error") console.error(line);
  else console.log(line);
}

async function publishIfDisputeEntity(
  record: NormalizedStreamRecord,
  stats: { skippedNonEntity: number; published: number; failed: number }
): Promise<void> {
  const images = getStreamImages(record);
  const entityType = entityTypeFromImages(images);
  if (!isDisputeEntityType(entityType)) {
    stats.skippedNonEntity += 1;
    logHandlerEvent("dispute_record_skipped_non_entity", {
      eventName: record.eventName,
      eventID: record.eventID,
      entityType: entityType || null,
    });
    return;
  }

  try {
    logHandlerEvent("dispute_record_publish_start", {
      eventName: record.eventName,
      eventID: record.eventID,
      entityType,
    });
    await publishDisputeStreamToEventBridge(record, { images });
    stats.published += 1;
    logHandlerEvent("dispute_record_publish_ok", {
      eventName: record.eventName,
      eventID: record.eventID,
    });
  } catch (err) {
    stats.failed += 1;
    logHandlerEvent(
      "dispute_record_publish_failed",
      {
        eventName: record.eventName,
        eventID: record.eventID,
        entityType,
        error: err instanceof Error ? err.message : String(err),
        stack: err instanceof Error ? err.stack : undefined,
      },
      "error"
    );
    throw err;
  }
}

export const handler = async (
  event: Record<string, unknown>
): Promise<{ ok: boolean; stream: unknown }> => {
  const stats = { skippedNonEntity: 0, published: 0, failed: 0 };

  logHandlerEvent("dispute_lambda_invocation_start", {
    recordCount: Array.isArray(event?.Records) ? event.Records.length : 0,
  });

  try {
    const stream = await processDisputeCoreStreamEvents(event, {
      onInsert: async (record) => {
        logStreamKeys("[DisputeCore stream] INSERT", record);
        await publishIfDisputeEntity(record, stats);
      },
      onModify: async (record) => {
        logStreamKeys("[DisputeCore stream] MODIFY", record);
        await publishIfDisputeEntity(record, stats);
      },
      onRemove: async (record) => {
        logStreamKeys("[DisputeCore stream] REMOVE", record);
        await publishIfDisputeEntity(record, stats);
      },
    });

    logHandlerEvent("dispute_lambda_invocation_ok", {
      ...stream,
      disputeSkippedNonEntity: stats.skippedNonEntity,
      disputePublished: stats.published,
      disputePublishFailed: stats.failed,
    });

    return {
      ok: true,
      stream: {
        ...stream,
        disputeSkippedNonEntity: stats.skippedNonEntity,
        disputePublished: stats.published,
        disputePublishFailed: stats.failed,
      },
    };
  } catch (err) {
    logHandlerEvent(
      "dispute_lambda_invocation_failed",
      {
        error: err instanceof Error ? err.message : String(err),
        stack: err instanceof Error ? err.stack : undefined,
        disputeSkippedNonEntity: stats.skippedNonEntity,
        disputePublished: stats.published,
        disputePublishFailed: stats.failed,
      },
      "error"
    );
    throw err;
  }
};
