# Rotta Driver

Flutter driver application for Rotta 116.

The app is an operational client of the Django `/api/v1/` backend. Domain rules, RBAC, operation state transitions, multi-stop sequencing, tracking validation and POD rules remain backend responsibilities.

## Platforms

- Android — current rollout priority.
- iOS — maintained by the same Flutter project.

Application identifier:

```text
br.com.rotta116.driver
```

## Current Functional Scope

The project includes application flows/integration for:

- authentication/session handling.
- driver profile/capabilities.
- assigned FreightOperations.
- operation detail.
- operational state advancement.
- incidents.
- Proof of Delivery.
- GPS tracking.
- driver preferences/route intents.

The backend now supports multi-stop operational stops and POD per delivery stop; Flutter screens/contracts should consume the operational stop list returned by the API rather than reconstruct stops from commercial request data.

## Backend Contract

Base API:

```text
/api/v1/
```

See:

- `../../docs/api/v1.md`
- `../../docs/api/conventions.md`

The mobile client must tolerate network retries and preserve `client_event_id`/sequence identifiers where the API contract uses them.

## Design Direction

The primary visual reference for the driver app is the approved `flutter01` package. `flutter02` is complementary and should only contribute components/patterns that do not dilute the main logistics identity.

## Architecture Rules

- Do not embed server business rules in Flutter.
- Do not allow arbitrary status changes not supported by backend transitions.
- Do not grant broader roles to make a screen work; use `DRIVER` capabilities and ownership.
- Do not persist sensitive tokens in insecure storage.
- GPS retry must not rely on timestamp-only deduplication.
- Temperature telemetry, when exposed to mobile/device workflows, remains distinct from GPS tracking.

## Development

Typical commands:

```bash
flutter pub get
flutter analyze
flutter test
flutter run
```

Android builds should be validated before release without committing signing secrets.
