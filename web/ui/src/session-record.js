/** The list card and the detail recap use the cards projection, then the record itself. */
export function recapInputs(record, card) {
  if (card && (card.excerptKey || card.excerptLabel)) {
    return {excerptKey: card.excerptKey || null, excerptLabel: card.excerptLabel || null};
  }
  return {excerptKey: record?.excerptKey || null, excerptLabel: record?.excerptLabel || null};
}
