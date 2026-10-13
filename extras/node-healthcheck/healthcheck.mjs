#!/usr/bin/env node
// Aura AI — live-site health check (Node.js, zero dependencies)
// Usage: node healthcheck.mjs

const SITE_URL = "https://arshadnaib20.pythonanywhere.com";
const REPO_URL = "https://api.github.com/repos/arshadnaib20/aura-ai";
const TIMEOUT_MS = 15_000;

async function fetchWithTimeout(url, options = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    return await fetch(url, { ...options, signal: ctrl.signal });
  } finally {
    clearTimeout(timer);
  }
}

function ok(label, detail) {
  console.log(`  \u2714 ${label}: ${detail}`);
}

function bad(label, detail) {
  console.log(`  \u2716 ${label}: ${detail}`);
}

console.log(`Aura AI health check \u2014 ${new Date().toISOString()}\n`);

// 1. Live site
try {
  const start = Date.now();
  const res = await fetchWithTimeout(SITE_URL, { redirect: "follow" });
  const ms = Date.now() - start;
  if (res.ok) ok("live site", `${SITE_URL} -> HTTP ${res.status} in ${ms}ms`);
  else bad("live site", `HTTP ${res.status} (${res.statusText}) in ${ms}ms`);
} catch (e) {
  bad("live site", `${SITE_URL} unreachable: ${e.name}`);
}

// 2. Repo info
try {
  const res = await fetchWithTimeout(REPO_URL, {
    headers: { "User-Agent": "aura-healthcheck", Accept: "application/vnd.github+json" },
  });
  if (res.ok) {
    const d = await res.json();
    ok("repo", `${d.full_name} (${d.language}) \u2022 ${d.stargazers_count} stars \u2022 last pushed ${d.pushed_at}`);
  } else {
    bad("repo", `HTTP ${res.status}`);
  }
} catch (e) {
  bad("repo", `GitHub API unreachable: ${e.name}`);
}
