# Security policy

## Project status

`administrative-agent` is a research prototype. It is not a production service and has no
supported production release. Do not process real employee, customer, calendar, or financial
data with it.

## Reporting a vulnerability

Please do not disclose a suspected vulnerability in a public issue. Use GitHub's private
vulnerability reporting option on the repository's **Security** tab. Include the affected
component, reproduction steps, and the likely impact. Reports about exposed credentials
should identify the file and commit without copying the credential into the report.

## Credentials

The application reads local credentials from `.env` and `secrets/`. Both locations are
excluded from Git. If a real credential is ever committed, revoke it first. Removing it from
the latest commit is not enough because Git history remains available.
