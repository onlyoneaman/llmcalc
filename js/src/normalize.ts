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

export function normalizeModelName(model: string): string {
  let normalized = model.trim().toLowerCase();
  if (normalized.length === 0) {
    throw new Error("model must not be empty");
  }

  if (normalized.includes(":")) {
    const [provider, suffix] = normalized.split(":", 2);
    if (provider && suffix) {
      normalized = suffix;
    }
  }

  if (normalized.includes("/")) {
    const [provider, suffix] = normalized.split("/", 2);
    if (provider && suffix && PROVIDER_PREFIXES.has(provider)) {
      normalized = suffix;
    }
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
