export const TEXT_INPUT_MESSAGE =
  "llmcalc takes token counts, not text. Pass integer input/output token counts, " +
  "or the provider's usage object (for example response.usage). llmcalc does not " +
  "tokenize strings or message lists.";

const INPUT_KEYS = ["input_tokens", "prompt_tokens", "inputTokens", "promptTokens"] as const;
const OUTPUT_KEYS = [
  "output_tokens",
  "completion_tokens",
  "outputTokens",
  "completionTokens"
] as const;
const GEMINI_INPUT_KEYS = ["prompt_token_count", "promptTokenCount"] as const;
const GEMINI_OUTPUT_KEYS = [
  "candidates_token_count",
  "candidatesTokenCount",
  "response_token_count",
  "responseTokenCount"
] as const;
const GEMINI_CACHE_KEYS = ["cached_content_token_count", "cachedContentTokenCount"] as const;
const GEMINI_REASONING_KEYS = ["thoughts_token_count", "thoughtsTokenCount"] as const;
const GEMINI_TOOL_USE_KEYS = [
  "tool_use_prompt_token_count",
  "toolUsePromptTokenCount"
] as const;
const GEMINI_TOTAL_KEYS = ["total_token_count", "totalTokenCount"] as const;
const PROMPT_DETAIL_KEYS = [
  "prompt_tokens_details",
  "promptTokensDetails",
  "input_tokens_details"
] as const;
const COMPLETION_DETAIL_KEYS = [
  "completion_tokens_details",
  "completionTokensDetails",
  "output_tokens_details",
  "candidates_tokens_details",
  "candidatesTokensDetails",
  "response_tokens_details",
  "responseTokensDetails"
] as const;
const CACHE_READ_KEYS = ["cache_read_input_tokens", "cacheReadInputTokens"] as const;
const CACHE_CREATION_KEYS = [
  "cache_creation_input_tokens",
  "cacheCreationInputTokens",
  "cache_write_input_tokens",
  "cacheWriteInputTokens"
] as const;
const CACHED_SUBSET_KEYS = ["cached_tokens", "cachedTokens"] as const;
const CACHE_WRITE_SUBSET_KEYS = ["cache_write_tokens", "cacheWriteTokens"] as const;
const REASONING_KEYS = [
  "reasoning_tokens",
  "reasoningTokens",
  "thinking_tokens",
  "thinkingTokens"
] as const;
const CACHE_CREATION_DETAIL_KEYS = ["cache_creation", "cacheCreation"] as const;
const FIVE_MINUTE_CACHE_KEYS = ["ephemeral_5m_input_tokens", "ephemeral5mInputTokens"] as const;
const ONE_HOUR_CACHE_KEYS = ["ephemeral_1h_input_tokens", "ephemeral1hInputTokens"] as const;
const BEDROCK_CACHE_DETAIL_KEYS = ["cache_details", "cacheDetails"] as const;
const BEDROCK_DETAIL_TOKEN_KEYS = ["input_tokens", "inputTokens"] as const;
const SERVICE_TIER_KEYS = ["service_tier", "serviceTier", "traffic_type", "trafficType"] as const;
const STANDARD_SERVICE_TIERS = new Set([
  "0",
  "default",
  "standard",
  "standard_only",
  "on_demand",
  "service_tier_unspecified",
  "unspecified",
  "traffic_type_unspecified"
]);
export interface NormalizedUsage {
  inputTokens: number;
  outputTokens: number;
  cachedTokens: number;
  cacheCreationTokens: number;
  reasoningTokens: number;
  processingMode: string | null;
  cacheCreationTokens1h: number;
  cacheCreationAudioTokens: number;
  cachedAudioTokens: number;
  cachedImageTokens: number;
  inputAudioTokens: number;
  outputAudioTokens: number;
  inputImageTokens: number;
  outputImageTokens: number;
  queryCount: number;
  webSearchRequests: number;
  mapsGroundingRequests: number;
}

export function validateTokenCount(value: number, fieldName: string): void {
  if (typeof value !== "number" || !Number.isSafeInteger(value)) {
    throw new Error(`${fieldName} must be an integer, got ${typeof value}`);
  }
  if (value < 0) {
    throw new Error(`${fieldName} must be non-negative`);
  }
}

function coerceTokenValue(value: unknown, fieldName: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value)) {
    throw new Error(`${fieldName} must be an integer, got ${typeof value}`);
  }
  return value;
}

function valueFromMapping(
  usage: Record<string, unknown>,
  keyOptions: readonly string[],
  fieldName: string
): number | null {
  for (const key of keyOptions) {
    if (key in usage && usage[key] !== null && usage[key] !== undefined) {
      return coerceTokenValue(usage[key], fieldName);
    }
  }
  return null;
}

