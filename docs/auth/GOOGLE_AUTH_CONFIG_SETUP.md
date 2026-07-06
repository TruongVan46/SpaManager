# Google OAuth Config Setup

## Scope

This document prepares SpaManager for Google OAuth configuration behind a feature flag.

Google OAuth start and callback routes are available as a safe skeleton. They do not create users, do not log users in, and do not activate Google accounts yet.

## Default behavior

- `GOOGLE_AUTH_ENABLED=false` by default.
- Google OAuth remains disabled until the feature flag is explicitly enabled.
- Existing login and owner approval flows continue unchanged.
- The login page hides the Google button unless the feature flag and config are valid.
- `GET /auth/google/start` redirects to Google only when the feature flag and OAuth client are available.
- `GET /auth/google/callback` handles disabled/error/skeleton states safely.
- The callback does not create a SpaManager user yet.
- The future Google user creation flow must create pending users for owner approval.

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
- Do not enable the feature flag in production before the full OAuth user creation and owner approval flow is implemented and tested.
- Keep the default disabled state in local, test, and production environments until the feature is ready.

## Validation helper

The config layer exposes a validation helper that can report missing Google OAuth credentials when the feature flag is on.

That helper is intended for future readiness checks, not for automatic route activation.

When the feature is enabled with valid config, the OAuth client is initialized safely in app startup. Local environments without Authlib still fail safe when Google auth is disabled.
