import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  disputeDetailTypeForTarget,
  entityTypeFromStreamImages,
  envFlag,
  isDisputeStreamEntity,
  parseDisputeAccountNumberFromSk,
  parseDisputeIdFromSk,
  resolveDisputeStreamEventType,
} from "./eventBridgeDisputePublish";
import type { NormalizedStreamRecord } from "./streamProcessor";

function recordWithEntity(entityType: string, sk = "CASE#DN1#DISPUTE#"): NormalizedStreamRecord {
  return {
    eventName: "INSERT",
    dynamodbKeys: { SK: { S: sk } },
    dynamodbNewImage: {
      entityType: { S: entityType },
      caseId: { S: "case-1" },
    },
  };
}

describe("envFlag", () => {
  it("parses DISPUTE_CORE_EVENTBRIDGE_ENABLED case-insensitively", () => {
    process.env.DISPUTE_CORE_EVENTBRIDGE_ENABLED = "TRUE";
    assert.equal(envFlag("DISPUTE_CORE_EVENTBRIDGE_ENABLED", false), true);
    process.env.DISPUTE_CORE_EVENTBRIDGE_ENABLED = "False";
    assert.equal(envFlag("DISPUTE_CORE_EVENTBRIDGE_ENABLED", true), false);
    delete process.env.DISPUTE_CORE_EVENTBRIDGE_ENABLED;
  });
});

describe("isDisputeStreamEntity", () => {
  it("returns true when entityType is DISPUTE", () => {
    assert.equal(isDisputeStreamEntity(recordWithEntity("DISPUTE")), true);
    assert.equal(isDisputeStreamEntity(recordWithEntity("dispute")), true);
  });

  it("returns false for other entity types", () => {
    assert.equal(isDisputeStreamEntity(recordWithEntity("DISPUTE_FINETUNING")), false);
    assert.equal(
      isDisputeStreamEntity(
        recordWithEntity("", "CASE#DN1#DISPUTE#AI_ANALYSIS")
      ),
      false
    );
  });
});

describe("parseDisputeAccountNumberFromSk", () => {
  it("parses accountNumber after CASE#", () => {
    assert.equal(parseDisputeAccountNumberFromSk("CASE#1#DISPUTE#D1"), "1");
    assert.equal(parseDisputeAccountNumberFromSk("CASE#A1001#DISPUTE#D1#ATTACHMENT#doc-1"), "A1001");
  });

  it("returns null for non-dispute SK", () => {
    assert.equal(parseDisputeAccountNumberFromSk("MODEL#x#FINETUNING#id"), null);
  });
});

describe("parseDisputeIdFromSk", () => {
  it("parses dispute id after DISPUTE#", () => {
    assert.equal(parseDisputeIdFromSk("CASE#1#DISPUTE#D1"), "D1");
    assert.equal(parseDisputeIdFromSk("CASE#A1001#DISPUTE#D1#ATTACHMENT#doc-1"), "D1");
  });

  it("returns null when SK has no dispute id segment", () => {
    assert.equal(parseDisputeIdFromSk("CASE#1#DISPUTE"), null);
    assert.equal(parseDisputeIdFromSk("MODEL#x#FINETUNING#id"), null);
  });
});

describe("resolveDisputeStreamEventType", () => {
  it("maps stream event names", () => {
    assert.equal(resolveDisputeStreamEventType("INSERT"), "DISPUTE_INSERT");
    assert.equal(resolveDisputeStreamEventType("MODIFY"), "DISPUTE_MODIFY");
    assert.equal(resolveDisputeStreamEventType("REMOVE"), "DISPUTE_REMOVE");
  });
});

describe("disputeDetailTypeForTarget", () => {
  it("uses disputes.case.* detail-types", () => {
    assert.equal(disputeDetailTypeForTarget("INSERT", "invokeTemporal"), "disputes.case.created");
    assert.equal(
      disputeDetailTypeForTarget("INSERT", "invokeAgenticAI"),
      "disputes.case.created.agentic"
    );
    assert.equal(
      disputeDetailTypeForTarget("MODIFY", "invokeOpensearch"),
      "disputes.case.updated.ready-for-index"
    );
  });
});

describe("entityTypeFromStreamImages", () => {
  it("reads entityType from OldImage on REMOVE", () => {
    const rec: NormalizedStreamRecord = {
      eventName: "REMOVE",
      dynamodbOldImage: { entityType: { S: "DISPUTE" } },
    };
    assert.equal(entityTypeFromStreamImages(rec), "DISPUTE");
  });
});
