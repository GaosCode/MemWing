"use strict";

class OpenClawToolSchemaError extends Error {
  constructor(field, message) {
    super(message);
    this.name = "OpenClawToolSchemaError";
    this.code = "schema_validation_failed";
    this.field = field;
  }
}

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
  const input = validateRuntimeScopeParams(params);
  const query = requireText(input.query, "query");
  const mode = optionalEnum(input.mode, "mode", ["current", "history"], options.modeDefault);
  return withoutUndefined({
    ...input,
    query,
    mode,
    limit: optionalPositiveInteger(input.limit, "limit", 20),
    cursor: optionalText(input.cursor, "cursor"),
    sort: optionalEnum(input.sort, "sort", ["relevance", "event_time", "updated_at"], "relevance"),
    min_score: optionalNonNegativeNumber(input.min_score, "min_score", 0)
  });
}

function validateNativeSearchParams(params) {
  const input = validateRuntimeScopeParams(params);
  const limit = optionalPositiveInteger(input.max_results, "max_results", 20);
  const canonical = validateSearchParams({
    ...input,
    limit,
    mode: input.mode || "current"
  }, { modeDefault: "current" });
  delete canonical.max_results;
  return canonical;
}

function validateMemoryIdParams(params, options) {
  const input = validateRuntimeScopeParams(params);
  const validated = {
    ...input,
    memory_id: requireText(input.memory_id, "memory_id")
  };
  if (options.includeEvidence) {
    validated.include_evidence = optionalBoolean(input.include_evidence, "include_evidence", false);
  }
  return withoutUndefined(validated);
}

function validateProjectContextParams(params) {
  const input = validateRuntimeScopeParams(params);
  return withoutUndefined({
    ...input,
    token_budget: optionalPositiveInteger(input.token_budget, "token_budget", undefined)
  });
}

function objectSchema(properties, required) {
  return {
    type: "object",
    additionalProperties: true,
    required,
    properties
  };
}

function runtimeScopeProperties() {
  return {
    agent_id: { type: "string", minLength: 1 },
    workspace_id: { type: "string", minLength: 1 },
    session_id: { type: "string", minLength: 1 },
    scope: {
      type: "object",
      additionalProperties: true,
      required: ["project_memory_space_id"],
      properties: {
        project_memory_space_id: { type: "string", minLength: 1 },
        group_id: { type: ["string", "null"], minLength: 1 },
        thread_id: { type: ["string", "null"], minLength: 1 },
        shared_group_id: { type: ["string", "null"], minLength: 1 }
      }
    }
  };
}

function validateRuntimeScopeParams(params) {
  const input = requireObject(params, "params");
  return withoutUndefined({
    ...input,
    agent_id: requireText(input.agent_id, "agent_id"),
    workspace_id: optionalText(input.workspace_id, "workspace_id"),
    session_id: optionalText(input.session_id, "session_id"),
    scope: validateScope(input.scope)
  });
}

function validateScope(scope) {
  const input = requireObject(scope, "scope");
  return withoutUndefined({
    ...input,
    project_memory_space_id: requireText(
      input.project_memory_space_id,
      "scope.project_memory_space_id"
    ),
    group_id: optionalText(input.group_id, "scope.group_id"),
    thread_id: optionalText(input.thread_id, "scope.thread_id"),
    shared_group_id: optionalText(input.shared_group_id, "scope.shared_group_id")
  });
}

function requireObject(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new OpenClawToolSchemaError(field, `${field} must be an object`);
  }
  return value;
}

function requireText(value, field) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new OpenClawToolSchemaError(field, `${field} is required`);
  }
  return value;
}

function optionalText(value, field) {
  if (value === undefined || value === null) {
    return undefined;
  }
  if (typeof value !== "string" || value.trim() === "") {
    throw new OpenClawToolSchemaError(field, `${field} must be text`);
  }
  return value;
}

function optionalPositiveInteger(value, field, defaultValue) {
  if (value === undefined || value === null) {
    return defaultValue;
  }
  if (!Number.isInteger(value) || value < 1) {
    throw new OpenClawToolSchemaError(field, `${field} must be a positive integer`);
  }
  return value;
}

function optionalNonNegativeNumber(value, field, defaultValue) {
  if (value === undefined || value === null) {
    return defaultValue;
  }
  if (typeof value !== "number" || Number.isNaN(value) || value < 0) {
    throw new OpenClawToolSchemaError(field, `${field} must be a non-negative number`);
  }
  return value;
}

function optionalBoolean(value, field, defaultValue) {
  if (value === undefined || value === null) {
    return defaultValue;
  }
  if (typeof value !== "boolean") {
    throw new OpenClawToolSchemaError(field, `${field} must be a boolean`);
  }
  return value;
}

function optionalEnum(value, field, allowed, defaultValue) {
  if (value === undefined || value === null) {
    return defaultValue;
  }
  if (!allowed.includes(value)) {
    throw new OpenClawToolSchemaError(field, `${field} is not supported`);
  }
  return value;
}

function withoutUndefined(value) {
  return Object.fromEntries(
    Object.entries(value).filter(([, entryValue]) => entryValue !== undefined)
  );
}

module.exports = {
  OpenClawToolSchemaError,
  toolParameters,
  validateMemoryIdParams,
  validateNativeSearchParams,
  validateProjectContextParams,
  validateSearchParams
};
