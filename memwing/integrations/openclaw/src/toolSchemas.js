"use strict";

const {
  OpenClawToolSchemaError,
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
  withoutUndefined
} = require("./schemaPrimitives.js");

const SEARCH_FIELDS = ["query", "mode", "limit", "cursor", "sort", "min_score"];

function toolParameters(toolName) {
  if (toolName === "memwing_get_memory") {
    return objectSchema({
      memory_id: { type: "string", minLength: 1 },
      include_evidence: { type: "boolean" },
      ...runtimeScopeProperties()
    }, ["agent_id", "memory_id", "scope"]);
  }
  if (toolName === "memwing_explain_memory") {
    return objectSchema({
      memory_id: { type: "string", minLength: 1 },
      ...runtimeScopeProperties()
    }, ["agent_id", "memory_id", "scope"]);
  }
  if (toolName === "memwing_get_project_context") {
    return objectSchema({
      token_budget: { type: "integer", minimum: 1 },
      ...runtimeScopeProperties()
    }, ["agent_id", "scope"]);
  }
  return objectSchema({
    query: { type: "string", minLength: 1 },
    mode: { enum: ["current", "history"] },
    limit: { type: "integer", minimum: 1 },
    cursor: { type: ["string", "null"], minLength: 1 },
    sort: { enum: ["relevance", "event_time", "updated_at"] },
    min_score: { type: "number", minimum: 0 },
    ...runtimeScopeProperties()
  }, ["agent_id", "query", "scope"]);
}

function validateSearchParams(params, options) {
  const input = requireObject(params, "params");
  rejectUnknownFields(input, [...RUNTIME_SCOPE_FIELDS, ...SEARCH_FIELDS], "params");
  const runtime = validateRuntimeScopeParams(input);
  const query = requireText(input.query, "query");
  const mode = optionalEnum(input.mode, "mode", ["current", "history"], options.modeDefault);
  return withoutUndefined({
    ...runtime,
    query,
    mode,
    limit: optionalPositiveInteger(input.limit, "limit", 20),
    cursor: optionalText(input.cursor, "cursor"),
    sort: optionalEnum(input.sort, "sort", ["relevance", "event_time", "updated_at"], "relevance"),
    min_score: optionalNonNegativeNumber(input.min_score, "min_score", 0)
  });
}

function validateMemoryIdParams(params, options) {
  const input = requireObject(params, "params");
  const allowedFields = options.includeEvidence
    ? [...RUNTIME_SCOPE_FIELDS, "memory_id", "include_evidence"]
    : [...RUNTIME_SCOPE_FIELDS, "memory_id"];
  rejectUnknownFields(input, allowedFields, "params");
  const runtime = validateRuntimeScopeParams(input);
  const validated = {
    ...runtime,
    memory_id: requireText(input.memory_id, "memory_id")
  };
  if (options.includeEvidence) {
    validated.include_evidence = optionalBoolean(input.include_evidence, "include_evidence", false);
  }
  return withoutUndefined(validated);
}

function validateProjectContextParams(params) {
  const input = requireObject(params, "params");
  rejectUnknownFields(input, [...RUNTIME_SCOPE_FIELDS, "token_budget"], "params");
  const runtime = validateRuntimeScopeParams(input);
  return withoutUndefined({
    ...runtime,
    token_budget: optionalPositiveInteger(input.token_budget, "token_budget", undefined)
  });
}

module.exports = {
  OpenClawToolSchemaError,
  toolParameters,
  validateMemoryIdParams,
  validateProjectContextParams,
  validateSearchParams
};
