# ts-dashboard — Aura repo dashboard (TypeScript)

A tiny dependency-free TypeScript program that prints a live dashboard of the
Aura AI repo and live site.

## Run it

```bash
# Option 1: compile with the TypeScript compiler
npx tsc dashboard.ts && node dashboard.js

# Option 2: newer Node.js (22.18+) runs .ts directly via type stripping
node dashboard.ts

# Option 3: Deno
deno run dashboard.ts
```

## What it does

- Fetches `https://api.github.com/repos/arshadnaib20/aura-ai`
- Prints repo name, description, language, stars, forks, open issues, last push
- Pings `https://arshadnaib20.pythonanywhere.com` and prints HTTP status + latency

No dependencies, no build config.
