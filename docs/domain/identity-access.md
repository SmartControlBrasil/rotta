# Identity And Access

This document records the implemented identity, RBAC and organizational-access model used by current Rotta 116 modules.

## Concepts

- **User**: authentication identity. A user may belong to multiple organizations.
- **Organization**: company/institutional participant and primary tenant boundary.
- **Membership**: relationship between a user and an organization, optionally scoped through business-unit/branch/department/team structures.
- **Role**: named bundle of permissions assigned through membership.
- **Permission**: stable capability code.
- **AccessScope**: boundary applied to a permission, such as `COMPANY`, `BRANCH`, `TEAM`, `OWN` or `NONE` where supported.
- **Driver profile**: business identity of a driver. A driver may be linked to a `User`, but `User` and `Driver` are not the same domain concept.

## Distinctions

Authentication != Authorization.

Authentication proves who the user is. Authorization determines which business actions/data are allowed.

Permission != Scope.

A permission grants a capability. A scope constrains where/over which data the capability applies.

User != Membership.

Organization-specific access belongs in memberships and permission grants, not in hardcoded global user flags.

User != Driver.

The mobile authentication account is linked to a driver profile, while operational ownership is enforced through the driver assigned to the `FreightOperation`.

## Driver Role

`RoleCode.DRIVER` contains only the minimum operational permissions required by the current mobile workflow:

```text
FREIGHT_OPERATIONS_VIEW
FREIGHT_OPERATIONS_CHANGE_STATUS
FREIGHT_OPERATIONS_REPORT_INCIDENT
FREIGHT_OPERATIONS_RECORD_POD
TRACKING_VIEW
TRACKING_START
TRACKING_RECORD
TRACKING_END
```

These permissions do **not** grant administrative rights over drivers, vehicles, organizations, users or other drivers' operations.

Ownership remains a separate mandatory condition.

## Fail-Closed Access

Cross-tenant and cross-driver access must fail closed. Where appropriate, interfaces return a not-found response rather than disclose the existence of an inaccessible resource.

Application services and scoped query helpers are the preferred enforcement points; templates and Flutter must not implement the canonical authorization rules.
