/// <reference types="node" />
import { EventBridgeClient, PutEventsCommand } from "@aws-sdk/client-eventbridge";
import { unmarshall } from "@aws-sdk/util-dynamodb";
import type { AttributeValue } from "@aws-sdk/client-dynamodb";
import type { NormalizedStreamRecord } from "./streamProcessor";

export type DisputeStreamEventType = "DISPUTE_INSERT" | "DISPUTE_MODIFY" | "DISPUTE_REMOVE";

type StreamOperation = "INSERT" | "MODIFY" | "REMOVE";

type RoutingTarget =
  | "invokeTemporal"
  | "invokeOpensearch"
  | "invokeDataWarehouse"
  | "invokeAgenticAI";

const EB_LOG = "[EventBridge dispute]";

function logDisputeEvent(
  msg: string,
  fields: Record<string, unknown>,
  level: "info" | "warn" | "error" = "info"
): void {
  const line = JSON.stringify({ msg, stream: "dispute", ...fields });
  if (level === "error") console.error(line);
  else if (level === "warn") console.warn(line);
  else console.log(line);
}

function streamRecordContext(record: NormalizedStreamRecord): Record<string, unknown> {
  return {
    eventName: record.eventName,
    eventID: record.eventID,
    sequenceNumber: record.sequenceNumber,
  };
}

const ROUTING_TARGETS: RoutingTarget[] = [
  "invokeTemporal",
  "invokeOpensearch",
  "invokeDataWarehouse",
  "invokeAgenticAI",
];

const ROUTING_TARGET_ENV_FLAGS: Record<RoutingTarget, string> = {
  invokeTemporal: "DISPUTE_CORE_INVOKE_TEMPORAL",
  invokeOpensearch: "DISPUTE_CORE_INVOKE_OPENSEARCH",
  invokeDataWarehouse: "DISPUTE_CORE_INVOKE_DATA_WAREHOUSE",
  invokeAgenticAI: "DISPUTE_CORE_INVOKE_AGENTIC_AI",
};

let warnedCustomEndpoint = false;
let eventBridgeClient: EventBridgeClient | null = null;

export interface DisputeCoreStreamDetail {
  sourceTable: string;
  eventName: string;
  disputeStreamEventType: DisputeStreamEventType;
  entityType: "DISPUTE";
  eventID?: string;
  sequenceNumber?: string;
  approximateCreationDateTime?: number;
  caseId?: string;
  accountId?: string;
  disputeNumber?: string;
  disputeId?: string;
  controlNumber?: string;
  pk?: string;
  sk?: string;
  keys: Record<string, unknown>;
  newImage: Record<string, unknown>;
  oldImage?: Record<string, unknown>;
}

export function disputeTableNameFromEnv(): string {
  return process.env.DISPUTE_TABLE_NAME?.trim() || "DisputeCore";
}

/** Dispute PutEvents target bus (separate from collections `EVENT_BUS_NAME`). */
function disputesEventBusNameFromEnv(): string | undefined {
  const name = process.env.DISPUTES_EVENT_BUS_NAME?.trim();
  return name ? name : undefined;
}

/** Env bool: unset/empty uses default; `1`/`true` on; `0`/`false` off. */
export function envFlag(name: string, defaultValue: boolean): boolean {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return defaultValue;
  return raw === "1" || raw.toLowerCase() === "true";
}

function isDisputeEventBridgeEnabled(): boolean {
  return envFlag("DISPUTE_CORE_EVENTBRIDGE_ENABLED", true);
}

function toStringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function toStreamOperation(name: string | undefined): StreamOperation | null {
  if (name === "INSERT" || name === "MODIFY" || name === "REMOVE") return name;
  return null;
}

function warnIfCustomEndpointMisconfigured(): void {
  if (warnedCustomEndpoint || !process.env.AWS_ENDPOINT_URL) return;
  warnedCustomEndpoint = true;
  console.warn(
    EB_LOG +
      " AWS_ENDPOINT_URL is set (" +
      process.env.AWS_ENDPOINT_URL +
      "). Remove it in deployed Lambdas so PutEvents uses the AWS EventBridge endpoint for this region."
  );
}

function getEventBridgeClient(): EventBridgeClient {
  if (eventBridgeClient) return eventBridgeClient;
  const region = process.env.AWS_REGION || "us-east-1";
  const endpoint = process.env.AWS_ENDPOINT_URL;
  eventBridgeClient = new EventBridgeClient({
    region,
    ...(endpoint
      ? {
          endpoint,
          credentials: {
            accessKeyId: process.env.AWS_ACCESS_KEY_ID || "test",
            secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY || "test",
          },
        }
      : {}),
  });
  return eventBridgeClient;
}

