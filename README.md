# job-watch

A small CLI you run once a week. It checks engineering firm and public agency
career sites and tells you only what's **new** since the last run. It's tuned
for entry-level civil/transportation roles (EIT, Engineer I/II, etc.) in the
Las Vegas metro.

```
========================================================================
job-watch digest — 2026-10-05
========================================================================

NEW POSTINGS (2)

Public agencies
---------------
  • Assistant/Associate Engineer
      Clark County — Las Vegas, NV
      https://www.governmentjobs.com/careers/clarkcounty/jobs/4004033/...

National firms
--------------
  • Transportation Engineer I
      HNTB — Las Vegas, NV
      https://hntb.wd5.myworkdayjobs.com/HNTB_Careers/job/...

CLOSED SINCE LAST RUN (1)
  • Civil EIT — Kimley-Horn (closed 2026-10-05)

Checked 18 site(s), 1432 posting(s) total.

SITES THAT FAILED (1)
  ✗ USAJOBS (0810 Civil Engineering) [usajobs-0810]: ConfigError: USAJOBS_API_KEY ...
```

## Setup

You need Python 3.11+.

**With uv (recommended)**

```bash
uv sync                      # creates .venv and installs everything
cp .env.example .env         # then fill in the values
uv run job-watch check-config
uv run job-watch run
```

