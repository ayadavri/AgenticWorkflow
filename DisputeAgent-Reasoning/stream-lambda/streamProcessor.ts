import { unmarshall } from "@aws-sdk/util-dynamodb";
import type { AttributeValue } from "@aws-sdk/client-dynamodb";

function toStringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** One structured log line per DisputeCore DynamoDB stream record (for CloudWatch). */
function logStreamRecord(record: NormalizedStreamRecord): void {
  try {
    const keys = unmarshall(
      (record.dynamodbKeys || {}) as Record<string, AttributeValue>
    );
    const newImage = record.dynamodbNewImage
      ? unmarshall((record.dynamodbNewImage || {}) as Record<string, AttributeValue>)
      : {};
    const oldImage = record.dynamodbOldImage
      ? unmarshall((record.dynamodbOldImage || {}) as Record<string, AttributeValue>)
      : undefined;
    const entityType =
      toStringValue(newImage.entityType) ||
      (oldImage ? toStringValue(oldImage.entityType) : "") ||
      undefined;
    console.log(
      JSON.stringify({
        msg: "dispute_core_stream_record",
        eventName: record.eventName,
        eventID: record.eventID,
        sequenceNumber: record.sequenceNumber,
        streamViewType: record.streamViewType,
        approximateCreationDateTime: record.approximateCreationDateTime,
        pk: toStringValue(keys.PK) || undefined,
        sk: toStringValue(keys.SK) || undefined,
        entityType: entityType ?? null,
      })
    );
  } catch (err) {
    console.error(
      JSON.stringify({
        msg: "dispute_core_stream_record_log_failed",
        eventName: record.eventName,
        eventID: record.eventID,
        error: err instanceof Error ? err.message : String(err),
      })
    );
  }
}

export interface NormalizedStreamRecord {
  eventID?: string;
  eventName?: string;
  eventSource?: string;
  eventSourceARN?: string;
  awsRegion?: string;
  approximateCreationDateTime?: number;
  sequenceNumber?: string;
  sizeBytes?: number;
  streamViewType?: string;
  dynamodbKeys?: Record<string, unknown>;
  dynamodbNewImage?: Record<string, unknown>;
  dynamodbOldImage?: Record<string, unknown>;
}

export interface StreamHandlers {
  onInsert?: (record: NormalizedStreamRecord) => Promise<void>;
  onModify?: (record: NormalizedStreamRecord) => Promise<void>;
  onRemove?: (record: NormalizedStreamRecord) => Promise<void>;
}

export function normalizeDynamoStreamRecord(record: Record<string, unknown>): NormalizedStreamRecord {
  const dd = (record?.dynamodb ?? {}) as Record<string, unknown>;

  return {
    eventID: record?.eventID as string | undefined,
    eventName: record?.eventName as string | undefined,
    eventSource: record?.eventSource as string | undefined,
    eventSourceARN: record?.eventSourceARN as string | undefined,
    awsRegion: record?.awsRegion as string | undefined,
    approximateCreationDateTime: dd.ApproximateCreationDateTime as number | undefined,
    sequenceNumber: dd.SequenceNumber as string | undefined,
    sizeBytes: dd.SizeBytes as number | undefined,
    streamViewType: dd.StreamViewType as string | undefined,
    dynamodbKeys: (dd.Keys || {}) as Record<string, unknown>,
    dynamodbNewImage: (dd.NewImage || undefined) as Record<string, unknown> | undefined,
    dynamodbOldImage: (dd.OldImage || undefined) as Record<string, unknown> | undefined,
  };
}

export function normalizeDynamoStreamRecords(event: Record<string, unknown>): NormalizedStreamRecord[] {
  const records = (event?.Records || []) as Record<string, unknown>[];
  return records.map(normalizeDynamoStreamRecord);
}

export async function processDisputeCoreStreamEvents(
  event: Record<string, unknown>,
  handlers: StreamHandlers = {}
): Promise<{ recordCount: number; byEventName: Record<string, number> }> {
  const normalized = normalizeDynamoStreamRecords(event);
  const byEventName = { INSERT: 0, MODIFY: 0, REMOVE: 0, OTHER: 0 };

  console.log(
    JSON.stringify({
      msg: "dispute_stream_batch_start",
      recordCount: normalized.length,
    })
  );

  for (const record of normalized) {
    logStreamRecord(record);
    const stage =
      record.eventName === "INSERT"
        ? "onInsert"
        : record.eventName === "MODIFY"
          ? "onModify"
          : record.eventName === "REMOVE"
            ? "onRemove"
            : "unknown";

    try {
      switch (record.eventName) {
        case "INSERT":
          byEventName.INSERT += 1;
          if (handlers.onInsert) await handlers.onInsert(record);
          break;
        case "MODIFY":
          byEventName.MODIFY += 1;
          if (handlers.onModify) await handlers.onModify(record);
          break;
        case "REMOVE":
          byEventName.REMOVE += 1;
          if (handlers.onRemove) await handlers.onRemove(record);
          break;
        default:
          byEventName.OTHER += 1;
          console.warn(
            JSON.stringify({
              msg: "dispute_stream_unknown_event_name",
              eventName: record.eventName,
              eventID: record.eventID,
            })
          );
      }
    } catch (err) {
      console.error(
        JSON.stringify({
          msg: "dispute_stream_record_handler_failed",
          stage,
          eventName: record.eventName,
          eventID: record.eventID,
          sequenceNumber: record.sequenceNumber,
          error: err instanceof Error ? err.message : String(err),
          stack: err instanceof Error ? err.stack : undefined,
        })
      );
      throw err;
    }
  }

  console.log(
    JSON.stringify({
      msg: "dispute_stream_batch_complete",
      recordCount: normalized.length,
      byEventName,
    })
  );

  return { recordCount: normalized.length, byEventName };
}
