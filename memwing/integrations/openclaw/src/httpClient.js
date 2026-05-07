"use strict";

function createMemWingHttpClient(options = {}) {
  const baseUrl = resolveMemWingBaseUrl(options);
  return {
    ingest(params) {
      return postJson(baseUrl, "/v1/openclaw/events/ingest", params);
    },
    observeHook(hookName, params) {
      return postJson(baseUrl, `/v1/openclaw/hooks/${encodeURIComponent(hookName)}`, {
        ...params,
        hook_name: hookName
      });
    },
    assemble(params) {
      return postJson(baseUrl, "/v1/openclaw/context/assemble", params);
    },
    afterTurn(params) {
      return postJson(baseUrl, "/v1/openclaw/events/after-turn", params);
    },
    searchMemory(params) {
      return postJson(baseUrl, "/v1/memwing/tools/search-memory", params);
    },
    getMemory(params) {
      return postJson(baseUrl, "/v1/memwing/tools/get-memory", params);
    },
    explainMemory(params) {
      return postJson(baseUrl, "/v1/memwing/tools/explain-memory", params);
    },
    searchSources(params) {
      return postJson(baseUrl, "/v1/memwing/tools/search-sources", params);
    },
    getProjectContext(params) {
      return postJson(baseUrl, "/v1/memwing/tools/project-context", params);
    },
    indexMemory(params) {
      return postJson(baseUrl, "/v1/openclaw/native/memory-index", params);
    },
    status(params) {
      return postJson(baseUrl, "/v1/openclaw/native/memory-status", params);
    },
    nextOpenClawPushCard(params) {
      return postJson(
        baseUrl,
        `/v1/openclaw/push-candidates/next${scopeQuery(params && params.scope)}`,
        params
      );
    },
    ackOpenClawPushCard(candidateId, params) {
      return postJson(
        baseUrl,
        `/v1/openclaw/push-candidates/${encodeURIComponent(candidateId)}/ack${scopeQuery(params && params.scope)}`,
        params
      );
    }
  };
}

function resolveMemWingBaseUrl(options) {
  const value = options.memwingBaseUrl || (options.config && options.config.memwingBaseUrl);
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error("memwingBaseUrl is required when no explicit MemWing client is provided");
  }
  return value.replace(/\/+$/, "");
}

async function postJson(baseUrl, path, payload) {
  if (typeof fetch !== "function") {
    throw new Error("global fetch is required for MemWing HTTP client");
  }
  const response = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: {
      "content-type": "application/json"
    },
    body: JSON.stringify(payload || {})
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const code = body && body.code ? body.code : "memwing_http_error";
    const message = body && body.message ? body.message : `MemWing HTTP ${response.status}`;
    const error = new Error(message);
    error.code = code;
    error.status = response.status;
    throw error;
  }
  return body;
}

function scopeQuery(scope) {
  if (!scope || typeof scope !== "object" || Array.isArray(scope)) {
    return "";
  }
  const query = new URLSearchParams();
  for (const key of ["project_memory_space_id", "group_id", "thread_id", "shared_group_id"]) {
    const value = scope[key];
    if (typeof value === "string" && value.trim() !== "") {
      query.set(key, value);
    }
  }
  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

module.exports = {
  createMemWingHttpClient
};
