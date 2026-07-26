# OpenRouter Free-Model Marker — Capability Fact

**Validated**: 2026-07-25 (live API call)  
**Endpoint**: `GET https://openrouter.ai/api/v1/models`  
**Planning set**: MO18  

## Free-model identification

Two independent markers exist for free models on OpenRouter:

1. **Model-ID suffix `:free`** — every free model carries the `:free` suffix in its `id` field. This is a consistent, versioned convention (OpenRouter docs describe variant suffixes like `:free`, `:thinking`).
2. **Zero pricing** — `pricing.prompt == "0"` AND `pricing.completion == "0"` for free models.

Both markers are present; the model-id-suffix filter (`include: ["*:free"]`) requires **zero fetcher code changes** because `_normalize_openai_models` already captures the `id` field as `model-id`, and `apply_model_filter` supports fnmatch glob patterns against `model-id`.

## Evidence sample (15 free models, limit=100, q=:free)

| model-id | pricing.prompt | pricing.completion | context_length |
| --- | --- | --- | --- |
| inclusionai/ling-3.0-flash:free | 0 | 0 | 262144 |
| poolside/laguna-s-2.1:free | 0 | 0 | 262144 |
| poolside/laguna-xs-2.1:free | 0 | 0 | 262144 |
| cohere/north-mini-code:free | 0 | 0 | 256000 |
| nvidia/nemotron-3.5-content-safety:free | 0 | 0 | 128000 |
| nvidia/nemotron-3-ultra-550b-a55b:free | 0 | 0 | 1000000 |
| nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free | 0 | 0 | 256000 |
| poolside/laguna-m.1:free | 0 | 0 | 262144 |
| google/gemma-4-26b-a4b-it:free | 0 | 0 | 262144 |
| google/gemma-4-31b-it:free | 0 | 0 | 262144 |
| nvidia/nemotron-3-super-120b-a12b:free | 0 | 0 | 262144 |
| nvidia/nemotron-3-nano-30b-a3b:free | 0 | 0 | 256000 |
| nvidia/nemotron-nano-12b-v2-vl:free | 0 | 0 | 128000 |
| nvidia/nemotron-nano-9b-v2:free | 0 | 0 | 128000 |
| openai/gpt-oss-20b:free | 0 | 0 | 131072 |

## Response shape (matches `_normalize_openai_models` expectations)

```json
{
  "data": [
    {
      "id": "anthropic/claude-opus-5-fast",
      "name": "Claude Opus 5 (Fast)",
      "context_length": 1000000,
      "pricing": {"prompt": "0.00001", "completion": "0.00005"},
      "architecture": {"modality": "text+image+file->text", ...},
      ...
    }
  ],
  "total_count": 345,
  "links": {"next": "/api/v1/models?offset=3&limit=3"}
}
```

**Conclusion**: The `:free` suffix filter (`include: ["*:free"]`) is the correct, zero-code-change approach. No fetcher extension needed for this item.
