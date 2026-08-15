# Identity And Access

This document records current identity and authorization concepts for future modules.

## Concepts

- User: authentication identity. A user can log in, but does not by itself define all business access.
- Organization: company or participant represented in Rotta.
- Membership: relationship between a user and an organization, optionally scoped to business unit, branch, department, or team.
- Role: named bundle of permissions assigned through membership.
- Permission: stable code representing an allowed capability, such as `organizations.view`.
- AccessScope: data boundary for a permission, such as `COMPANY`, `BRANCH`, `TEAM`, `OWN`, or `NONE`.

## Distinctions

Authentication != Authorization.

Authentication proves who the user is. Authorization decides what that user can do.

Permission != Scope.

A permission grants a capability. A scope limits where or over which records that capability applies.

User != Membership.

A user may belong to multiple organizations. Organization-specific access must be modeled through memberships, not hardcoded on the user record.