function routingFlags(): Record<RoutingTarget, boolean> {
  return {
    invokeTemporal: envFlag("DISPUTE_CORE_INVOKE_TEMPORAL", true),
    invokeOpensearch: envFlag("DISPUTE_CORE_INVOKE_OPENSEARCH", true),
    invokeDataWarehouse: envFlag("DISPUTE_CORE_INVOKE_DATA_WAREHOUSE", true),
    invokeAgenticAI: envFlag("DISPUTE_CORE_INVOKE_AGENTIC_AI", true),
  };
}

/** EventBridge DetailType per operation + target (disputes.case.*). Exported for tests. */
export function disputeDetailTypeForTarget(operation: StreamOperation, target: RoutingTarget): string {
  const envKey = "DISPUTE_DETAIL_TYPE_" + operation + "_" + target;
  const raw = process.env[envKey];
  if (raw !== undefined && raw !== "") return raw;

  if (operation === "INSERT") {
    switch (target) {
      case "invokeTemporal":
        return "disputes.case.created";
      case "invokeOpensearch":
        return "disputes.case.created.ready-for-index";
      case "invokeDataWarehouse":
        return "disputes.case.created.data-warehouse";
      case "invokeAgenticAI":
        return "disputes.case.created.agentic";
    }
  }
  if (operation === "MODIFY") {
    switch (target) {
      case "invokeTemporal":
        return "disputes.case.updated";
      case "invokeOpensearch":
        return "disputes.case.updated.ready-for-index";
      case "invokeDataWarehouse":
        return "disputes.case.updated.data-warehouse";
      case "invokeAgenticAI":
        return "disputes.case.updated.agentic";
    }
  }
  switch (target) {
    case "invokeTemporal":
      return "disputes.case.removed";
    case "invokeOpensearch":
      return "disputes.case.removed.ready-for-index";
    case "invokeDataWarehouse":
      return "disputes.case.removed.data-warehouse";
    case "invokeAgenticAI":
      return "disputes.case.removed.agentic";
  }
}

export type DisputeStreamImages = {
  newImage: Record<string, unknown>;
  oldImage?: Record<string, unknown>;
};

function unmarshallImages(record: NormalizedStreamRecord): DisputeStreamImages {
  const newImage = record.dynamodbNewImage
    ? unmarshall((record.dynamodbNewImage || {}) as Record<string, AttributeValue>)
    : {};
  const oldImage = record.dynamodbOldImage
    ? unmarshall((record.dynamodbOldImage || {}) as Record<string, AttributeValue>)
    : undefined;
  return { newImage, oldImage };
}

/** Unmarshall NewImage/OldImage once; pass through {@link publishDisputeStreamToEventBridge} to avoid duplicate work. */
export function getStreamImages(record: NormalizedStreamRecord): DisputeStreamImages {
  return unmarshallImages(record);
}

export function entityTypeFromImages(images: DisputeStreamImages): string {
  return (
    toStringValue(images.newImage.entityType) ||
    (images.oldImage ? toStringValue(images.oldImage.entityType) : "")
  );
}

/** Publish only when stream image entityType is DISPUTE (integration head rows). */
export function entityTypeFromStreamImages(record: NormalizedStreamRecord): string {
  return entityTypeFromImages(getStreamImages(record));
}

export function isDisputeEntityType(entityType: string): boolean {
  return entityType.trim().toUpperCase() === "DISPUTE";
}

export function isDisputeStreamEntity(record: NormalizedStreamRecord): boolean {
  return isDisputeEntityType(entityTypeFromStreamImages(record));
}

export function resolveDisputeStreamEventType(streamEventName: string): DisputeStreamEventType | null {
  const op = toStreamOperation(streamEventName);
  if (!op) return null;
  if (op === "INSERT") return "DISPUTE_INSERT";
  if (op === "MODIFY") return "DISPUTE_MODIFY";
  return "DISPUTE_REMOVE";
}

/**
 * Parse dispute id from SK `CASE#<accountNumber>#DISPUTE#<disputeId>` (suffixes like `#ATTACHMENT#…` allowed).
 * API `disputeNumber` is the accountNumber segment; this returns the id after `DISPUTE#`.
 */
export function parseDisputeIdFromSk(skRaw: string): string | null {
  const segs = skRaw.split("#").filter(Boolean);
  if (segs.length < 4 || segs[0]?.toUpperCase() !== "CASE" || segs[2]?.toUpperCase() !== "DISPUTE") {
    return null;
  }
  return segs[3] ?? null;
}

