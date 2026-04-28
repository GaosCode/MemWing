"use strict";

const {
  RUNTIME_SCOPE_FIELDS,
  objectSchema,
  optionalBoolean,
  optionalEnum,
  optionalNonNegativeNumber,
  optionalPositiveInteger,
  optionalText,
  rejectUnknownFields,
  requireObject,
  requireText,
  runtimeScopeProperties,
  validateRuntimeScopeParams,
  validateScope,
  withoutUndefined
} = require("./schemaPrimitives.js");

const NATIVE_SEARCH_FIELDS = ["query", "mode", "max_results", "min_score"];
const NATIVE_INDEX_FIELDS = ["agent_id", "workspace_id", "session_id", "force"];
const NATIVE_STATUS_FIELDS = [
  "agent_id",
  "workspace_id",
  "session_id",
  "project_memory_space_id",
  "scope",
  "deep"
];

function nativeToolParameters(toolName) {
  if (toolName === "memory_get") {
    return objectSchema({
      memory_id: { type: "string", minLength: 1 },
      include_evidence: { type: "boolean" },
      ...runtimeScopeProperties()
    }, ["agent_id", "memory_id", "scope"]);
  }
  if (toolName === "memory_index") {
    return objectSchema({
      agent_id: { type: "string", minLength: 1 },
      workspace_id: { type: "string", minLength: 1 },
      session_id: { type: "string", minLength: 1 },
      force: { type: "boolean" }
    }, []);
  }
  if (toolName === "memory_status") {
    return objectSchema({
      agent_id: { type: "string", minLength: 1 },
      workspace_id: { type: "string", minLength: 1 },
      session_id: { type: "string", minLength: 1 },
      project_memory_space_id: { type: "string", minLength: 1 },
      deep: { type: "boolean" },
      scope: runtimeScopeProperties().scope
    }, ["agent_id"]);
  }
  return objectSchema({
    query: { type: "string", minLength: 1 },
    mode: { enum: ["current", "history"] },
    max_results: { type: "integer", minimum: 1 },
    min_score: { type: "number", minimum: 0 },
    ...runtimeScopeProperties()
  }, ["agent_id", "query", "scope"]);
}

function validateNativeSearchParams(params) {
  const input = requireObject(params, "params");
  rejectUnknownFields(input, [...RUNTIME_SCOPE_FIELDS, ...NATIVE_SEARCH_FIELDS], "params");
  const runtime = validateRuntimeScopeParams(input);
  return withoutUndefined({
    ...runtime,
    query: requireText(input.query, "query"),
    limit: optionalPositiveInteger(input.max_results, "max_results", 20),
    mode: optionalEnum(input.mode, "mode", ["current", "history"], "current"),
    sort: "relevance",
    min_score: optionalNonNegativeNumber(input.min_score, "min_score", 0)
  });
}

function validateNativeGetParams(params) {
  const input = requireObject(params, "params");
  rejectUnknownFields(
    input,
    [...RUNTIME_SCOPE_FIELDS, "memory_id", "include_evidence"],
    "params"
  );
  const runtime = validateRuntimeScopeParams(input);
  return withoutUndefined({
    ...runtime,
    memory_id: requireText(input.memory_id, "memory_id"),
    include_evidence: optionalBoolean(input.include_evidence, "include_evidence", false)
  });
}

function validateNativeIndexParams(params) {
  const input = requireObject(params, "params");
  rejectUnknownFields(input, NATIVE_INDEX_FIELDS, "params");
  return withoutUndefined({
    agent_id: optionalText(input.agent_id, "agent_id"),
    workspace_id: optionalText(input.workspace_id, "workspace_id"),
    session_id: optionalText(input.session_id, "session_id"),
    force: optionalBoolean(input.force, "force", false)
  });
}

function validateNativeStatusParams(params) {
  const input = requireObject(params, "params");
  rejectUnknownFields(input, NATIVE_STATUS_FIELDS, "params");
  const scope = input.scope === undefined ? undefined : validateScope(input.scope);
  return withoutUndefined({
    agent_id: requireText(input.agent_id, "agent_id"),
    workspace_id: optionalText(input.workspace_id, "workspace_id"),
    session_id: optionalText(input.session_id, "session_id"),
    project_memory_space_id: optionalText(
      input.project_memory_space_id,
      "project_memory_space_id"
    ),
    scope,
    deep: optionalBoolean(input.deep, "deep", false)
  });
}

module.exports = {
  nativeToolParameters,
  validateNativeGetParams,
  validateNativeIndexParams,
  validateNativeSearchParams,
  validateNativeStatusParams
};