function nestedToken(
  usage: Record<string, unknown>,
  containerKeys: readonly string[],
  names: readonly string[]
): number {
  for (const containerKey of containerKeys) {
    const container = usage[containerKey];
    if (typeof container !== "object" || container === null) {
      continue;
    }
    const value = valueFromMapping(container as Record<string, unknown>, names, containerKey);
    if (value !== null) {
      return value;
    }
  }
  return 0;
}

function rawValue(usage: Record<string, unknown>, names: readonly string[]): unknown {
  for (const name of names) {
    const value = usage[name];
    if (value !== null && value !== undefined) {
      return value;
    }
  }
  return null;
}

export function getUsageTokens(usage: unknown): [number, number, number, number, number] {
  if (typeof usage === "string" || Array.isArray(usage)) {
    throw new Error(TEXT_INPUT_MESSAGE);
  }
  if (typeof usage !== "object" || usage === null) {
    throw new Error("usage must provide input/prompt tokens and output/completion tokens");
  }

  const dictUsage = usage as Record<string, unknown>;
  if ("messages" in dictUsage) {
    throw new Error(TEXT_INPUT_MESSAGE);
  }

  const geminiInput = valueFromMapping(dictUsage, GEMINI_INPUT_KEYS, "promptTokenCount");
  if (geminiInput !== null) {
    const geminiOutput = valueFromMapping(
      dictUsage,
      GEMINI_OUTPUT_KEYS,
      "candidatesTokenCount"
    ) ?? 0;
    const cached = valueFromMapping(dictUsage, GEMINI_CACHE_KEYS, "cachedContentTokenCount") ?? 0;
    const reasoning = valueFromMapping(dictUsage, GEMINI_REASONING_KEYS, "thoughtsTokenCount") ?? 0;
    const toolUse = valueFromMapping(
      dictUsage,
      GEMINI_TOOL_USE_KEYS,
      "toolUsePromptTokenCount"
    ) ?? 0;
    const total = valueFromMapping(dictUsage, GEMINI_TOTAL_KEYS, "totalTokenCount");
    validateTokenCount(geminiInput, "promptTokenCount");
    validateTokenCount(geminiOutput, "candidatesTokenCount");
    validateTokenCount(cached, "cachedContentTokenCount");
    validateTokenCount(reasoning, "thoughtsTokenCount");
    validateTokenCount(toolUse, "toolUsePromptTokenCount");
    if (total !== null) {
      validateTokenCount(total, "totalTokenCount");
    }
    if (cached > geminiInput) {
      throw new Error("cachedContentTokenCount must not exceed promptTokenCount");
    }

    const outputTotal = geminiOutput + reasoning;
    const totalWithoutTool = geminiInput + outputTotal;
    validateTokenCount(outputTotal, "outputTokens");
    validateTokenCount(totalWithoutTool, "totalTokenCount");

    if (toolUse === 0) {
      if (total !== null && total !== totalWithoutTool) {
        throw new Error("totalTokenCount is inconsistent with Gemini token details");
      }
      return [geminiInput, outputTotal, cached, 0, reasoning];
    }
    if (total === null) {
      throw new Error(
        "totalTokenCount is required to determine whether toolUsePromptTokenCount is additive"
      );
    }
    if (total === totalWithoutTool) {
      return [geminiInput, outputTotal, cached, 0, reasoning];
    }
    if (total === totalWithoutTool + toolUse) {
      const inputTotal = geminiInput + toolUse;
      validateTokenCount(inputTotal, "inputTokens");
      return [inputTotal, outputTotal, cached, 0, reasoning];
    }
    throw new Error("totalTokenCount is inconsistent with Gemini token details");
  }

  let inputTokens = valueFromMapping(dictUsage, INPUT_KEYS, "inputTokens");
  const outputTokens = valueFromMapping(dictUsage, OUTPUT_KEYS, "outputTokens");
  if (inputTokens === null || outputTokens === null) {
    throw new Error("usage must provide input/prompt tokens and output/completion tokens");
  }

  validateTokenCount(inputTokens, "inputTokens");
  validateTokenCount(outputTokens, "outputTokens");
  const additiveRead = valueFromMapping(dictUsage, CACHE_READ_KEYS, "cacheReadInputTokens");
  const additiveCreation = valueFromMapping(
    dictUsage,
    CACHE_CREATION_KEYS,
    "cacheCreationInputTokens"
  );

  let cached: number;
  let creation: number;
  if (additiveRead !== null || additiveCreation !== null) {
    cached = additiveRead ?? 0;
    creation = additiveCreation ?? 0;
    validateTokenCount(cached, "cacheReadInputTokens");
    validateTokenCount(creation, "cacheCreationInputTokens");
    inputTokens += cached + creation;
    validateTokenCount(inputTokens, "inputTokens");
  } else {
    cached = nestedToken(dictUsage, PROMPT_DETAIL_KEYS, CACHED_SUBSET_KEYS);
    creation = nestedToken(dictUsage, PROMPT_DETAIL_KEYS, CACHE_WRITE_SUBSET_KEYS);
  }

  const reasoning = nestedToken(dictUsage, COMPLETION_DETAIL_KEYS, REASONING_KEYS);
  return [inputTokens, outputTokens, cached, creation, reasoning];
}