/** `accountNumber` in the item/SK is the API dispute number (`CASE#<accountNumber>#DISPUTE#…`). */
export function parseDisputeAccountNumberFromSk(skRaw: string): string | null {
  const segs = skRaw.split("#").filter(Boolean);
  if (segs.length < 3 || segs[0]?.toUpperCase() !== "CASE" || segs[2]?.toUpperCase() !== "DISPUTE") {
    return null;
  }
  return segs[1] ?? null;
}

function buildDetailPayload(
  record: NormalizedStreamRecord,
  disputeStreamEventType: DisputeStreamEventType,
  images: DisputeStreamImages
): DisputeCoreStreamDetail | null {
  const keys = unmarshall(
    (record.dynamodbKeys || {}) as Record<string, AttributeValue>
  );
  const { newImage, oldImage } = images;
  const skRaw = toStringValue(keys.SK);

  const caseId =
    toStringValue(newImage.caseId) ||
    (oldImage ? toStringValue(oldImage.caseId) : "") ||
    "";
  const accountId =
    toStringValue(newImage.accountId) ||
    (oldImage ? toStringValue(oldImage.accountId) : "") ||
    "";

  const disputeNumber =
    toStringValue(newImage.disputeNumber) ||
    toStringValue(newImage.accountNumber) ||
    (oldImage ? toStringValue(oldImage.disputeNumber) : "") ||
    (oldImage ? toStringValue(oldImage.accountNumber) : "") ||
    parseDisputeAccountNumberFromSk(skRaw) ||
    "";

  const disputeId =
    toStringValue(newImage.disputeId) ||
    (oldImage ? toStringValue(oldImage.disputeId) : "") ||
    parseDisputeIdFromSk(skRaw) ||
    "";

  const controlNumber =
    toStringValue(newImage.controlNumber) ||
    (oldImage ? toStringValue(oldImage.controlNumber) : "") ||
    "";

  const pk = toStringValue(keys.PK);
  const sk = toStringValue(keys.SK);

  return {
    sourceTable: disputeTableNameFromEnv(),
    eventName: String(record.eventName || "INSERT"),
    disputeStreamEventType: disputeStreamEventType,
    entityType: "DISPUTE",
    eventID: record.eventID,
    sequenceNumber: record.sequenceNumber,
    approximateCreationDateTime: record.approximateCreationDateTime,
    ...(caseId ? { caseId } : {}),
    ...(accountId ? { accountId } : {}),
    ...(disputeNumber ? { disputeNumber } : {}),
    ...(disputeId ? { disputeId } : {}),
    ...(controlNumber ? { controlNumber } : {}),
    ...(pk ? { pk } : {}),
    ...(sk ? { sk } : {}),
    keys,
    newImage,
    ...(oldImage !== undefined ? { oldImage } : {}),
  };
}

export type PublishDisputeStreamOptions = {
  /** When set (e.g. from the stream handler), skips a second image unmarshall. */
  images?: DisputeStreamImages;
};

/**
 * Publishes DisputeCore stream rows with entityType DISPUTE to EventBridge (disputes.case.* detail-types).
 */
