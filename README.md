# Alaid School — Display Preview

Static school management UI. Opens directly without login, a backend, or a database.
All displayed records are fictional examples. Navigation, searching, printing and CSV
export work; record-changing controls explain that this is a display-only preview.
There is no persistent storage. A Supabase reachability check runs on page load.

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

## Supabase connection

The frontend is configured for `https://wctkzldkyjvggxidvdxm.supabase.co`
using the project owner's publishable key. On startup it checks Supabase Auth
reachability without blocking the working preview. The CSP allows connections
only to this Supabase origin and the app itself.

This is connection configuration, not a complete database integration. School
records are still fictional display data and are not saved. Project-management
access was denied, so school tables, RLS, membership roles and the real data
forms have not been configured. Do not enable anonymous writes to get past this.
The next step requires the owner to grant project access to the Supabase plugin.
No database password or service-role key is included in this repository.
