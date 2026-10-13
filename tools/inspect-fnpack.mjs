#!/usr/bin/env node
// Narrow scan: JSON field tags near wizard struct definitions.
import fs from "node:fs";

const buf = fs.readFileSync("e:/Project/FN/All-in-OneOffice/.tools/fnpack.exe");
const s = buf.toString("latin1");
const candidates = [
  "stepTitle", "steptitle", "items", "itemtype", "field", "fields", "label", "labels",
  "required", "requiredMessage", "required_message", "initValue", "init_value", "default",
  "options", "tips", "pages", "steps", "rules", "window", "name", "placeholder", "title",
  "validate", "regex", "min", "max", "description", "key", "value", "uninstall_ui",
];
const hits = new Set();
for (const c of candidates) {
  // json:"xxx" tags
  const re = new RegExp(`json:"[a-zA-Z_,]*${c}[a-zA-Z_,]*"`, "g");
  for (const m of s.matchAll(re)) hits.add(m[0]);
}
console.log([...hits].sort().join("\n"));
