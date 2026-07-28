export function normalizeJobTags(value) {
  if (Array.isArray(value)) {
    return value
      .map((item) => String(item || "").trim())
      .filter(Boolean);
  }
  if (typeof value !== "string") return [];

  const text = value.trim();
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    if (parsed !== text) return normalizeJobTags(parsed);
  } catch {
    // Legacy records may store comma-separated tags instead of JSON.
  }
  return text
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatSalaryNumber(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount) || amount <= 0) return null;
  const inThousands = amount >= 1000 ? amount / 1000 : amount;
  return Number.isInteger(inThousands)
    ? String(inThousands)
    : String(Math.round(inThousands * 10) / 10);
}

export function formatJobSalary(job = {}) {
  const description = String(job.salary_desc || "").trim();
  if (description) return description;

  const minimum = formatSalaryNumber(job.salary_min);
  const maximum = formatSalaryNumber(job.salary_max);
  if (minimum && maximum) return `${minimum}-${maximum}K`;
  if (minimum) return `${minimum}K起`;
  if (maximum) return `最高${maximum}K`;
  return "薪资面议";
}
