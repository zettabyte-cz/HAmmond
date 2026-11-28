# Changelog

All notable changes to xomtra are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) (see
[docs/releasing.md](docs/releasing.md)). Before 1.0.0 a minor release may contain
breaking changes; they are listed under **Changed** with an upgrade note.

Add an entry under `[Unreleased]` in every pull request with a user-visible change
(sections: Added, Changed, Deprecated, Removed, Fixed, Security).

## [Unreleased]

### Changed

- Admin: the page *Retention* says at the top that its periods are those of the xomtra
  Data Lake, not of Home Assistant (whose recorder has its own retention).
- Admin: the page *Retention* has a new section *Data Lake* above the lake's tables,
  opening with a highlighted panel on backups. In the add-on it is the note that Home
  Assistant backups do not include the lake (moved from *Overview*); in the Docker
  edition it says to back up the Data Lake and the other volumes and links the
  [backup guide](docs/setup/backup.md).
- Admin: the pages *Answers* and *Tokens* are called *MCP setup* and *MCP tokens*
  (cs *MCP Setup*, *MCP Tokeny*), so it is clear they set up the MCP connection of the
  AI assistants; their addresses `/admin/answers` and `/admin/tokens` stay.
- Admin: the page *Analysis settings* is called *Analysis parameters* (cs *Parametry
  Analýz*); its address `/admin/analysis` stays.
- Admin: the page *Audit* is called *Audit log* (cs *Audit Log*); its address
  `/admin/audit` stays.

### Fixed

- Local access: `https://<address>/` redirects to the admin GUI (`/admin/`) instead of
  answering "Not found".
- Docs: [Docker Compose](docs/setup/docker.md) names the admin GUI address
  `https://<address>/admin/` and that `docker compose up -d` alone does not print the
  setup link.
- A new installation before its first catalog run: `search_catalog` and `get_findings`
  return an empty result with a note that the catalog is not built yet, and
  `describe_entity` says so, instead of the DuckDB error *Table with name
  catalog_entity does not exist*.
- `xomtra-ingest catalog` on a new installation before the first hourly ingest runs the
  ingest sync first (registries, statistics, SQLMesh) instead of failing with *Table
  silver.entities does not exist*.

## [0.10.0] - 2026-11-28

### Added

- Admin: *Overview* shows the size of the data lake (its data files according to the
  DuckLake catalog).
- Admin: *Overview* shows the free space on the disk also in the Docker edition (the
  `admin` container mounts the SeaweedFS volume read-only at `/disk`,
  `XOMTRA_DISK_PATH`), with a warning below 10 %.
- Docs: [backup and restore](docs/setup/backup.md) of the Docker Compose installation,
  cold (volumes with the stack stopped) and hot (Postgres dump first, then the lake
  files through S3 with rclone), with the reason for the order and what to restore.

- Retention set in the admin GUI: the page Retention has a form for each of the three
  periods (states, 5-minute statistics, hourly statistics; 1 to 3650 days), with a
  reason, the history of changes and *Reset*. A saved period wins over the
  installation's configuration and applies from the next retention run, without a
  restart; a shorter period asks for a confirmation, because the next run deletes the
  older data. Every change is in the audit (ADR 094). The page no longer tells you to
  edit `.env` or restart containers.

  Upgrade note: nothing to do. `XOMTRA_*_RETENTION_DAYS` in `.env` and the add-on's
  options `*_retention_days` keep working and are now the default that a value saved in
  the admin GUI overrides.
- Docs: complete uninstall of the Docker Compose installation
  ([docs/setup/uninstall.md](docs/setup/uninstall.md)): optional backup of the volumes,
  `docker compose down -v --rmi all`, the Claude clients and the CA certificate, the
  token and user in Home Assistant, and the public setup.
- Release asset `xomtra-<version>-compose.tar.gz` with `xomtra/deploy/compose` of the
  tag, covered by `SHA256SUMS`: Docker Compose installs and upgrades without git.
- Docs: cosign runs in its official container pinned by digest, no installation needed.

### Changed

- Docs: the installation is split into two separate paths. **Local access** (LAN or
  VPN, personal tokens) is the default and the first one in
  [docker.md](docs/setup/docker.md) and [the setup overview](docs/setup/README.md);
  **access from the internet** for claude.ai ([claude-connector.md](docs/setup/claude-connector.md))
  is an advanced guide on top of it: requirements, the switch in `.env` with
  `docker compose up -d --force-recreate`, what stops working (personal tokens) and the
  way back. It states that an installation runs one access mode at a time and that the
  admin GUI cannot switch it, and that the Home Assistant sign-in of the connector needs
  `XOMTRA_HA_URL` in `.env`.

- Docs: Docker Compose installs and upgrades from the release archive
  `xomtra-<version>-compose.tar.gz` checked with `SHA256SUMS` (`curl` and `tar`, no
  git); [docs/setup/docker.md](docs/setup/docker.md) has a new section *Upgrade*.
- Admin: the Home Assistant card on *Overview* and after the setup shows the address
  (FQDN or IP) of the connected Home Assistant instead of its version and response time;
  in the add-on it says *this Home Assistant*.
- Admin: the *Overview* card *Last state in lake* is now *Last data state change*; it is
  the time of the newest state change stored in the lake, not of a page refresh.
