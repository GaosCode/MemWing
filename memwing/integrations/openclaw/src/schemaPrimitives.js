"use strict";

const RUNTIME_SCOPE_FIELDS = ["agent_id", "workspace_id", "session_id", "scope"];
const SCOPE_FIELDS = [
  "project_memory_space_id",
  "group_id",
  "thread_id",
  "shared_group_id"
];

class OpenClawToolSchemaError extends Error {
  constructor(field, message) {
    super(message);
    this.name = "OpenClawToolSchemaError";
    this.code = "schema_validation_failed";
    this.field = field;
  }
}

function objectSchema(properties, required) {
  return {
    type: "object",
    additionalProperties: false,
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
      additionalProperties: false,
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
    agent_id: requireText(input.agent_id, "agent_id"),
    workspace_id: optionalText(input.workspace_id, "workspace_id"),
    session_id: optionalText(input.session_id, "session_id"),
    scope: validateScope(input.scope)
  });
}

function validateScope(scope) {
  const input = requireObject(scope, "scope");
  rejectUnknownFields(input, SCOPE_FIELDS, "scope");
  return withoutUndefined({
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

function rejectUnknownFields(value, allowedFields, field) {
  for (const key of Object.keys(value)) {
    if (!allowedFields.includes(key)) {
      throw new OpenClawToolSchemaError(key, `${field}.${key} is not supported`);
    }
  }
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
};