function processingMode(usage: Record<string, unknown>): string | null {
  const tier = rawValue(usage, SERVICE_TIER_KEYS);
  if (tier === null) {
    return null;
  }
  const normalized = String(tier).trim().toLowerCase().replaceAll("-", "_");
  if (
    STANDARD_SERVICE_TIERS.has(normalized) ||
    normalized === "auto" ||
    normalized === "provisioned_throughput"
  ) {
    return "standard";
  }
  if (normalized === "priority" || normalized === "fast" || normalized === "on_demand_priority") {
    return "priority";
  }
  if (normalized === "flex" || normalized === "on_demand_flex") {
    return "flex";
  }
  if (normalized === "batch" || normalized === "batches") {
    return "batch";
  }
  throw new Error(`service tier ${String(tier)} is not supported`);
}

function firstDetails(
  usage: Record<string, unknown>,
  keys: readonly string[]
): unknown {
  for (const key of keys) {
    const details = usage[key];
    if (details !== null && details !== undefined) {
      return details;
    }
  }
  return null;
}

function modalityCounts(details: unknown, fieldName: string): [number, number] {
  if (details === null || details === undefined) {
    return [0, 0];
  }
  if (Array.isArray(details)) {
    let audio = 0;
    let image = 0;
    for (const item of details) {
      if (typeof item !== "object" || item === null || Array.isArray(item)) {
        continue;
      }
      const record = item as Record<string, unknown>;
      const modality = rawValue(record, ["modality"]);
      const tokens = valueFromMapping(record, ["token_count", "tokenCount"], fieldName);
      if (modality === null || tokens === null) {
        continue;
      }
      const normalized = String(modality).trim().toLowerCase();
      if (normalized === "audio") {
        audio += tokens;
      } else if (normalized === "image" || normalized === "document") {
        image += tokens;
      } else if (normalized !== "text" && normalized !== "modality_unspecified" && tokens > 0) {
        throw new Error(`unsupported token modality: ${normalized}`);
      }
    }
    validateTokenCount(audio, `${fieldName}.audioTokens`);
    validateTokenCount(image, `${fieldName}.imageTokens`);
    return [audio, image];
  }
  if (typeof details !== "object") {
    return [0, 0];
  }
  const record = details as Record<string, unknown>;
  const audio = valueFromMapping(record, ["audio_tokens", "audioTokens"], `${fieldName}.audioTokens`) ?? 0;
  const image = valueFromMapping(record, ["image_tokens", "imageTokens"], `${fieldName}.imageTokens`) ?? 0;
  const video = valueFromMapping(record, ["video_tokens", "videoTokens"], `${fieldName}.videoTokens`) ?? 0;
  if (video > 0) {
    throw new Error("video token pricing is not supported");
  }
  return [audio, image];
}

function cacheDurationCounts(usage: Record<string, unknown>): [number, number] {
  const fiveMinute = nestedToken(usage, CACHE_CREATION_DETAIL_KEYS, FIVE_MINUTE_CACHE_KEYS);
  let oneHour = nestedToken(usage, CACHE_CREATION_DETAIL_KEYS, ONE_HOUR_CACHE_KEYS);
  let detailTotal = fiveMinute + oneHour;
  const details = rawValue(usage, BEDROCK_CACHE_DETAIL_KEYS);
  if (Array.isArray(details)) {
    for (const item of details) {
      if (typeof item !== "object" || item === null || Array.isArray(item)) {
        continue;
      }
      const record = item as Record<string, unknown>;
      const tokens = valueFromMapping(record, BEDROCK_DETAIL_TOKEN_KEYS, "cacheDetails.inputTokens");
      if (tokens === null) {
        continue;
      }
      detailTotal += tokens;
      if (String(rawValue(record, ["ttl"])).trim().toLowerCase() === "1h") {
        oneHour += tokens;
      }
    }
  }
  validateTokenCount(detailTotal, "cacheDetails.inputTokens");
  validateTokenCount(oneHour, "cacheCreationTokens1h");
  return [detailTotal, oneHour];
}

