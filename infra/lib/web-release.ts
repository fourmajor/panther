import { createHash } from "node:crypto";

/** Content-addressed browser files; the HTML and release manifest are revalidated. */
export function webRelease(html: string, assets: Record<string, string>) {
  const files: Record<string, string> = {};
  for (const [name, content] of Object.entries(assets)) {
    const digest = createHash("sha256").update(content).digest("hex").slice(0, 20);
    const versioned = name.replace(/(\.[^.]+)$/, `.${digest}$1`);
    files[versioned] = content;
    html = html.replaceAll(`"/${name}"`, `"/${versioned}"`);
  }
  const version = createHash("sha256").update(html).digest("hex");
  html = html.replace("</head>", `<meta name="panther-release" content="${version}">\n  </head>`);
  return { files, html, version, manifest: JSON.stringify({ version }) };
}