- Admin: *Last statistic* on *Overview* is now *Last hourly statistic* and shows the
  newest hourly statistic only (before, a 5-minute one could be newer).

### Removed

- Docker compose: the lite override `deploy/compose/compose.lite.yaml` (ADR 095). The
  Docker compose installation is the full edition only (SeaweedFS, Dagster); it is
  meant for a machine with enough memory, not for a small server. The lite edition
  (worker, lake on the local disk) stays in the Home Assistant add-on. Upgrade note:
  installations started with `compose.lite.yaml` (or `COMPOSE_FILE=...:compose.lite.yaml`
  in `.env`) keep the file from their current version; their lake is in the volume
  `lake-data` and does not move to SeaweedFS. To move to the full edition, install it
  anew (new volumes); it loads the history again from what Home Assistant still holds.

### Fixed

- Admin GUI: dates are written as the language of the admin writes them (for example
  27. 11. 2025 in Czech, 27.11.2025 in German) already on the server, and the cut-off
  date on Retention is formatted like every other date (it was ISO).
- Admin GUI: the page Catalog of a new installation explains that the catalog is
  profiled once a day at 04:15 (in `XOMTRA_TIMEZONE`) and shows its entities after the
  first night, instead of an empty table; the empty choice of the kind filter reads
  "all kinds". To profile right away: `docker compose exec dagster-daemon xomtra-ingest
  catalog`.

## [0.9.2] - 2026-11-27

### Added

- Claude Desktop without trusting a certificate: in the local access mode the extension
  downloaded from the admin GUI (**Download for Claude Desktop** after issuing a token,
  also on Connect clients) carries the root certificate of the server's own CA and
  trusts only it (pinned), so nothing has to be imported into the computer. The admin
  GUI reads the certificate from Caddy inside the compose network
  (`XOMTRA_LOCAL_CA_URL`, an internal listener on port 8081 that is not published). The
  token is still entered at install and never part of the file. An extension from
  before a new installation of the server says to download it again. Claude Code and
  other clients still need the CA trusted as described in docs/setup/local-access.md.

  Upgrade note (Docker compose): take the new `deploy/compose/compose.yaml` together
  with the new images (it sets `XOMTRA_LOCAL_CA_URL`), then `docker compose up -d`.
  With an older compose file the download keeps working, only without the certificate.

### Changed

- Admin GUI, clearer structure and texts: the menu starts with Findings, Answers and
  Tokens; Drift is called Entity changes; the page Answers has one introduction and folds
  the text of a factory set; Tokens says in one line which assistants can connect (the
  details stay on Connect clients); Analysis settings opens with the advice to leave
  working settings alone and no longer cites ADR numbers; Retention in the add-on names
  the add-on's options instead of Dagster and `.env`; Findings explains a dismissal
  without internal names and translates its columns and types. Czech and German texts
  reviewed (German now uses "du", as Home Assistant does).
- Admin GUI, Tokens: the picture of the flow no longer has the Claude Desktop button
  (the page of a new token has the download), and the arrow labels sit above and below
  the boxes, so that longer translations no longer run into them. The note on the style
  of the answers moved from Tokens and Connect clients to the page Answers.
- Admin GUI (Docker compose): the menu no longer links to the Dagster UI; it stays
  reachable for administrators at `/admin/dagster/`.
- Admin GUI: the page Access is in the menu only where it has something to manage (the
  Claude connector with Home Assistant sign-in, public mode). With personal tokens, the
  add-on or Entra ID it had only a sentence; `/admin/access` leads to Tokens, which
  carries the Entra note.
- Admin GUI: when Home Assistant cannot be reached (setup page and Overview), a sentence
  says why and what to try, in every language of the admin GUI: `https://` on a plain
  HTTP port ("try http://"), an untrusted certificate, a name this server cannot
  resolve, nothing listening on the port, another server or a proxy without WebSockets
  answering, a timeout, or a rejected token. The technical message follows as a detail.

### Fixed

- An address that answers HTTP but not with a WebSocket upgrade no longer ends in an
  internal error on the setup page; it is reported like any other connection error.
- Setup page: whitespace copied with the access token (a line break from a wrapped
  terminal line, a trailing newline) is dropped instead of making Home Assistant reject
  the token, and the token field asks password managers not to fill in a saved password
  (`autocomplete=new-password`).
- Setup page: an address without a port (`http://192.168.1.10`) means port 80 or 443,
  where often another server answers. The setup now tries Home Assistant's port 8123 as
  well and stores that address if it works; otherwise the error says that the port is
  missing. The example in the URL field shows the port.
- Claude Desktop extension: a certificate the computer does not trust
  (`unable to get local issuer certificate`) is no longer reported with the network
  hint (Local Network permission). The message says to choose `xomtra-ca.crt` as
  *Certificate of the server*, that a chosen file is not the CA of this server, or that
  the certificate is for another name.
- Docs (local access) and the Connect page: trusting xomtra's CA is required for Claude
  Desktop and Claude Code, with the commands for macOS, Windows and Linux and how to
  compare the fingerprint on both sides.

## [0.9.1] - 2026-11-27

### Added

