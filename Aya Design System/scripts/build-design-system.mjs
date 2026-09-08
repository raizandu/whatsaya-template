import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const cssPath = join(root, "colors_and_type.css");
const bundlePath = join(root, "_ds_bundle.js");
const css = readFileSync(cssPath, "utf8");

execFileSync(
  "npx",
  [
    "-y",
    "esbuild@0.28.2",
    join(root, "scripts/bundle-entry.jsx"),
    "--bundle",
    "--format=iife",
    "--platform=browser",
    "--target=es2020",
    `--outfile=${bundlePath}`,
  ],
  { cwd: root, stdio: "inherit" },
);

function walk(directory, extension) {
  return readdirSync(directory)
    .flatMap((name) => {
      const path = join(directory, name);
      return statSync(path).isDirectory() ? walk(path, extension) : [path];
    })
    .filter((path) => path.endsWith(extension));
}

function hash(contents, length = 12) {
  return createHash("sha256").update(contents).digest("hex").slice(0, length);
}

function attributes(source) {
  return Object.fromEntries(
    [...source.matchAll(/([\w-]+)="([^"]*)"/g)].map((match) => [
      match[1],
      match[2],
    ]),
  );
}

function cardFrom(path) {
  const source = readFileSync(path, "utf8");
  const marker = source.match(/<!--\s*@dsCard\s+([^]*?)-->/);
  if (!marker) return null;
  const metadata = attributes(marker[1]);
  return {
    path: relative(root, path),
    group: metadata.group,
    viewport: metadata.viewport,
    subtitle: metadata.subtitle,
    name: metadata.name,
  };
}

function declarations(block, scope) {
  return [...block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map((match) => {
    const name = match[1];
    const value = match[2].trim();
    const kind = name.startsWith("--font-") || name.startsWith("--text-")
      ? "font"
      : name.startsWith("--radius")
        ? "radius"
        : name.startsWith("--shadow")
          ? "shadow"
          : name.startsWith("--fw-")
            ? "other"
            : "color";
    return {
      name,
      value,
      kind,
      definedIn: "colors_and_type.css",
      ...(scope ? { scope } : {}),
    };
  });
}

function block(selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return css.match(new RegExp(`${escaped}\\s*\\{([^]*?)\\n\\}`))?.[1] ?? "";
}

const light = block(":root, .light");
const dark = block(".dark");
const whatsapp = block(".whatsapp");
const darkWhatsapp = block(".dark.whatsapp");
const tokens = [
  ...declarations(light),
  ...declarations(dark, ".dark"),
  ...declarations(whatsapp, ".whatsapp"),
  ...declarations(darkWhatsapp, ".dark.whatsapp"),
];

const fonts = [...css.matchAll(/@font-face\s*\{([^}]+)\}/g)].map((match) => {
  const body = match[1];
  const family = body.match(/font-family:\s*'([^']+)'/)?.[1];
  const weight = body.match(/font-weight:\s*(\d+)/)?.[1];
  const file = body.match(/url\('([^']+)'\)/)?.[1];
  return {
    family,
    weight,
    style: "normal",
    cssPath: "colors_and_type.css",
    files: [file],
  };
});

const jsxFiles = walk(join(root, "ui_kits"), ".jsx");
const sourceHashes = Object.fromEntries(
  jsxFiles.map((path) => [relative(root, path), hash(readFileSync(path, "utf8"))]),
);
const namespace = `AyaDesignSystem_${hash(css + JSON.stringify(sourceHashes), 6)}`;
const htmlFiles = [
  ...walk(join(root, "preview"), ".html"),
  ...walk(join(root, "ui_kits"), ".html"),
];

const manifest = {
  namespace,
  components: [],
  startingPoints: [],
  cards: htmlFiles.map(cardFrom).filter(Boolean).sort((a, b) => a.path.localeCompare(b.path)),
  templates: [],
  globalCssPaths: ["colors_and_type.css"],
  tokens,
  themes: [
    { selector: ".dark", label: "Dark" },
    { selector: ".whatsapp", label: "WhatsApp" },
    { selector: ".dark.whatsapp", label: "Dark WhatsApp" },
  ],
  fonts,
  brandFonts: [
    { family: "Aya", status: "ok", tokens: ["--font-display"], path: "colors_and_type.css" },
    { family: "Open Sans", status: "ok", tokens: ["--font-sans"], path: "colors_and_type.css" },
    { family: "Geist", status: "ok", tokens: ["--font-numeric"], path: "colors_and_type.css" },
  ],
  source: "spa",
};

writeFileSync(join(root, "_ds_manifest.json"), `${JSON.stringify(manifest)}\n`);

let bundle = readFileSync(bundlePath, "utf8");
const bundleMetadata = {
  format: 3,
  namespace,
  components: [],
  sourceHashes,
  inlinedExternals: [],
  unexposedExports: [],
};
const bundleHeader = `/* @ds-bundle: ${JSON.stringify(bundleMetadata)} */`;
bundle = bundle.match(/^\/\* @ds-bundle: .* \*\//)
  ? bundle.replace(/^\/\* @ds-bundle: .* \*\//, bundleHeader)
  : `${bundleHeader}\nwindow.${namespace} = window.${namespace} || {};\n${bundle}`;
bundle = bundle.replace(/AyaDesignSystem_[A-Za-z0-9_]+/g, namespace);
writeFileSync(bundlePath, bundle);

console.log(`Built ${relative(process.cwd(), join(root, "_ds_manifest.json"))}`);
console.log(`Updated bundle namespace to ${namespace}`);
