# Shared dialog contract

Use the standard React/Radix Dialog primitives in `web/ui/src/components/ui/dialog.jsx`.
Existing imperative views use `DOMDialog` through `PantherUI.createDialog` or
`enhanceDialog`; they must not introduce native dialogs, alternate close widgets,
manual focus traps, or per-screen footer skins.

`DialogContent` has four presentation variants:

- `form` (default): padded content, shared header and form footer.
- `content`: padded read-only content; no form footer is implied.
- `media`: compact header, edge-to-edge media, and a subtle Download link below
  the media at the right. Generation details retain the same content gutter.
- `recording`: padded recording controls. Closing the dialog does not stop recording.

Content gutters are 24px on desktop and 16px on mobile. Every dialog has one
borderless Lucide X close control with a 44×44px hit area in its top-right header.
Long titles wrap with space reserved for that control. A footer Close action does
not replace the header X. Existing dedicated header-close handlers are retained
by the DOM adapter, which applies the same `dialog-close` slot.

Forms use `DialogFooter` with the `dialog-footer` slot: transparent background,
no divider or full-width colored strip, a 16px gap above the actions, and
right-aligned buttons. Cancel uses the shared outline Button variant. Actions use
the shared 36px Button size, including during pending and retry states. Upload
retains the application's outline Upload convention. The DOM adapter applies
these slots to existing form action rows and retains their event handlers.

A long form needs a scrollable body and an unobstructed footer, not a sticky strip
painted over the content. ChapterEditor demonstrates this composition. Media
previews and progress displays must not acquire a form footer just to match a form.

Radix owns portal placement, keyboard dismissal, nested popover/select handling,
and focus restoration. Verify the actual close/action hit areas and viewport
bounds at desktop and mobile widths; do not force clicks or programmatically
scroll a hidden action to claim accessibility. The dialog-consistency browser
suite checks these contracts against actual local application forms.

## Library controls and generation

Assets and Episodes use `LibrarySearchFilters`: the same standard Input search
row and inline-label MultiSelect composition for Tags and Characters. Selected
chips remain inside their controls; Radix and cmdk own selection, keyboard
matching and popup behavior. Do not recreate these fields in imperative markup.

Assets uses `GenerateAssetMenu`, composed from the standard Radix/shadcn
DropdownMenu. Its choices come from server capabilities. Selecting a type opens
a specific `Generate Map`, `Generate Video`, `Generate Speech` or other supported
dialog with that type fixed and only the relevant model inputs. Upload remains
a separate form. Frozen submissions and their cache keys include the selected
type so an uncertain request cannot be replayed as a different media operation.
