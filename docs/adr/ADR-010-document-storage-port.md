# ADR-010 - Document Storage Port

## Context

Rotta will store sensitive business documents such as CNH, CRLV, company documents, insurance files, photos, proof of delivery, and transport documents.

## Decision

Model document storage as a port. The local filesystem adapter is only the development/default adapter. Future adapters may use S3, MinIO, or another compatible object storage.

## Consequences

Domain and application code should not depend directly on S3, MinIO, or filesystem details. Private business documents must not depend on permanent public URLs and should be private by default.