- Findings record their provenance in `catalog.finding` and the weekly snapshots:
  `analyzer` (`correlations` or `anomalies`), `pack` and `pack_version` (the parameter
  pack, `home`) and `source_instance` (`ha`). The columns are added to existing lakes on
  the next analysis run; older rows stay empty (ADR 089, preparation for data plugins).
- Development: `uv run lint-imports` checks the boundaries between the domain-neutral
  modules and the Home Assistant modules (import-linter contracts, also in CI).

### Changed

- Docker compose: the installation ends with the one-time setup link on the terminal,
  `docker compose up -d && docker compose exec admin xomtra-admin setup-link`, instead of
  searching for it in `docker compose logs admin` (where it stays as well). The new
  command `xomtra-admin setup-link` prints the link while Home Assistant is not
  connected, and where to sign in once it is.
- Docs (Docker compose): new step "0. Address" (the LAN address works without settings;
  a name goes into `.env` before the first start and only has to resolve on the
  clients). Changing the address later needs `docker compose up -d --force-recreate`,
  not just `up -d`, so that every service takes the new address.

### Fixed

- Docker compose: the first `docker compose up -d` of a new installation could stop with
  "dependency failed to start: container xomtra-seaweedfs-1 is unhealthy". SeaweedFS
  started alongside `secrets-init`, exited before its S3 keys were written, and compose
  gave up although the container came up healthy a few seconds later. SeaweedFS now
  waits for `secrets-init`; a test checks that every service reading the secrets volume
  does (full and lite edition).

## [0.9.0] - 2026-11-27

### Added

- Admin page **Answers** (ADR 090): named sets of answer guidelines kept in the local
  database. Factory sets **Default** (relevant data first, the answer first, then a chart
  or a table, friendly tone, with topics: energy with solar, battery, feed-in and costs;
  security with alarms, cameras and motion, counted per area and never per person;
  vehicles; heating and indoor climate; water; device health; the weekly overview, each
  with what to look at, which charts and optional external sources such as spot prices,
  weather or fuel prices), **Concise** (as short as possible, no jokes) and **Core
  only** (no guidelines); custom sets (up to 20, 8,000 characters each) are duplicated from any set and edited in
  the browser, with a preview of exactly what the assistant gets, a history with restore,
  and export and import as JSON. One set is active; a change applies within 30 seconds,
  without a restart.

### Changed

- The default answer guidelines aim at relevant results and readable answers: search
  before answering, compare periods, rank findings, answer first, charts or compact
  tables, "what to check" at the end.
- The core rules also cover conclusions about persons, invented values and read only
  access; they come before every set and cannot be changed or turned off.
- Tool descriptions carry only the short core rules; `answer_guidelines` in the results
  of `server_info`, `get_findings` and `get_weekly_summary` carry the core rules and the
  active set; other data results name the active set (`answer_guidelines_set`).

### Removed

- Add-on options `answer_style` and `default_guidelines` and the variables
  `XOMTRA_ANSWER_STYLE` and `XOMTRA_DEFAULT_GUIDELINES`, including the pub style.
  **Upgrade note:** every installation starts with the set Default (also those that had
  the pub style). If you had turned the guidelines off, activate **Core only** on the
  page Answers; a pub-like tone can be written as a custom set (within the core rules).
- The place for a central theme from xomtra.com (ADR 075): no text for the assistant ever
  comes from a central service.

## [0.8.0] - 2026-11-27

### Added

- Admin page **Access** (public access with Home Assistant sign-in, ADR 081): give HA
  users who are not administrators the role `xomtra.Reader`, and see every sign-in of
  the Claude connector with **Disconnect**.
- Claude connector sign-ins end after `XOMTRA_SESSION_DAYS` (default 180); in the last
  14 days `server_info` asks the assistant to tell the user to connect again.
- Guide [which installation to choose](docs/setup/choose-edition.md): limits of the
  add-on and of an own machine, supported AI assistants, what the external connector
  needs (domain, A record, port 443, certificate, sign-in).
- Answer style option (add-on option `answer_style`, `XOMTRA_ANSWER_STYLE`): `friendly`
  (default) or `pub`, the crude style of 0.7.x with personal humour (ADR 080).

### Changed

- Home Assistant sign-in is the default (`XOMTRA_AUTH_MODE=ha`); Entra ID stays an
  option (ADR 081). **Upgrade note:** installations with Entra ID that did not set
  `XOMTRA_AUTH_MODE` must add `XOMTRA_AUTH_MODE=entra` to `.env` (the server refuses to
  start with Entra values and no mode, with this hint).
- Public access with Home Assistant sign-in: only HA administrators get in by default
  (`XOMTRA_HA_ROLE_MAP` default `admin=xomtra.Admin,user=`); other users need a role on
  the page Access. **Upgrade note:** users who were Readers through the old default
  need that role on the page Access.
- Claude connector with Home Assistant sign-in requires two-factor authentication in
  HA (`XOMTRA_HA_REQUIRE_MFA`, default `true`).
- Default answer style is friendly with light humour; the crude pub style is an option.
- Core rules also forbid politically or religiously tinged jokes and innuendo, in every
  style and theme.
- Personal tokens expire after at most a year (30, 90 or 365 days, 90 by default); the
  option "never" is gone. Existing tokens keep their expiry.
