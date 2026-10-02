# Manually authored novel chapters

The Novel page supports Add chapter and Edit chapter. Saving an edit creates a new
immutable edition and retains the earlier manuscript. References are optional,
explicit same-game finished assets; they do not turn fictional text into factual
transcription. Generation through the editorial worker remains a separate action.

`UserChapter` schema 1 contains `chapterId`, `gameId`, `title`, `markdown`,
`sourceKeys`, `seriesId`, `version`, and nullable `previousChapterId`. It is
human-authored and not reviewed; it never claims an editorial job or AI acceptance.
Each asset records semantic version metadata, non-applicable inference/cost, and
its exact input keys. The shared storage builder reserves its immutable location.
No previous content is overwritten. Existing generated chapters retain their
original contract, bytes and review provenance.

`POST /novel-chapters` accepts a complete envelope: gameId, title, markdown,
sourceKeys (at most 20), operationId (32 lowercase hex characters), and nullable
previousChapterId. The authenticated publisher API validates the registered game,
indexed same-game references, manuscript size and prior authored edition. Save the
exact operation after an uncertain result; repeating it is idempotent. Reusing an
operation ID with different content fails. A durable pending record retains the
server timestamp and exact manuscript before source publication. Completed records
pin the immutable asset checksum and remain available through `/novel-chapter`.

Materialized catalog projection recognizes UserChapter for bounded novel browsing,
book organization and illustration selections. The existing all-game catalog
rebuild and verification use the same projection; no page scans source storage.
This new contract introduces no historical records requiring a backfill. New
editions appear once their upload notification updates the catalog. Read-time
chapter validation checks the committed pointer and immutable bytes, independently
of editorial workflow status. Parent-edition links and the edition list expose
actual history.

The writer has create-only S3 permissions restricted to authored-chapter locations
and catalog reservations, metadata writes restricted to its chapter partition, and
read-only access to game and source catalogs. It cannot dispatch workflows, call
models, alter editorial jobs, or overwrite other assets. CDK owns provisioning.
