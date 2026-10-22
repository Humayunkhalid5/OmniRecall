# Beta program

How the 0.1 beta collects feedback and decides what to fix (implementation plan, Phase 7).

## What we collect

Only what a tester chooses to send. OmniRecall has no telemetry, crash reporting, or analytics, and the beta does not add any.

- **Problem reports** (Settings → Report a problem): the app version, OS name and version, CPU architecture, counts of items by state, failed items by source type and error code, job and queue counts, which models are installed, index and storage sizes, which capture sources are on, the number of exclusions (not the rules), and up to 40 recent warnings from the engine log, filtered again to codes, counts, and durations (`omnirecall/diagnostics.py`). It never contains captured text, queries, file names or paths, app names, exclusion rules, or item IDs; `tests/test_diagnostics.py` checks this with marker content. The app shows the report in full before anything else happens, and only copies it, saves it to a file the tester names, or opens the issue page in the browser. Nothing is uploaded by the app.
- **Issues** on GitHub, through the templates in `.github/ISSUE_TEMPLATE/`, which ask testers to describe problems without their content.
- **Security and privacy vulnerabilities**, privately (`SECURITY.md`).

## Triage order

Every new issue gets `needs-triage`. It is then labeled with a priority from `bugs.md`:

1. **Data loss** (something saved is missing, a database or export cannot be read) and **privacy** (anything captured or kept that should not have been, content in a log, report, or network traffic): P0. Fixed before any other work, with a regression test, and released as a new beta.
2. **Crashes** and an engine that will not start: P0 if it affects many testers or loses data, otherwise P1.
3. **Incorrect sources** (a result that points to the wrong item, file, or time in a recording): P1.
4. Everything else, including new features: after the above, by how many testers it affects.

Confirmed bugs are recorded in `bugs.md` with the template there. Feature requests wait until there are no open P0 or P1 issues (implementation plan, Phase 7).

## Releases

A beta release is a `v*` tag. The release workflow builds and checks every installer and creates a draft pre-release with the installers, `SHA256SUMS.txt`, an SBOM (`omnirecall-sbom.cdx.json`), and build provenance; a maintainer reviews it and publishes it (`release.md`).