function usageCounter(
  usage: Record<string, unknown>,
  names: readonly string[],
  fieldName: string
): number {
  const direct = valueFromMapping(usage, names, fieldName);
  if (direct !== null) {
    return direct;
  }
  const promptDetails = firstDetails(usage, PROMPT_DETAIL_KEYS);
  if (typeof promptDetails === "object" && promptDetails !== null && !Array.isArray(promptDetails)) {
    return valueFromMapping(promptDetails as Record<string, unknown>, names, fieldName) ?? 0;
  }
  return 0;
}

export function normalizeUsage(usage: unknown): NormalizedUsage {
  const [baseInput, outputTokens, cachedTokens, baseCreation, reasoningTokens] =
    getUsageTokens(usage);
  const dictUsage = usage as Record<string, unknown>;
  const promptDetails = firstDetails(dictUsage, PROMPT_DETAIL_KEYS);
  const completionDetails = firstDetails(dictUsage, COMPLETION_DETAIL_KEYS);
  const [inputAudioTokens, inputImageTokens] = modalityCounts(
    promptDetails,
    "promptTokensDetails"
  );
  const [outputAudioTokens, outputImageTokens] = modalityCounts(
    completionDetails,
    "completionTokensDetails"
  );

  let cacheDetails = firstDetails(dictUsage, ["cache_tokens_details", "cacheTokensDetails"]);
  if (
    cacheDetails === null &&
    typeof promptDetails === "object" &&
    promptDetails !== null &&
    !Array.isArray(promptDetails)
  ) {
    cacheDetails = rawValue(
      promptDetails as Record<string, unknown>,
      ["cached_tokens_details", "cachedTokensDetails"]
    );
  }
  const [cachedAudioTokens, cachedImageTokens] = modalityCounts(
    cacheDetails,
    "cacheTokensDetails"
  );

  const [detailTotal, cacheCreationTokens1h] = cacheDurationCounts(dictUsage);
  let inputTokens = baseInput;
  let cacheCreationTokens = baseCreation;
  if (detailTotal > 0) {
    if (cacheCreationTokens > 0 && detailTotal !== cacheCreationTokens) {
      throw new Error("cache duration token details must sum to cacheCreationInputTokens");
    }
    if (cacheCreationTokens === 0) {
      cacheCreationTokens = detailTotal;
      inputTokens += detailTotal;
      validateTokenCount(inputTokens, "inputTokens");
    }
  }
  if (cacheCreationTokens1h > cacheCreationTokens) {
    throw new Error("1-hour cache tokens must not exceed cache creation tokens");
  }

  let webSearchRequests = usageCounter(
    dictUsage,
    ["web_search_requests", "webSearchRequests"],
    "webSearchRequests"
  );
  const serverToolUse = rawValue(dictUsage, ["server_tool_use", "serverToolUse"]);
  if (
    webSearchRequests === 0 &&
    typeof serverToolUse === "object" &&
    serverToolUse !== null &&
    !Array.isArray(serverToolUse)
  ) {
    webSearchRequests = valueFromMapping(
      serverToolUse as Record<string, unknown>,
      ["web_search_requests", "webSearchRequests"],
      "serverToolUse.webSearchRequests"
    ) ?? 0;
  }
  const serverSideToolUse = rawValue(dictUsage, [
    "server_side_tool_usage_details",
    "serverSideToolUsageDetails"
  ]);
  if (
    webSearchRequests === 0 &&
    typeof serverSideToolUse === "object" &&
    serverSideToolUse !== null &&
    !Array.isArray(serverSideToolUse)
  ) {
    webSearchRequests = valueFromMapping(
      serverSideToolUse as Record<string, unknown>,
      ["web_search_calls", "webSearchCalls"],
      "serverSideToolUsageDetails.webSearchCalls"
    ) ?? 0;
  }

  return {
    inputTokens,
    outputTokens,
    cachedTokens,
    cacheCreationTokens,
    reasoningTokens,
    processingMode: processingMode(dictUsage),
    cacheCreationTokens1h,
    cacheCreationAudioTokens: usageCounter(
      dictUsage,
      ["cache_creation_audio_tokens", "cacheCreationAudioTokens"],
      "cacheCreationAudioTokens"
    ),
    cachedAudioTokens,
    cachedImageTokens,
    inputAudioTokens,
    outputAudioTokens,
    inputImageTokens,
    outputImageTokens,
    queryCount: usageCounter(
      dictUsage,
      ["query_count", "queryCount", "search_units", "searchUnits"],
      "queryCount"
    ),
    webSearchRequests,
    mapsGroundingRequests: usageCounter(
      dictUsage,
      ["google_maps_grounding_requests", "googleMapsGroundingRequests"],
      "googleMapsGroundingRequests"
    )
  };
}