export async function publishDisputeStreamToEventBridge(
  record: NormalizedStreamRecord,
  opts?: PublishDisputeStreamOptions
): Promise<void> {
  warnIfCustomEndpointMisconfigured();

  logDisputeEvent("dispute_publish_start", {
    ...streamRecordContext(record),
    eventBridgeEnabled: isDisputeEventBridgeEnabled(),
  });

  if (!isDisputeEventBridgeEnabled()) {
    logDisputeEvent("dispute_publish_skipped", {
      ...streamRecordContext(record),
      reason: "DISPUTE_CORE_EVENTBRIDGE_DISABLED",
      hint: "Set DISPUTE_CORE_EVENTBRIDGE_ENABLED=1",
    });
    return;
  }

  const images = opts?.images ?? getStreamImages(record);
  const entityType = entityTypeFromImages(images);
  if (!isDisputeEntityType(entityType)) {
    logDisputeEvent("dispute_publish_skipped", {
      ...streamRecordContext(record),
      reason: "entity_type_not_dispute",
      entityType: entityType || null,
    });
    return;
  }

  const op = toStreamOperation(record.eventName);
  if (!op) {
    logDisputeEvent("dispute_publish_skipped", {
      ...streamRecordContext(record),
      reason: "unknown_stream_event_name",
    });
    return;
  }

  const disputeStreamEventType = resolveDisputeStreamEventType(record.eventName || "");
  if (!disputeStreamEventType) {
    logDisputeEvent("dispute_publish_skipped", {
      ...streamRecordContext(record),
      reason: "unresolved_dispute_stream_event_type",
    });
    return;
  }

  const detail = buildDetailPayload(record, disputeStreamEventType, images);
  if (!detail) {
    logDisputeEvent("dispute_publish_skipped", {
      ...streamRecordContext(record),
      reason: "build_detail_payload_null",
      disputeStreamEventType,
    });
    return;
  }

  logDisputeEvent("dispute_detail_built", {
    ...streamRecordContext(record),
    disputeStreamEventType,
    caseId: detail.caseId ?? null,
    accountId: detail.accountId ?? null,
    disputeId: detail.disputeId ?? null,
    disputeNumber: detail.disputeNumber ?? null,
    pk: detail.keys?.PK ?? null,
    sk: detail.keys?.SK ?? null,
  });

  const detailJson = JSON.stringify(detail);
  if (Buffer.byteLength(detailJson, "utf8") > 240_000) {
    throw new Error(
      "EventBridge detail exceeds safe size (~256KB); trim payload or store blob in S3 and pass pointer"
    );
  }

  const flags = routingFlags();
  const source = process.env.DISPUTE_EVENTBRIDGE_SOURCE || "com.residentinterface.disputes";
  const eventBusName = disputesEventBusNameFromEnv();

  const appliedRules: { target: RoutingTarget; detailType: string }[] = [];
  const skippedRules: { target: RoutingTarget; reason: string }[] = [];

  const entries: {
    Source: string;
    DetailType: string;
    Detail: string;
    EventBusName?: string;
  }[] = [];

  for (const target of ROUTING_TARGETS) {
    if (!flags[target]) {
      skippedRules.push({ target, reason: "routing_flag_disabled" });
      logDisputeEvent("dispute_routing_rule_skipped", {
        ...streamRecordContext(record),
        target,
        reason: "routing_flag_disabled",
        envFlag: ROUTING_TARGET_ENV_FLAGS[target],
      });
      continue;
    }

    const detailType = disputeDetailTypeForTarget(op, target);
    appliedRules.push({ target, detailType });
    logDisputeEvent("dispute_routing_rule_applied", {
      ...streamRecordContext(record),
      target,
      detailType,
      streamOperation: op,
      disputeStreamEventType,
      caseId: detail.caseId ?? null,
      disputeNumber: detail.disputeNumber ?? null,
    });

    entries.push({
      Source: source,
      DetailType: detailType,
      Detail: detailJson,
      ...(eventBusName ? { EventBusName: eventBusName } : {}),
    });
  }

  logDisputeEvent("dispute_routing_rules_summary", {
    ...streamRecordContext(record),
    flags,
    appliedRules,
    skippedRules,
    entryCount: entries.length,
  });

  if (entries.length === 0) {
    logDisputeEvent("dispute_publish_skipped", {
      ...streamRecordContext(record),
      reason: "no_routing_rules_applied",
      flags,
      skippedRules,
      hint: "Enable at least one DISPUTE_CORE_INVOKE_* flag",
    });
    return;
  }

  const region = process.env.AWS_REGION || "us-east-1";
  const eventBus = eventBusName || "default";
  console.info(
    EB_LOG + " PutEvents sending",
    JSON.stringify({
      region,
      eventBus,
      source,
      entryCount: entries.length,
      detailTypes: entries.map((e) => e.DetailType),
      caseId: detail.caseId,
      disputeNumber: detail.disputeNumber,
      streamEventID: record.eventID,
      disputeStreamEventType,
    })
  );

  try {
    const res = await getEventBridgeClient().send(new PutEventsCommand({ Entries: entries }));
    const failed = (res.Entries || []).filter((e) => e.ErrorCode);
    if (failed.length > 0) {
      const first = failed[0];
      throw new Error("PutEvents failed: " + first.ErrorCode + " " + (first.ErrorMessage || ""));
    }
  } catch (err: unknown) {
    const e = err as { name?: string; message?: string };
    logDisputeEvent(
      "dispute_put_events_failed",
      {
        ...streamRecordContext(record),
        name: e.name,
        error: e.message,
        region,
        eventBus,
        entryCount: entries.length,
        detailTypes: entries.map((ent) => ent.DetailType),
        appliedRules,
      },
      "error"
    );
    throw err;
  }

  console.log(
    JSON.stringify({
      msg: "eventbridge_put_events_ok",
      stream: "dispute",
      disputeStreamEventType,
      streamOperation: op,
      caseId: detail.caseId,
      disputeNumber: detail.disputeNumber,
      eventBus,
      entryCount: entries.length,
      entries: entries.map((ent) => ({
        source: ent.Source,
        detailType: ent.DetailType,
        eventBusName: ent.EventBusName ?? "default",
        detailBytes: Buffer.byteLength(ent.Detail, "utf8"),
      })),
    })
  );
}