- Admin GUI: the note on AI assistants says plainly that claude.ai needs an installation
  on its own virtual machine with a public address and that ChatGPT and other cloud
  assistants are not supported yet.

### Security

- The Claude connector keeps no Home Assistant token of the user: it is revoked right
  after the sign-in (as the admin GUI already did). Requests are checked against the
  session, the access list and, with an administrator token in xomtra's HA connection,
  HA's user directory. Audit records `connector:sign_in` (with `ha_token_revoked`) and
  `connector:session_refused`.

## [0.7.1] - 2026-11-26

### Added

- Option to turn off the default answer style (add-on option `default_guidelines`,
  `XOMTRA_DEFAULT_GUIDELINES=false` elsewhere), with a note on the admin pages for
  tokens and clients (ADR 080).
- Place for a central theme from xomtra.com (ADR 075, e.g. Christmas, Easter,
  Halloween): when one is active it comes first in `answer_guidelines` and takes
  precedence over the default style. It cannot be turned off, is forgotten 24 hours
  after it was received and never overrides the core rules.

### Changed

- Default answer style: very funny, crude and vulgar, like a mate in the pub, fitted to
  the language, country, culture and locality of the installation and to the owner's
  line of work when the user mentions it (never to wealth or status), for the user as
  the occupant of the property; teasing the user only with tact; facts stay exact
  (ADR 073, 080).
- Humour made personal and a bit politically incorrect: the assistant uses what it
  already knows about the user from its own context (memory, profile, conversation),
  never personal details inferred from the house data, never the user's clients or
  employers by name, always within the core rules (ADR 080).
- Core rules that always apply, also with the default style off and above a central
  theme: no jokes, irony or vulgarity about accidents, faults, outages, risky
  situations or threats to life or health; no sexist, racist, homophobic, xenophobic
  or political jokes or innuendo and no slurs against any group.

## [0.7.0] - 2026-11-26

### Added

- Docker Compose installs with one command (ADR 077): `docker compose up -d` works
  without a `.env`. The new one-shot service `secrets-init` generates every internal
  password and key into the Docker volume `secrets` (one file per service, readable
  only by its user) and finds the server's LAN address for the local access mode.
- Setup page in the admin GUI (`/admin/setup`): the Home Assistant URL and token are
  entered in the browser after the first start, checked against Home Assistant and
  stored encrypted in Postgres. Until then a one-time link is printed to
  `docker compose logs admin`; the stream and the hourly ingest wait for the connection.
  Signed-in administrators can change the URL or token later on the same page.
- Guide [docs/setup/docker.md](docs/setup/docker.md).

### Changed

- Tone of answers with xomtra data: humour is now the default style, with at least one
  joke or witty remark in every answer (about the house and the data, never about people,
  safety, health or a fault, and never at the cost of exact facts). Applies to the server
  instructions, `answer_guidelines` and the rules in tool descriptions (ADR 073, 080).
- Compose defaults: `XOMTRA_ACCESS_MODE=local`, `XOMTRA_AUTH_MODE=ha`, `ADMIN_CIDR` all
  private ranges; no variable is required any more. Public access still needs its
  values in `.env`.
- `init-env.sh` is an optional guide and no longer writes internal passwords.
  **Upgrade note:** an existing `.env` with passwords keeps working; on the first start
  `secrets-init` takes them over into the volume `secrets`, after which they can be
  removed from `.env`. Back up the volume `secrets` together with the data volumes.
- The documentation and the Claude Desktop extension now say precisely what "read only"
  means: xomtra only reads and never calls Home Assistant services, and the assistant
  gets read-only tools over xomtra's own data. Home Assistant has no read-only tokens,
  so this is guaranteed by xomtra's code; the Docker guide explains why a separate
  non-admin user is still recommended (access can be revoked at any time).

## [0.6.2] - 2026-11-26

### Fixed

- The default guidelines for answering with xomtra data (findings are hypotheses, no
  conclusions about people unless asked, friendly tone) now also reach clients that do
  not pass the server instructions to the model, such as a proxy between Claude and a
  local MCP server: a short version is part of every data tool description, and the
  full text comes with `server_info`, `get_findings` and `get_weekly_summary`
  (`answer_guidelines`).

## [0.6.1] - 2026-11-26

### Added

- Admin GUI, Tokens and Connect clients: a note on which AI assistants can connect to
  the local access mode (assistants on a computer in the LAN, not cloud connectors
  such as claude.ai or ChatGPT).
- Admin GUI footer with the version (links to its release notes), xomtra.com, the
  documentation and bug reports. The links open in a new tab and send no Referer.

### Changed

- Claude Desktop extension: the xomtra icon and xomtra.com as its homepage.
- Admin GUI overview: smaller card values that fit on one line, clearer catalog column
  names (entity kind, entities, stale entities), the profiling time in the local
  format, and the backup note in one box.

### Fixed

- Claude Desktop extension did not start in Claude Desktop's built-in Node.js
  ("Unable to connect to extension server"): the bridge only started when run as the
  main script. It now always starts.
- Claude Desktop extension: a server it cannot connect to (wrong address, or on macOS
  Claude not allowed in Local Network) now gives an error with a hint within 10 s
  instead of Claude Desktop's "Unable to connect to extension server" after a minute.
