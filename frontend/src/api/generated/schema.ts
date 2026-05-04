export function requireRecord(input: unknown, field: string): Record<string, unknown> {
  if (input === null || typeof input !== "object" || Array.isArray(input)) {
    throw new Error(`${field} must be an object`);
  }
  return input as Record<string, unknown>;
}

export function requireText(input: unknown, field: string): string {
  if (typeof input !== "string" || input.trim().length === 0) {
    throw new Error(`${field} must be text`);
  }
  return input;
}

export function requireOptionalText(input: unknown, field: string): string | null {
  if (input === null) {
    return null;
  }
  return requireText(input, field);
}

export function requireTextArray(input: unknown, field: string): string[] {
  if (!Array.isArray(input) || !input.every((item) => typeof item === "string")) {
    throw new Error(`${field} must be a string array`);
  }
  return [...input];
}

export function requireInteger(input: unknown, field: string): number {
  if (typeof input !== "number" || !Number.isInteger(input)) {
    throw new Error(`${field} must be an integer`);
  }
  return input;
}

export function requireBoolean(input: unknown, field: string): boolean {
  if (typeof input !== "boolean") {
    throw new Error(`${field} must be boolean`);
  }
  return input;
}

export function requireExactFields(
  input: Record<string, unknown>,
  allowed: readonly string[],
  field: string,
): void {
  const allowedSet = new Set(allowed);
  for (const key of allowedSet) {
    if (!(key in input)) {
      throw new Error(`${field}.${key} is required`);
    }
  }
  for (const key of Object.keys(input)) {
    if (!allowedSet.has(key)) {
      throw new Error(`${field}.${key} is not supported`);
    }
  }
}
