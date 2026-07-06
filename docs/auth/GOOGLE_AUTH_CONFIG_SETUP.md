# Google OAuth Config Setup

## Scope

This document prepares SpaManager for Google OAuth configuration behind a feature flag.

Google OAuth login/callback routes are not implemented in this task.

## Default behavior

- `GOOGLE_AUTH_ENABLED=false` by default.
- Google OAuth remains disabled until the feature flag is explicitly enabled.
- Existing login and owner approval flows continue unchanged.

## Required environment variables

When Google OAuth is enabled later, configure:

- `GOOGLE_AUTH_ENABLED=true`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`

Optional values:

- `GOOGLE_ALLOWED_DOMAIN`
- `GOOGLE_DISCOVERY_URL`
- `GOOGLE_SCOPES`

## Safety rules

- Do not commit real client IDs or client secrets.
- Do not enable the feature flag in production before the OAuth routes are implemented and tested.
- Keep the default disabled state in local, test, and production environments until the feature is ready.

## Validation helper

The config layer exposes a validation helper that can report missing Google OAuth credentials when the feature flag is on.

That helper is intended for future readiness checks, not for automatic route activation.