- Admin GUI: Safari saved the Claude Desktop extension as `xomtra.zip`. It is now
  sent as `application/octet-stream` with a plain file name and saves as
  `xomtra.mcpb`.
- Admin GUI after an upgrade: the browser kept the previous version's stylesheet and
  script (cached for an hour or a day) and showed the new pages half unstyled. Their
  URLs now carry a version (also the tips and the icon), so an upgrade loads the new
  ones, and the token diagram stays readable without its stylesheet.
- Home Assistant add-on: the update dialog said "No changelog found". The add-on now
  ships its own `CHANGELOG.md` with the last five released versions;
  `scripts/release.py prepare` writes it and `check` refuses a tag without it.

## [0.6.0] - 2026-11-26

### Added

- Admin GUI and add-on options in Czech, German, Polish and Dutch: the GUI follows Home
  Assistant's language (outside Home Assistant the browser's), English stays the
  default. Entity names, values and code stay as they are.
- Analysis settings: "Reset all to defaults" sets every changed setting back to its
  default in one step (confirmed with a tick box, recorded in the history and audit).
- Admin GUI: explanations of the columns and cards on hover or focus, in the language of
  Home Assistant (English, Czech, German, Polish, Dutch); numbers with digit grouping,
  shares as percentages, dates and times in Home Assistant's number, date and time
  format and time zone (outside Home Assistant the browser's).
- Free disk space of the lake on the admin overview. Below
  `XOMTRA_WORKER_STOP_FREE_RATIO` (default 3 %) the worker pauses the stream and the
  writing jobs until there is space again, then catches up from Home Assistant's
  history; the retention still runs (ADR 072).
- Home Assistant add-on: the overview and the documentation say that Home Assistant
  backups do not include the lake (history and findings) and recommend xomtra on its
  own virtual machine for backups of the whole history.
- Default guidance for the LLM in the MCP server's instructions (ADR 073): findings as
  hypotheses with their strength and window, statements based on fetched data, local
  time, no conclusions about a person unless asked, a friendly tone with the odd joke or irony,
  and no advice on locks or alarms from a finding alone. Advisory for the model; the
  server's access rules are unchanged.
- Tokens page: a picture of how a token connects an LLM agent with xomtra and that
  xomtra only reads Home Assistant, with the page's actions on it.

### Changed

- The admin GUI has the look of xomtra.com: the xomtra mark and wordmark, Geist and
  Geist Mono (bundled, no external requests), graphite and indigo colours. It is dark
  by default; behind Home Assistant Ingress it turns light when Home Assistant is in
  light mode. The add-on has an icon and a logo for the add-on store.
- The add-on's website link in Home Assistant points to https://xomtra.com instead of
  the GitHub repository.

### Fixed

- Home Assistant add-on: after a restore from a backup (which leaves the lake out) it
  failed on Parquet files the catalog still named. It now detects the missing lake,
  starts a new one and loads the history from Home Assistant again; tokens, audit and
  analysis settings stay.
- Worker on a new lake (first start, or after a restore without it): the live stream
  and the missed jobs both created the `bronze` schema, one failed on the DuckLake
  transaction conflict and the stream reconnected. The worker now creates the lake's
  schemas and tables once before the stream and the jobs start.
- Admin GUI behind Home Assistant Ingress: forms (issuing a token, settings) were still
  refused with "Cross-site request refused" when Home Assistant is opened over plain
  `http://` in the LAN. Browsers send `Sec-Fetch-Site` only to https origins, and the
  Origin does not match the forwarded host that reaches the add-on. Behind Ingress the
  forms now carry a token bound to the Home Assistant user and the Ingress session;
  `Sec-Fetch-Site: cross-site` or `same-site` is still refused.
- Postgres no longer logs DuckLake's commit retries ("duplicate key value violates
  unique constraint ducklake_snapshot_pkey") as errors: the stream and the jobs write
  at the same time and DuckLake retries such a commit by design. Errors of the catalog
  database are left to the services, which log them.

## [0.5.1] - 2026-11-26

### Fixed

- Home Assistant add-on: it did not start ("expected url" for `mcp_url`). The empty
  default of the optional option failed the Supervisor's check of `url?`; optional
  options now have no default, and a test keeps the defaults in line with the schema.
- `migrate-from-hammond.sh` stopped at its first step: `docker compose -p hammond down`
  read the new `compose.yaml` with the old `.env` and failed on the missing `XOMTRA_*`
  variables. It now stops and removes the old containers and networks by their compose
  labels.
- Postgres (add-on and compose) logs errors without the failed statement. DuckLake
  retries a commit when another writer took its snapshot id, and the statement filled
  the add-on log with Home Assistant data.
- Claude Desktop extension downloaded from the admin GUI: for a plain `http://` address
  (the add-on in the LAN) *Allow unencrypted http://* is checked by default; before, the
  extension refused the add-on's endpoint until the user found the checkbox.
- Admin GUI behind Home Assistant Ingress: every form (issuing a token, settings) was
  refused with 403 when Home Assistant is opened through another address than its own
  host, e.g. behind a reverse proxy. The cross-site check now trusts the browser's
  `Sec-Fetch-Site` header and compares the Origin only where that header is missing.

## [0.5.0] - 2026-11-25

### Added

- Home Assistant add-on (lite edition, in development): one container with Postgres,
  the worker and the MCP server for the LAN, supervised by s6-overlay; internal secrets
  and the Postgres cluster are generated on the first start in `/data`; Home Assistant
  is reached through the Supervisor. Built, scanned and started in CI (job `addon`).
  `XOMTRA_HA_URL=http://supervisor/core` uses the Supervisor's WebSocket endpoint.
- Admin GUI behind Home Assistant Ingress (ADR 070, add-on): `XOMTRA_AUTH_MODE=ingress`
  takes the user from the Supervisor's `X-Remote-User-*` headers, accepts only the
  Ingress proxy's address and serves its links under `X-Ingress-Path`;
  `XOMTRA_DAGSTER_UI=false` hides the Dagster link. The add-on shows the GUI in the
  sidebar for HA administrators.
- Home Assistant add-on repository (`repository.yaml`): the add-on images
  `xomtra-addon-amd64` and `xomtra-addon-aarch64` are built natively, signed and
  published with every commit of `main` and promoted with every release;
  `scripts/release.py` keeps the add-on version in step.
- Admin GUI page *Analysis settings* (ADR 060): thresholds of correlations, anomalies
  and change points can be changed without a restart, with a preview of their effect on
  the current findings and a history of changes. A stored value wins over the ingest's
  environment variable. New schema `analysis` in the audit database (created by
  `ensure-databases`), new ingest variable `XOMTRA_ANALYSIS_SETTINGS_DB` (default
  `audit`).
- Admin GUI page *Findings* (ADR 060 point 6): a finding can be dismissed (the pair of
  entities of a correlation, the entity of an anomaly or change point), for good or
  until a date, and undone. The ingest flags matching findings `dismissed` after every
  run; `get_findings` and the weekly summary hide them like the other flags.
- Low-power indicator (ADR 067): every correlation run records its confidence in
  `catalog.analysis_run`: `low` with fewer than 30 analysed series or less than 80 % of
  the analysed entities in an HA area. `get_findings` returns it per window
  (`confidence`, no entity names); the admin page *Findings* shows it with the analysed
  entities that have no area. The thresholds are not tightened: on the synthetic
  households a stricter q or |r| did not lower the false discovery rate, complete areas
  did.
- Usefulness of findings (ADR 062 point 9, ADR 068): every finding gets `strength`,
  `evidence`, `nontriviality`, `action_category` and `usefulness` = R0 =
  √(strength · evidence); findings are ranked by it within type and window. Trivial
  relations (T1–T6: one device, one quantity twice, a helper and its source, one device
  class twice in one area, known physics, a collection artefact) get the flag `trivial`
  and are hidden by default. Categories come from the public, versioned rulebook
  `hacore/rules/actionability.toml` (17 entity families). `get_findings` returns
  `usefulness`, `action_category` and `trivial_rule`, and `ranking_version` in
  `methods`; the admin page *Findings* shows them.
- Analysis setting *Indirect and common-factor relations* (ADR 062 point 10,
  `XOMTRA_CORRELATION_STRUCTURE_DISPLAY`): `hide` (default), `lower` or `show`. New
  column `hidden` in `catalog.finding` decides what `get_findings`, the weekly summary
  and the admin hide by default (older rows: any flag). The weekly summary orders by
  usefulness.
- Preregistration of the usefulness evaluation (`docs/evaluation/usefulness-prereg.md`)
  and its metrics in `hacore.public.ratings`: Krippendorff's α (ordinal), weighted κ,
  NDCG@10, precision@10, cluster bootstrap over households and the simulation that
  fixes the human sample at 200 findings. `hacore.public.usefulness_sample` draws the
  stratified sample of findings on public data (manual job `usefulness-sample` of the
  validation workflow, CSV artifact kept 30 days, CC BY citation).
- Rulebook 1.0.1: a gas or smoke detector (`binary_sensor`) is air quality, a gas meter
  energy (both were air quality).
- Validation on public data (ADR 065, Gate 1c point 6): `hacore.public` fetches the IDEAL
  hourly readings with HTTP range requests (member list pinned, CRC-32 checked) and
  measures the cross-household null of correlations and anomalies
  (`python -m hacore.public.crosshouse`); `hacore.synthetic.benchmark` measures run time
  and memory. The nightly workflow `validation.yml` runs both on amd64 and arm64 and
  prints only aggregate metrics.

### Changed

- **Breaking: hammond is now xomtra (ADR 071).** The project moved to the organization
  **xomtra** (repository `github.com/xomtra/xomtra`) and every name follows: images
  `ghcr.io/xomtra/xomtra-{mcp,ingest,caddy}` and `xomtra-addon-{amd64,aarch64}`, Python
  packages `xomtra_mcp` and `xomtra_ingest`, commands `xomtra-*`, environment variables
  `XOMTRA_*`, compose project `xomtra` (containers and volumes), lake bucket `xomtra`,
  Postgres roles `xomtra_ops`, `xomtra_audit` and `xomtra_audit_admin`, Entra roles
  `xomtra.Admin` and `xomtra.Reader`, Home Assistant labels `xomtra_no_ingest` and
  `xomtra_no_analysis`, personal tokens `xmt_…` and the add-on slug `xomtra`. Releases up
  to 0.4.1 keep the image addresses of their `images.env`; signatures of new releases
  name the new repository. Upgrade: put the `*_IMAGE` lines of the release's
  `images.env` into `.env` (still under the old names) and run
  `deploy/compose/migrate-from-hammond.sh`: it rewrites `.env`, copies the volumes,
  renames the Postgres roles, copies the bucket and updates the DuckLake catalog,
  keeping the old data until you remove it. Then add the Entra roles, rename the labels
  in Home Assistant and issue new personal tokens (the old `hmd_…` tokens stop working).
- Anomalies v2 (ADR 066): the scale of a series is at least a quarter of its 99th
  percentile deviation in the baseline. Heavy-tailed series (appliances idling most
  hours) were scaled by their idle noise, so their ordinary use saturated the z cap and
  real episodes could not stand out (recall of planted episodes on the IDEAL homes was
  about 0). Normal series are not affected.

### Fixed

- `compose.lite.yaml` defaulted to the ingest image 0.3.0, which has no `worker`;
  `scripts/release.py` now keeps it at the release version like `compose.yaml`.

## [0.4.1] - 2026-11-25

### Fixed

- Anomalies v2 found nothing on a real installation: a few nearly constant sensors had
  a robust scale near 0 and z in the millions, which made the pooled reference so heavy
  that no episode passed. The scale is now at least the sensor's resolution and the
  episode statistic caps `|z|` at 50 (`HAMMOND_ANOMALY_Z_CAP`).
- Correlations: the stored top 100 of a window held only duplicates and same-device
  pairs after the unflagged ones, so explained relations (`indirect`, `house_context`,
  ...) were never stored. Explained and unstable pairs now come before the trivial
  ones.

## [0.4.0] - 2026-11-25

### Added

- Editions (ADR 050): `HAMMOND_EDITION=full|lite` selects default retention and DuckDB
  memory; `HAMMOND_LAKE_DATA_PATH` keeps the lake data files in a local directory
  instead of object storage (no SeaweedFS needed). Existing installations are unchanged.
- `hammond-ingest worker` (ADR 050): live stream and the scheduled jobs in one process
  instead of Dagster, with runs in the new Postgres database `ops`; `hammond-ingest job`
  and `hammond-ingest runs`. `deploy/compose/compose.lite.yaml` runs the lite edition
  (no SeaweedFS, no Dagster, lake data in a local volume).
- Synthetic households with known truth for evaluating the analyses
  (`hacore.synthetic`, `python -m hacore.synthetic.evaluate`, ADR 062): archetypes,
  hidden drivers, planted relations, defects and inserted events. See
  docs/analysis-evaluation.md.
- Correlation findings carry `p_value` and `explained_by`, and new flags
  `common_factor`, `indirect` and `unstable` (ADR 062). `get_findings` returns them;
  flagged findings are hidden unless `include_flagged`.
- Correlation flag `same_area` (ADR 064): a relation between two entities in one Home
  Assistant area (or, without an area, one area named in their ids or names) is
  explained by the room's occupancy and ranked after the unflagged findings.
- Correlation flag `house_context` (ADR 064): a relation explained by a presence
  entity of the residents. Groups and drivers reach the analyses through a
  domain-neutral context (`hacore.context`); Home Assistant is its first adapter.

### Changed

- Correlation significance v2 (ADR 062, `HAMMOND_CORRELATION_METHOD=v2`, default):
  variance of `r` from the autocorrelations of both series, an empirical null of
  circularly shifted pairs instead of Bonferroni over lags, and structural flags. On
  the synthetic households the share of false or unexplained findings drops several
  times; findings between autocorrelated but unrelated series disappear. Set
  `HAMMOND_CORRELATION_METHOD=v1` for the previous method. The next run replaces the
  findings of each window.
- Anomalies and change points v2 (ADR 062, `HAMMOND_ANOMALY_METHOD=v2`, default):
  conformal p-values of anomaly episodes against the installation's own baseline weeks
  and permutation p-values of change points (AR(1) surrogates), each with the
  Benjamini–Hochberg FDR over all series (`HAMMOND_ANOMALY_MAX_Q`, 0.05) instead of
  fixed thresholds per series. With many series far fewer false anomalies; in a very
  small installation only strong ones pass. Findings carry `p_value` and `q_value`.
  Set `HAMMOND_ANOMALY_METHOD=v1` for the previous method.

## [0.3.0] - 2026-11-24

### Added

- The label ids that leave entities out are settings: `HAMMOND_LABEL_NO_INGEST` and
  `HAMMOND_LABEL_NO_ANALYSIS` (defaults `hammond_no_ingest`, `hammond_no_analysis`).
- Sign-in with a Home Assistant account (`HAMMOND_AUTH_MODE=ha`, ADR 053) for the
  Claude connector and the admin GUI: HA administrators get `HAmmond.Admin`, other users
  `HAmmond.Reader` (`HAMMOND_HA_ROLE_MAP`, optional `HAMMOND_HA_ALLOWED_USERS`,
  `HAMMOND_HA_AUTH_URL`). See docs/setup/ha-login.md.
- Local access mode (`HAMMOND_ACCESS_MODE=local`, ADR 056/059): MCP and admin GUI only in
  the LAN behind Caddy's local CA (`HAMMOND_LOCAL_HOST`, `LAN_CIDR`), personal tokens
  issued and revoked on the new admin page **Tokens**, connect instructions for Claude
  Desktop, Claude Code and other MCP clients. See docs/setup/local-access.md.
- Claude Desktop extension `hammond.mcpb` (dependency-free stdio bridge): downloadable
  from the admin GUI with the server address filled in, and attached to releases.
- `deploy/compose/init-env.sh` creates `.env` with every internal password and key
  generated (ADR 061); `--fill` completes an existing `.env` after an update.
- Audit records carry the identity provider (`idp`: `entra`, `ha`, `token`); `whoami`
  shows it, `server_info` shows the access mode.

### Changed

- The Caddy image starts through `hammond-caddy`, which picks the configuration of
  `HAMMOND_ACCESS_MODE` and checks the values it needs. In compose, `ACME_EMAIL`,
  `CLOUDFLARE_API_TOKEN`, `CLAUDE_IP_RANGES` and `HAMMOND_PUBLIC_HOST` are no longer
  required by compose itself; Caddy refuses to start without them in the public mode.
  Upgrade: nothing to do, existing `.env` files keep the public mode.
- `postgres-init` adds the column `audit.tool_call.idp` and the schema `access` (personal
  tokens) to existing installations.

Upgrade from 0.2.0: take `compose.yaml`, `postgres/ensure-databases.sh` and the new
`init-env.sh` from the tag and the image lines from `hammond-0.3.0-images.env`.
Optionally run `./init-env.sh --fill` to add the new keys with their defaults (it never
changes existing values). An `.env` without the new keys keeps working: public access
with Entra ID as before.

## [0.2.0] - 2026-11-24

### Added

- Anomalies (unusual hours against the same hour of the week) and change points
  (lasting level shifts of daily means) of single entities in `catalog.finding`, run
  daily after the correlations (`HAMMOND_ANOMALIES_ENABLED`, `HAMMOND_ANOMALY_*`,
  `HAMMOND_CHANGEPOINT_*`).
- MCP tools `get_findings` (findings with entity names, trivial ones hidden by default)
  and `get_weekly_summary` (anomalies and change points of a week, correlations new or
  gone), both also for `HAmmond.Reader`.
- Dagster job `findings_weekly` (Monday 07:00) keeping weekly snapshots of the findings
  in `catalog.finding_weekly` (view `catalog_finding_weekly`, 104 weeks).

### Fixed

- Caddy answers refused requests with a short `text/plain` body (404 for unknown paths
  such as `/`, 403 for Claude-only endpoints and `/admin` from elsewhere); the empty
  response without a Content-Type made Safari offer it as a file download.

### Security

- Entities hidden from a role are also removed from the group lists (`entity_group`,
  `related_group`) of the findings it can see; before, a hidden entity could appear
  there as a near-duplicate of a visible one.

## [0.1.0] - 2026-11-23

### Added

- MCP server (FastMCP) for Claude with sign-in through Microsoft Entra ID (OAuth proxy),
  roles `HAmmond.Admin` and `HAmmond.Reader` from Entra app roles (#2).
- Public entry through Caddy: TLS via ACME DNS-01, OAuth endpoints open, MCP and token
  endpoints only from Claude's IP ranges (#4, #5).
- Data ingest from Home Assistant: live state stream, history and statistics backfill,
  bronze and silver layers in DuckLake on SeaweedFS (S3) and Postgres, Dagster jobs,
  retention (#6, #11, #12, #13).
- Entity catalog with drift detection and MCP data tools `search_catalog`,
  `describe_entity`, `list_views`, `get_timeseries`, `query_sql`; policy per role,
  SQL guard, read-only DuckDB lockdown and an audit log in Postgres (#14).
- Admin GUI with Entra sign-in and the Dagster UI behind it, reachable only from the
  admin network (#15).
- Correlations between entities (`catalog.finding`, MCP view `catalog_finding`),
  optional outside temperature from the Open-Meteo archive (#16, #18–#21).
- Home Assistant labels `hammond_no_ingest` and `hammond_no_analysis` exclude entities
  or devices from ingest and analysis (#21).
- Release management: SemVer tags, release workflow that promotes the tested images,
  signs them and publishes a GitHub release with pinned digests (#22).

### Changed

- Role `HAmmond.Reader` no longer sees state attributes; audit records are kept for
  90 days (`AUDIT_RETENTION_DAYS`) (#17).

[Unreleased]: https://github.com/xomtra/xomtra/compare/v0.10.0...HEAD
[0.10.0]: https://github.com/xomtra/xomtra/compare/v0.9.2...v0.10.0
[0.9.2]: https://github.com/xomtra/xomtra/compare/v0.9.1...v0.9.2
[0.9.1]: https://github.com/xomtra/xomtra/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/xomtra/xomtra/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/xomtra/xomtra/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/xomtra/xomtra/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/xomtra/xomtra/compare/v0.6.2...v0.7.0
[0.6.2]: https://github.com/xomtra/xomtra/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/xomtra/xomtra/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/xomtra/xomtra/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/xomtra/xomtra/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/xomtra/xomtra/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/xomtra/xomtra/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/xomtra/xomtra/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/xomtra/xomtra/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/xomtra/xomtra/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/xomtra/xomtra/releases/tag/v0.1.0
