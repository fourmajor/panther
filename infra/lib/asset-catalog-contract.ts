/** IAM scopes must move with the runtime's versioned, all-game catalog migration. */
export const assetCatalogVersion = 5;
export const assetCatalogSections = ["all", "audio", "transcripts", "videos", "novels", "sessions"] as const;
type Section = typeof assetCatalogSections[number];

export function assetCatalogPartitions(...sections: Section[]): string[] {
  return sections.map(section => `v${assetCatalogVersion}#*#${section}`);
}