**With a plain venv**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .             # installs the `job-watch` command
cp .env.example .env
job-watch run
```

**Optional: Playwright** (only needed for employers with `render_js: true`):

```bash
uv sync --extra browser && uv run playwright install chromium
# or: pip install playwright && playwright install chromium
```

If Playwright isn't installed, those employers show up under "sites that
failed" and every other employer still runs. **In the shipped config, no
employer needs Playwright.** Every entry has a JSON API, an RSS feed or
server-rendered HTML. The one to watch is `lochsa`: its site looks like Wix.
If `job-watch probe lochsa` finds 0 postings, set `render_js: true` on it.

### Environment variables (`.env`)

| Variable | Needed for |
|---|---|
| `USAJOBS_API_KEY`, `USAJOBS_EMAIL` | the USAJOBS entry. Get a free key at <https://developer.usajobs.gov/apirequest/> |
| `JOB_WATCH_SMTP_HOST`, `_PORT`, `_USER`, `_PASSWORD`, `_FROM`, `_TO` | `--email`. For Gmail use `smtp.gmail.com`, port `587`, and an [App Password](https://myaccount.google.com/apppasswords). `_TO` can be a comma-separated list |
| `JOB_WATCH_SMTP_SSL=1` | use implicit SSL (port 465) instead of STARTTLS |
| `JOB_WATCH_CONFIG` | path to config.yaml if you don't run from the repo directory |

`.env` is read from the config file's directory and from the current
directory. It's git-ignored.

## Usage

```bash
job-watch run                      # fetch everything, print new postings
job-watch run --email              # ...and email the digest
job-watch run --json               # machine-readable digest
job-watch run --only hntb clark-county
job-watch run --dry-run            # don't mark anything as reported
job-watch probe hntb --verbose     # fetch one employer; show every posting and why it passed or failed
job-watch probe --all              # smoke-test every employer (no DB writes)
job-watch list                     # open matching postings in the DB
job-watch list --status closed
job-watch check-config             # validate config.yaml
```

Exit code: `run` returns 0 even if some sites failed; add `--fail-on-error`
if you want a non-zero exit for cron alerts. It returns 2 if `--email` was
requested and sending failed. In that case nothing is marked as reported, so
the same postings show up again next time.

## How it works

1. **Fetch.** Each employer in `config.yaml` has a `type` that picks a fetcher
   module in `src/job_watch/fetchers/`. Every fetcher returns the same
   `Posting` record: firm, title, location, url, source, and the ATS's own
   job id when it has one.
2. **Filter.** `filters.py` applies three checks, all driven by keyword lists
   in `config.yaml`:
   - **level**: the title has an include term (EIT, Engineer I, II, junior, …)
     and no exclude term (senior, manager, lead, III, IV, …).
   - **discipline**: the posting is civil/transportation. It passes if a term
     like civil/transportation/traffic appears in the title or department.
     Otherwise the title must contain "engineer" and none of the excluded
     disciplines (software, electrical, …).
   - **location**: the location names Las Vegas, Henderson, North Las Vegas,
     etc. If a state is named, it must be NV. Remote and hybrid postings are
     accepted. Vague locations ("3 Locations", blank) are kept and flagged
     `[location unverified]`.

   Matching is case-insensitive and whole-word, so "Engineer I" doesn't match
   "Engineer II" and "lead" doesn't match "leadership".
3. **Diff.** `store.py` saves every fetched posting in SQLite (default
   `~/.local/share/job-watch/jobs.db`), whether it matched or not. Rows are
   never deleted.
   - **New** means it matches and hasn't been reported yet.
   - **Closed** means it was missing from a *successful* fetch of its
     employer. It gets a `closed_date`. A site that errors never closes
     anything.
   - **Reopened** means a closed posting came back. Its `closed_date` is
     cleared.
   - Because everything is stored, **loosening a keyword later brings up
     matching older postings once**.
4. **Report.** The terminal digest is grouped public → local → national →
   federal, with "sites that failed" at the end. `--json` and `--email` are
   also available.

**Politeness.** Every request goes through `http.py`:
- a real User-Agent (set it in `settings.user_agent`)
- a delay between requests to the same host (`request_delay_seconds`, default 2s)
- robots.txt checks
- retries with exponential backoff on 429/5xx and network errors, honoring
  `Retry-After`

**Your first run reports every currently matching posting.** That's your
starting list. After that you only see changes.

## Employers and how each one is fetched

| id | Employer | ATS / source | type |
|---|---|---|---|
| kimley-horn | Kimley-Horn | iCIMS (`careers-kimley-horn.icims.com`) | `icims` |
| hdr | HDR | Oracle Taleo (`hdr.taleo.net`, section `ex`, portal 101430233) | `taleo` |
| hntb, hntb-university | HNTB | Workday (`hntb.wd5`, sites `HNTB_Careers` / `HNTB_University_Careers`) | `workday` |
| wsp | WSP | Oracle Recruiting Cloud (`emit.fa.ca3.oraclecloud.com`, site `CX_2001`) | `oracle_hcm` |
| jacobs | Jacobs | Avature at careers.jacobs.com. The tool reads the server-rendered Las Vegas page on jacobs.jobs instead | `html` |
| stantec | Stantec | Oracle Taleo (`stantec.taleo.net`, portal id auto-discovered) | `taleo` |
| aecom | AECOM | SmartRecruiters (`AECOM2`) | `smartrecruiters` |
| atkinsrealis | AtkinsRéalis | Workday (`slihrms.wd3`, site `Careers`) | `workday` |
| horrocks | Horrocks | UKG Pro / UltiPro (`recruiting2.ultipro.com/HOR1015HOCK`) | `ultipro` |
| gcw | GCW | Betterteam (`gcwengineering.betterteam.com`) | `html` |
| lochsa | Lochsa Engineering | Own site, pages under `/careers/` | `html` |
| ca-group | CA Group | Own site (they usually ask for mailed resumes) | `html` |
| nv-state | State of Nevada incl. NDOT | NEOGOV (`governmentjobs.com/careers/nv`) | `neogov` |
| rtc-snv | RTC of Southern Nevada | NEOGOV (`rtc`) | `neogov` |
| clark-county | Clark County | NEOGOV (`clarkcounty`) | `neogov` |
| city-of-las-vegas | City of Las Vegas | NEOGOV (`lasvegas`) | `neogov` |
| city-of-henderson | City of Henderson | NEOGOV (`henderson`) | `neogov` |
| usajobs-0810 | USAJOBS, series 0810 within 50 mi, GS ≤ 9 | Official USAJOBS Search API | `usajobs` |

**These were identified from job URLs that search engines have indexed.**
The machine this was built on had no network access to the career sites. Each
entry's `verified:` field says what the identification is based on. **Run
`job-watch probe --all` once** and fix any entry that fails or returns 0
postings. The next sections explain how.

Fetcher types available: `workday`, `greenhouse`, `lever`, `icims`,
`usajobs`, `rss`, `html`, `neogov`, `taleo`, `oracle_hcm`,
`smartrecruiters`, `ultipro`. None of the current employers uses
Greenhouse or Lever, but both fetchers are there for when one does.

## Adding a new employer

Usually this is only config. Figure out the ATS (next section), then add an
entry:

```yaml
  - id: new-firm                 # unique slug; used by --only / probe
    name: New Firm
    category: national           # national | local | public | federal
    type: workday                # picks the fetcher
    careers_url: https://...     # for your reference
    verified: "how you confirmed the tenant"
    options:                     # fetcher-specific, documented at the top of each fetcher module
      host: newfirm.wd1.myworkdayjobs.com
      tenant: newfirm
      site: External
      search_text: Las Vegas
    filters:                     # optional per-employer overrides
      extra_level_include: [staff engineer]
      # skip_level / skip_discipline / skip_location: true
