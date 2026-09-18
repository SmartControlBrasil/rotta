# ADR-008 - Mobile Flutter

## Context

Rotta will include a mobile app experience for Android and iOS, especially for driver-facing workflows, field operations, offline actions, and future tracking-related capabilities.

## Decision

Use Flutter/Dart as the primary technology for the Android and iOS application. Native Kotlin on Android or Swift on iOS may be used when a platform-specific integration requires it.

## Consequences

Rotta Mobile is an official client adapter and must communicate with the Django backend through explicit API interfaces. Flutter code is not part of this Django foundation stage, and Flutter must not dictate domain rules, persistence, RBAC, or audit architecture.
## Implementation Status — 2026-08-22

This decision is implemented. The Flutter driver application exists under `apps/rotta_driver/` and consumes the versioned Django API for driver operations, tracking, POD and related workflows. Flutter remains a client adapter and does not own backend domain rules.
