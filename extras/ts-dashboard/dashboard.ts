// Aura AI — repo dashboard (TypeScript, zero dependencies).
// Usage:
//   npx tsc dashboard.ts && node dashboard.js
// or, on newer Node (22.18+ type stripping) or Deno:
//   node dashboard.ts   /   deno run dashboard.ts

interface GitHubRepo {
  full_name: string;
  description: string | null;
  language: string | null;
  stargazers_count: number;
  forks_count: number;
  open_issues_count: number;
  pushed_at: string;
  html_url: string;
}

const REPO_URL = "https://api.github.com/repos/arshadnaib20/aura-ai";
const SITE_URL = "https://arshadnaib20.pythonanywhere.com";

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url, {
    headers: { "User-Agent": "aura-dashboard", Accept: "application/vnd.github+json" },
  });
  if (!res.ok) throw new Error(`${url} -> HTTP ${res.status}`);
  return (await res.json()) as T;
}

function pad(label: string, value: string): string {
  return `${label.padEnd(16)}${value}`;
}

async function main(): Promise<void> {
  const started = Date.now();
  console.log("AURA AI \u2014 live dashboard");
  console.log("========================");

  const repo = await fetchJson<GitHubRepo>(REPO_URL);
  console.log(pad("repo", repo.full_name));
  console.log(pad("description", repo.description ?? "(none)"));
  console.log(pad("language", repo.language ?? "n/a"));
  console.log(pad("stars", String(repo.stargazers_count)));
  console.log(pad("forks", String(repo.forks_count)));
  console.log(pad("open issues", String(repo.open_issues_count)));
  console.log(pad("last pushed", repo.pushed_at));

  try {
    const res = await fetch(SITE_URL, { method: "GET" });
    console.log(pad("live site", `HTTP ${res.status} (${Date.now() - started}ms)`));
  } catch (e) {
    console.log(pad("live site", `unreachable (${(e as Error).name})`));
  }
}

main().catch((e: unknown) => {
  console.error("dashboard failed:", (e as Error).message);
  process.exit(1);
});
