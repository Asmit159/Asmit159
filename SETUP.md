# Setup

This turns your GitHub profile README into a self-updating "neofetch" card:
ASCII art from your avatar on the left, live GitHub stats on the right.

## 1. Create the special profile repo

GitHub renders a README as your profile page only if the repo is named
**exactly your username**. If you don't have it yet:

1. Create a new repo called `YOUR_USERNAME/YOUR_USERNAME`
2. Make it public
3. Copy every file from this project into it (keep the folder structure)

## 2. Edit `profile.yml`

Open `profile.yml` and fill in:

- `github_username` — your GitHub handle (required — everything else is derived from this)
- `system` / `languages` / `hobbies` / `contact` — whatever you want displayed;
  these are static, so change them any time by editing the file

## 3. Enable Actions permissions

Repo → **Settings → Actions → General → Workflow permissions** →
select **"Read and write permissions"**, then save. This lets the workflow
commit the regenerated README back to the repo.

## 4. Run it

- Push your edited `profile.yml` — the workflow triggers automatically, or
- Go to **Actions → Update README → Run workflow** to trigger it by hand

It also runs on its own once a day (see the `cron` schedule in
`.github/workflows/update-readme.yml`) so your stats stay fresh without
you doing anything.

## How it works

| Field | Source |
|---|---|
| ASCII avatar | rendered from your GitHub avatar via `ascii_magic` |
| Uptime | time since your GitHub account was created |
| Repos / Stars / Followers | GitHub REST API |
| Contributed repos | GitHub GraphQL API |
| Commits | GitHub commit search API (counts commits on default branches — an approximation, not exact) |
| Lines of code | shallow-clones your non-fork repos and sums `git log --numstat`; results are cached in `scripts/.loc_cache.json` so unchanged repos aren't re-cloned every run |
| OS / Host / Kernel / IDE / Languages / Hobbies / Contact | whatever you typed into `profile.yml` |

## Notes & tuning

- **Rate limits**: the built-in `GITHUB_TOKEN` gives you 5,000 API requests/hour and
  full clone bandwidth — plenty for a personal profile with well under a hundred repos.
- **Slow first run**: the very first run clones every repo to compute lines of code.
  Later runs only re-clone repos that changed, so they're much faster.
- **Skip LOC entirely**: if you'd rather not clone repos at all, delete the
  `compute_lines_of_code(...)` call in `scripts/update_readme.py` and drop that
  line from the rendered stats block.
- **Layout**: tweak `render_readme()` in `scripts/update_readme.py` to add/remove
  fields or change the formatting — it's just an f-string.