```

Then run `job-watch probe new-firm --verbose` to see what it fetches and why
each posting did or didn't match.

Options for each type (full docs are at the top of each module in
`src/job_watch/fetchers/`):

| type | options |
|---|---|
| `workday` | `host`, `tenant`, `site`, `search_text`, `applied_facets` |
| `greenhouse` | `board_token` |
| `lever` | `company` |
| `icims` | `host`, `search_keyword`, `search_location`, `render_js` |
| `taleo` | `host`, `section`, `portal` (optional), `keyword`, `title_column`/`location_column`/`date_column` |
| `oracle_hcm` | `host`, `site`, `keyword`, `location`, `radius` |
| `smartrecruiters` | `company`, `q`, `city`, `country` |
| `ultipro` | `host`, `tenant`, `board_id`, `query` |
| `neogov` | `agency`, `host`, `default_location` |
| `usajobs` | `job_category_code`, `location_name`, `radius_miles`, `keyword`, `max_low_grade` |
| `rss` | `url`, `location_field`, `location_regex`, `default_location` |
| `html` | `url`, then either `item_selector` (+ `title_selector`, `link_selector`, `location_selector`) or `link_regex`; plus `render_js`, `wait_selector`, `default_location`, `exclude_titles` |

**If a site uses an ATS with no fetcher yet**, add a module in
`src/job_watch/fetchers/`:
1. Subclass `Fetcher`, set `type_name` and `required_options`, and implement
   `fetch()`. Put the pure parsing in a `parse()` method.
2. Register the class in `fetchers/__init__.py`.
3. Save a sample response in `tests/fixtures/` and add a parse test.

### Identifying the ATS from the apply link

Click "Apply" or open any job, then look at the URL:

| URL looks like | ATS | type |
|---|---|---|
| `{tenant}.wd1.myworkdayjobs.com/{site}/...` | Workday | `workday` |
| `job-boards.greenhouse.io/{token}` or `boards.greenhouse.io/{token}` | Greenhouse | `greenhouse` |
| `jobs.lever.co/{company}` | Lever | `lever` |
| `careers-{x}.icims.com/jobs/...` | iCIMS | `icims` |
| `{x}.taleo.net/careersection/{section}/...` | Taleo | `taleo` |
| `{x}.oraclecloud.com/hcmUI/CandidateExperience/en/sites/{site}` | Oracle Recruiting | `oracle_hcm` |
| `jobs.smartrecruiters.com/{company}/...` | SmartRecruiters | `smartrecruiters` |
| `recruiting*.ultipro.com/{tenant}/JobBoard/{guid}` | UKG / UltiPro | `ultipro` |
| `governmentjobs.com/careers/{agency}` | NEOGOV | `neogov` |

### Finding a site's hidden JSON endpoint (browser network tab)

Most modern career pages are JavaScript apps that load the job list from a
JSON API. Using that API is faster and more reliable than scraping the HTML,
and it's the same data the page itself uses.

1. Open the careers search page in Chrome or Firefox.
2. Open DevTools (F12 or Cmd+Opt+I), go to the **Network** tab, and select the
   **Fetch/XHR** filter.
3. Reload the page, or type a search (e.g. "Las Vegas") and submit it.
4. Look for requests whose response is job data. Click one and check the
   **Response** or **Preview** tab for a list of titles. Tell-tale names:
   `jobs`, `search`, `postings`, `requisitions`, `LoadSearchResults`,
   `searchjobs`.
5. Look at the **Headers** tab for the method and URL, and the **Payload** tab
   for the POST body.
6. Right-click the request → **Copy → Copy as cURL** and run it in a
   terminal. If it works without your browser cookies, the tool can use it.
   Try removing headers one at a time to find the minimum it needs.
7. Map it to config:
   - If it matches a known ATS, fill in that type's options.
   - If the response is RSS/Atom, use `type: rss`.
   - If it's a one-off JSON API, write a small fetcher (see "Adding a new
     employer" above) and save the response as a test fixture.
   - If there's no XHR and the jobs are already in the page source
     (View Source → search for a job title), use `type: html` with selectors.
   - If the jobs only appear after JavaScript runs and there's no usable
     API, use `type: html` with `render_js: true` (needs Playwright).

Paging: note the `offset`/`limit`/`page`/`Skip`/`Top` fields in the request
and the `total`/`totalCount` field in the response. The existing fetchers use
these to page through results.

## Tuning the filters

Everything is in `config.yaml` under `filters:`. Examples:
- **Too much noise**: add words to `level.exclude` or `discipline.exclude`.
- **Missing something**: run `job-watch probe <id> --verbose`. It prints the
  exact reason each posting was rejected. Then add the missing term to the
  matching `include` list.
- **Planning or structures roles**: add `planner`, `planning`, `structural`
  to `discipline.include` (and `planner` to `level.include`).
- **No remote postings**: set `location.remote_ok: false`.

The test suite runs against the shipped `config.yaml`. So if you change a
keyword list, `uv run pytest` shows which of the example titles in
`tests/fixtures/filter_cases.json` behave differently. Update those
expectations if the change was intentional.

## Scheduling a weekly run

**cron (Linux/macOS).** Run `crontab -e` and add this line for every Monday
at 7:00 am:

```cron
0 7 * * 1 cd /path/to/MarikoJobFinder && /path/to/uv run job-watch run --email >> ~/job-watch.log 2>&1
```

Use the full path from `which uv`. cron has a minimal `PATH`. If you use a
plain venv, replace `/path/to/uv run job-watch` with
`/path/to/MarikoJobFinder/.venv/bin/job-watch`.

**launchd (macOS).** Save this as
`~/Library/LaunchAgents/com.jobwatch.weekly.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>             <string>com.jobwatch.weekly</string>
  <key>WorkingDirectory</key>  <string>/Users/YOU/MarikoJobFinder</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/YOU/MarikoJobFinder/.venv/bin/job-watch</string>
    <string>run</string>
    <string>--email</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key> <integer>1</integer>   <!-- Monday -->
    <key>Hour</key>    <integer>7</integer>
    <key>Minute</key>  <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>   <string>/Users/YOU/job-watch.log</string>
  <key>StandardErrorPath</key> <string>/Users/YOU/job-watch.log</string>
</dict>
</plist>
```

Then load it:

```bash
launchctl load ~/Library/LaunchAgents/com.jobwatch.weekly.plist
launchctl start com.jobwatch.weekly     # run once now to test
```

launchd runs a missed job when the Mac wakes up. cron doesn't.

## Development

```bash
uv run pytest            # all tests are offline and use tests/fixtures/
```

- The fixtures are hand-made in the shape of each platform's real responses.
- To test against a real response, save the output of
  `curl ... > tests/fixtures/<name>.json` and point a test at it.
- After changing dependencies, regenerate requirements.txt with
  `uv export --no-hashes --no-dev --no-emit-project -o requirements.txt`.
