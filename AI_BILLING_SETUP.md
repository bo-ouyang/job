# AI Billing Setup

## 1) Enable switches

Set these env vars in `.env`:

```env
AI_ENABLED=true
AI_BILLING_ENABLED=true
AI_BILLING_REQUIRE_PRODUCT=true
AI_RATE_LIMIT_ENABLED=true
```

## 2) Configure prices in Admin

Path: `/admin` -> `AI service pricing` (label in UI may be Chinese)

Required `Product.code` values:

- `ai_career_advice` -> `/api/v1/analysis/ai/advice`
- `ai_career_compass` -> `/api/v1/analysis/career-compass`
- `ai_search_intent` -> `/api/v1/jobs/ai_search` and `/api/v1/jobs/test_ai_parse`
- `ai_resume_parse` -> `/api/v1/resume/parse`

If `AI_BILLING_REQUIRE_PRODUCT=true` and a code is missing/inactive, API returns `503`.

Admin startup now auto-creates missing AI pricing rows with default prices.

## 3) Rate limit defaults (per user per minute)

- `AI_RATE_LIMIT_CAREER_ADVICE_PER_MINUTE` (default `10`)
- `AI_RATE_LIMIT_CAREER_COMPASS_PER_MINUTE` (default `3`)
- `AI_RATE_LIMIT_AI_SEARCH_PER_MINUTE` (default `12`)
- `AI_RATE_LIMIT_RESUME_PARSE_PER_MINUTE` (default `5`)

## 4) Fallback prices (used only when product is missing and require flag is false)

- `AI_PRICE_CAREER_ADVICE` (default `0.5`)
- `AI_PRICE_CAREER_COMPASS` (default `2.0`)
- `AI_PRICE_AI_SEARCH` (default `0.3`)
- `AI_PRICE_RESUME_PARSE` (default `1.0`)

## 5) Skill noise filtering in Admin

Path: `/admin` -> `System Config` (label in UI may be Chinese)

Keys:

- `analysis_skill_noise_exact`: exact tags to exclude (JSON array or comma/newline separated text)
- `analysis_skill_noise_contains`: substring rules to exclude (JSON array or comma/newline separated text)

Examples:

- `analysis_skill_noise_exact`: `["other","others","n/a","none","unknown"]`
- `analysis_skill_noise_contains`: `["remote work","social insurance","housing fund"]`
