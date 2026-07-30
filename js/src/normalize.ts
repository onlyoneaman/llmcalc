export const ALIASES: Readonly<Record<string, string>> = {
  "gpt-5.1-latest": "gpt-5.1"
};

export const PROVIDER_PREFIXES: ReadonlySet<string> = new Set([
  "openai",
  "anthropic",
  "google",
  "xai",
  "meta",
  "mistral"
]);

function splitOnce(value: string, separator: string): [string, string] | null {
  const index = value.indexOf(separator);
  if (index <= 0 || index === value.length - separator.length) {
    return null;
  }
  return [value.slice(0, index), value.slice(index + separator.length)];
}

export function normalizeModelName(model: string): string {
  let normalized = model.trim().toLowerCase();
  if (normalized.length === 0) {
    throw new Error("model must not be empty");
  }

  const colonParts = splitOnce(normalized, ":");
  if (colonParts !== null && PROVIDER_PREFIXES.has(colonParts[0])) {
    normalized = colonParts[1];
  }

  const slashParts = splitOnce(normalized, "/");
  if (slashParts !== null && PROVIDER_PREFIXES.has(slashParts[0])) {
    normalized = slashParts[1];
  }

  return ALIASES[normalized] ?? normalized;
}

export function resolveModelKey(model: string, availableKeys: Iterable<string>): string | null {
  const keyMap = new Map<string, string>();
  for (const key of availableKeys) {
    keyMap.set(key.toLowerCase(), key);
    const normalizedKey = normalizeModelName(key);
    if (!keyMap.has(normalizedKey)) {
      keyMap.set(normalizedKey, key);
    }
  }

  const candidates: string[] = [];
  const raw = model.trim().toLowerCase();
  if (raw.length > 0) {
    candidates.push(raw);
  }
  candidates.push(normalizeModelName(model));

  for (const candidate of candidates) {
    const direct = keyMap.get(candidate);
    if (direct !== undefined) {
      return direct;
    }
    const alias = ALIASES[candidate];
    if (alias !== undefined) {
      const aliased = keyMap.get(alias);
      if (aliased !== undefined) {
        return aliased;
      }
    }
  }

  return null;
}
