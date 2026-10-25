#!/usr/bin/env bun
/**
 * Parse the YAML frontmatter of every agent file and report failures.
 *
 * OpenCode's loader is lenient about a few things (e.g. `description:` values
 * containing ": "), but a strict YAML parser is a good tripwire for typos that
 * would silently produce a wrong config.
 *
 * Usage: bun check_frontmatter.ts [file-or-dir ...]
 * Default: <config>/agents relative to this script (../../agents).
 */
import { readdirSync, readFileSync, statSync } from "node:fs"
import path from "node:path"

const here = path.dirname(new URL(import.meta.url).pathname)
const defaultDir = path.resolve(here, "..", "..", "..", "agents")

const targets = process.argv.slice(2)
const files: string[] = []

function collect(p: string) {
  const st = statSync(p)
  if (st.isDirectory()) {
    for (const name of readdirSync(p)) {
      if (name.endsWith(".md")) files.push(path.join(p, name))
    }
  } else {
    files.push(p)
  }
}

for (const target of targets.length ? targets : [defaultDir]) collect(target)

let failed = 0
for (const file of files) {
  const text = readFileSync(file, "utf8")
  const match = /^---\n([\s\S]*?)\n---/.exec(text)
  if (!match) {
    console.log(`✗ ${file}: sem frontmatter`)
    failed++
    continue
  }
  try {
    const doc = Bun.YAML.parse(match[1]!) as Record<string, unknown>
    const perm = doc.permission as Record<string, unknown> | undefined
    const rules = doc.permissions as unknown[] | undefined
    const keys = Object.keys(doc).join(",")
    const mode = typeof doc.mode === "string" ? doc.mode : "?"
    const permissions = rules
      ? `${rules.length} regra(s) V2`
      : perm
        ? `V1: ${Object.keys(perm).join(",")}`
        : "—"
    const v2Marker = ["permissions", "system", "request", "disabled"].some((k) => k in doc)
    const v1Fields = ["name", "permission", "tools", "temperature", "maxSteps", "disable"].filter(
      (k) => k in doc,
    )
    const mixed = v2Marker && v1Fields.length > 0
    console.log(
      `✓ ${file}\n  mode=${mode} keys=${keys}\n  permission=${permissions}` +
        (mixed ? `\n  ⚠ mistura V1/V2: campos V1 ignorados (${v1Fields.join(",")})` : ""),
    )
  } catch (err) {
    const message = (err as Error).message.split("\n")[0]
    console.log(`✗ ${file}: YAML inválido — ${message}`)
    failed++
  }
}

if (failed) {
  console.log(`\n${failed} arquivo(s) com problema.`)
  process.exit(1)
}
