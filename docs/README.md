# Rotta 116 Documentation

Use this index to distinguish **current living documentation** from **historical decisions/audits**.

## Living Documentation

- `architecture/current-state.md` — implemented architecture and next structural boundary.
- `api/conventions.md` — API-wide rules.
- `api/v1.md` — current versioned API surface.
- `domain/identity-access.md` — user/membership/RBAC/driver ownership.
- `domain/supply-side.md` — carriers, drivers, vehicles, route preferences.
- `domain/freight-operations.md` — freight marketplace, operations, multi-stop, POD, tracking and thermal separation.
- `domain/transport-glossary.md` — current canonical terminology.
- `domain/operational-discovery.md` — discovery questions for real logistics operations.
- `domain/public-site.md` — public-site claims and editorial boundaries.
- `audits/mvp_gap_analysis.md` — current living technical gap analysis.

## Historical Architectural Decisions

`adr/` contains dated architectural decisions. ADR context/consequences may use future tense because they record what was known when the decision was made. Do not rewrite their original rationale to match today's implementation; append implementation-status notes instead.

## Historical Editorial Audit

The top-level `auditoria-editorial/` folder is an editorial/template audit snapshot. It contains source-template findings and historical planning material, including references to Cargon demo text. It is **not** the source of truth for current product capability.

## Source-Of-Truth Order

When documents disagree:

1. current implemented code and database constraints.
2. automated tests.
3. living documentation listed above.
4. ADRs for decision rationale.
5. historical audits/roadmaps.
