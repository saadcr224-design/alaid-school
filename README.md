# Alaid School — Display Preview

Static school management UI. Opens directly without login, a backend, or a database.
All displayed records are fictional examples. Navigation, searching, printing and CSV
export work; record-changing controls explain that this is a display-only preview.
There is no persistent storage and no API request on page load.

## Vercel

GitHub main → Vercel automatic deployment. The explicit static-only vercel.json
publishes public/index.html, public/app.js and public/style.css. Keep the project
Root Directory at the repository root.

Primary URL: https://alaid-school.vercel.app/

## Run locally

    python -m http.server 8000 --directory public

Open http://localhost:8000. No dependencies or credentials are needed.

Backend code and database dependencies have been removed from the current branch.
Earlier Git commits still contain the previous implementation. No external database
resources were deleted by this change.
