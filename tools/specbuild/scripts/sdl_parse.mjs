#!/usr/bin/env node
/**
 * MPEG SDL parser shim for SpecBuild.
 *
 * Reads a JSON array of {id, content} blocks from stdin, parses each via
 * the @mpeggroup/mpeg-sdl-parser, and writes a JSON array of
 * {id, errors: [...]} to stdout.
 *
 * Invoked by specbuild/checks/sdlsyntax.py.  Run independently with:
 *
 *   echo '[{"id":"x","content":"int(8) foo;"}]' | node scripts/sdl_parse.mjs
 */

import { readFileSync } from "node:fs";

let parserModule;
try {
  parserModule = await import("@mpeggroup/mpeg-sdl-parser");
} catch (err) {
  process.stderr.write(
    `[sdl_parse] Failed to import @mpeggroup/mpeg-sdl-parser: ${err.message}\n` +
    `[sdl_parse] Run \`npm install\` in the SpecBuild root.\n`,
  );
  process.exit(2);
}

const { createLenientSdlParser, SdlStringInput, collateSyntaxErrors } = parserModule;

if (!createLenientSdlParser || !SdlStringInput || !collateSyntaxErrors) {
  process.stderr.write(
    "[sdl_parse] @mpeggroup/mpeg-sdl-parser is missing expected exports " +
    "(createLenientSdlParser / SdlStringInput / collateSyntaxErrors).  " +
    `Got: ${Object.keys(parserModule).join(", ")}\n`,
  );
  process.exit(3);
}

let stdinText;
try {
  stdinText = readFileSync(0, "utf-8");
} catch (err) {
  process.stderr.write(`[sdl_parse] Failed to read stdin: ${err.message}\n`);
  process.exit(4);
}

let blocks;
try {
  blocks = JSON.parse(stdinText);
} catch (err) {
  process.stderr.write(`[sdl_parse] Invalid JSON on stdin: ${err.message}\n`);
  process.exit(5);
}

if (!Array.isArray(blocks)) {
  process.stderr.write("[sdl_parse] Input must be a JSON array of {id, content} objects.\n");
  process.exit(6);
}

const parser = await createLenientSdlParser();

const results = [];
for (const block of blocks) {
  const id = block?.id ?? "<unknown>";
  const content = block?.content ?? "";
  if (!content.trim()) {
    results.push({ id, errors: [] });
    continue;
  }
  try {
    const input = new SdlStringInput(content);
    const tree = parser.parse(input);
    const parseErrors = collateSyntaxErrors(tree, input) ?? [];
    // Normalize error shape — the parser may return different fields
    // across versions.  We keep raw fields and add a stable subset.
    const normalized = parseErrors.map((e) => {
      // v4: { errorMessage, location: {row, column, position}, errorLine }.
      // Older versions used flat `line`/`column` or `message` fields.
      const line =
        e?.location?.row ??
        e?.line ??
        e?.lineNumber ??
        e?.row ??
        e?.location?.line ??
        null;
      const column =
        e?.location?.column ?? e?.column ?? e?.columnNumber ?? null;
      // Prefer `errorMessage` (v4); fall back to `message` / `text`.
      let message = e?.errorMessage ?? e?.message ?? e?.text ?? String(e);
      // Strip the parser's trailing token-and-location summary if present
      // (older versions appended "... => { row: N, column: M, ... }").
      message = message.replace(/\s*=>\s*\{[^}]*\}\s*$/, "").trim();
      const sourceLine = e?.errorLine ?? null;
      return { line, column, message, sourceLine };
    });
    results.push({ id, errors: normalized });
  } catch (err) {
    results.push({
      id,
      errors: [{ line: null, column: null, message: `parser threw: ${err.message ?? err}`, raw: null }],
    });
  }
}

process.stdout.write(JSON.stringify(results));
