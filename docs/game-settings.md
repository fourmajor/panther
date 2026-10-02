# Game settings

The game dashboard and Settings use the same authenticated catalog projection for every game.
Game name and system remain facts on the existing Game record; player identities, memberships,
character identities and image defaults remain separate. Catalog readers can inspect settings.
Only configured catalog editors can save them. Repository collaboration does not grant application
publishing permissions.

An optional `GameDescription` annotation lives at `GAME#<id>` / `DESCRIPTION`, with
`schemaVersion: 1`, nullable plain-text `description`, an opaque `revision`, and actor/time metadata.
An absent annotation projects as `description: null, descriptionRevision: null` for every game:
no historical description is invented. This introduces an optional annotation, without changing
or exempting existing required Game/asset schemas; no required-field backfill is needed.

`POST /game/settings` requires the proposed name/system/description plus the previously read
name/system/description revision and a unique operation ID. One DynamoDB transaction conditionally
updates the Game facts, replaces the description annotation, and creates an immutable versioned
`GameSettingsChange` audit entry. Each audit preserves the previous and new values. Concurrent
changes return 409 without partial writes. Retrying exactly the same operation is safe; reusing
its ID with different content fails. Settings never rewrite assets, player rosters or memberships.
Descriptions are plain text, limited to 2,000 characters, and are rendered as text.

Generation defaults retain the existing guarded `/game/style` operation and history. The UI
makes their scope explicit: future generated visuals, without rewriting uploaded or existing images.
Deploy the new JWT-authorized route through CDK together with the frontend and Lambda bundle.
Actual game settings and audit inventories stay in application storage, outside Git.
