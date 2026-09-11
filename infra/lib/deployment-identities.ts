import * as fs from "node:fs";
import * as path from "node:path";

/** Deployment data, never a checked-in roster or a source of fictional production defaults. */
export interface DeploymentIdentities {
  schemaVersion: 1;
  users: string[];
  publishers: string[];
  workers: string[];
  migrationAdmins: string[];
}

export function validateIdentities(value: unknown): DeploymentIdentities {
  const v = value as DeploymentIdentities;
  const keys = ["schemaVersion", "users", "publishers", "workers", "migrationAdmins"];
  if (!v || typeof v !== "object" || Object.keys(v).sort().join() !== keys.sort().join() || v.schemaVersion !== 1) {
    throw new Error("Invalid private identity configuration schema");
  }
  for (const key of ["users", "publishers", "workers", "migrationAdmins"] as const) {
    const names = v[key];
    if (!Array.isArray(names) || !names.length || names.length > 100 || new Set(names).size !== names.length ||
        names.some(n => typeof n !== "string" || !/^[a-zA-Z0-9_-]{1,64}$/.test(n))) {
      throw new Error(`Invalid private identity configuration: ${key}`);
    }
    if (key !== "users" && names.some(n => !v.users.includes(n))) {
      throw new Error(`Private identity capability refers to an unconfigured account: ${key}`);
    }
  }
  return v;
}

export function loadIdentities(account: string, file?: string): DeploymentIdentities {
  if (!file) {
    // The non-deployable account is reserved for isolated CI synthesis only.
    if (account === "000000000000") return validateIdentities({schemaVersion:1,
      users:["example-operator", "example-editor", "example-member"],
      publishers:["example-operator", "example-editor"], workers:["example-operator"],
      migrationAdmins:["example-operator"]});
    throw new Error("Set PANTHER_IDENTITIES_FILE to a private JSON file outside the repository before synthesis/deployment");
  }
  const resolved = fs.realpathSync(file);
  const repo = fs.realpathSync(path.resolve(__dirname, "../../.."));
  const relative = path.relative(repo, resolved);
  if (relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative))) {
    throw new Error("Private identity configuration must be outside the repository");
  }
  const stat = fs.statSync(resolved);
  if (!stat.isFile() || stat.size > 64000 || (stat.mode & 0o077)) {
    throw new Error("Private identity configuration must be a small owner-only file (chmod 600)");
  }
  return validateIdentities(JSON.parse(fs.readFileSync(resolved, "utf8")));
}
