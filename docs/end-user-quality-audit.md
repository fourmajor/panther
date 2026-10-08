# End-user quality audit

Treat these stories as application acceptance criteria, not a list of pages that
merely load. Exercise actual persisted records, keyboard input, reloads, cancelled
edits, failed requests and desktop/mobile layouts. Never spend on generation just
to make a test fixture look functional.

## Stories and regression coverage

| User story | Acceptance / coverage |
| --- | --- |
| I can select a game and keep other games' content separate. | `games`, `development`, data-layer tests; current game scopes reads and mutations. |
| I can find recent characters, chapters and episodes from Home. | `end-user-audit`: real creations, actual dashboard links and durable destinations. |
| I can create a character and find it after reloading. | `end-user-audit`, `character-details`, `appearance-history`. |
| I can view selected portraits, earlier appearances and a usable model. | `development`, `appearance-history`, `viewer`; visual model quality is a separate production gate. |
| I can record safely, close its dialog, and reopen the controls. | `browser-recording`: synthetic capture, no physical microphone or paid provider calls. |
| I can find both original and corrected session transcripts. | `session-library`, real uploaded transcript in `end-user-audit`. |
| I can read, search and download text without reading JSON. | `session-library`, `end-user-audit`; unidentified speech is explicitly labeled and searchable. |
| A direct transcript link opens even while library thumbnails load. | `end-user-audit`: real 3,052-segment upload, twelve synthetic portraits, gateway 503/429 responses, readable viewer and complete text download. Browser GETs are bounded to three concurrent requests, with opened previews prioritized. |
| Temporary gateway throttling recovers without repeating a paid operation. | `data-layer` and `end-user-audit`: GET-only bounded retries; upload POST failures remain one request and require explicit user retry. |
| A failed session listing does not force me to reload the application. | `end-user-audit`: in-place retry of the exact listing request. |
| A playback request failure does not silently erase the recording. | `end-user-audit`: visible error, retained download, explicit playback retry. |
| A transient summary failure does not hide the transcript. | `end-user-audit`: read-only retry; no generation POST. |
| I can upload, find and reopen a file after reloading. | `end-user-audit`: real file bytes and SQLite persistence; `assets-browser` covers filters and previews. |
| I can recover an interrupted asset listing without losing my search. | `end-user-audit`: in-place retry preserving component state. |
| I can write and revisit a chapter. | `end-user-audit`, `novel`, `editorial-creation`; no paid inference required for authored chapters. |
| I can create an episode and ordered scenes without generating media. | `end-user-audit`, `session-library`, `movie-review`. |
| Cancelling scene edits leaves the saved scene unchanged. | `end-user-audit`, `session-library`. |
| I can inspect workflow types, runs and stage details. | `workshop`; actual local projections exercised in `end-user-audit`. |
| A workflow service failure or broken deep link is not a dead end. | `end-user-audit`: explicit retry and a back link even while detail fails. |
| I can understand failed/review-needed notifications and retain read history. | `notifications`; synthetic identities and events only. |
| I can use controls on a phone and with a keyboard. | Each relevant browser suite covers narrow and desktop viewports; inspect screenshots and real hit areas, not forced clicks. |

## Execution and limits

`end-user-audit.spec.cjs` starts the real loopback API with a new temporary SQLite
database, seeds fictional development records explicitly, and performs real browser
writes/reads. This is an intentionally API-only diagnostic environment: paid
processors are not started, and unavailability must remain honest. Only designated
network interruptions are injected; successful CRUD responses come from the API.

Run browsers inside the owned Docker runner. After focused discovery and repairs,
the manually dispatched full CI run must pass on the PR's exact SHA. Review desktop
and mobile screenshots. Private hosted inventories, real users, credentials and
campaign media must not enter the runner or its artifacts.

A passing suite is not proof that every deployed provider job, browser or campaign
record is healthy. Verify the deployed release and authenticated hosted reads
separately. Keep production-generation failures and model visual quality distinct
from app usability, and do not mark unavailable or failed outputs as complete.
