#!/usr/bin/env node
/**
 * 离线编译 Tailwind CSS v4：
 * - 优先复用 apps/front 的 @tailwindcss/node 与 tailwindcss 包（仓库内已安装）；
 * - 自动扫描 static/、plugins/、src/ 下文本文件中的字符串字面量作为候选类名；
 * - 输出 static/css/tailwind.css，运行时零依赖。
 */
import { mkdirSync, readFileSync, readdirSync, statSync, watch, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const projectRoot = fileURLToPath(new URL("../", import.meta.url));
const frontRoot = fileURLToPath(new URL("../../front/", import.meta.url));

function resolveNodePackage(name) {
  for (const base of [frontRoot, projectRoot]) {
    try {
      return require.resolve(name, { paths: [base] });
    } catch {
      // 尝试下一个 base
    }
  }
  // pnpm 虚拟 store：@tailwindcss/node 未软链到顶层时直接定位
  const pnpmRoot = join(frontRoot, "node_modules", ".pnpm");
  const scoped = name.startsWith("@") ? "@" + name.slice(1).replace("/", "+") : name;
  try {
    const entries = readdirSync(pnpmRoot);
    const candidates = entries
      .filter((e) => e.startsWith(scoped + "@"))
      .sort()
      .reverse();
    if (candidates.length > 0) {
      const pkgDir = join(pnpmRoot, candidates[0], "node_modules", name);
      const manifest = JSON.parse(readFileSync(join(pkgDir, "package.json"), "utf8"));
      return join(pkgDir, manifest.exports?.["."]?.import || "dist/index.mjs");
    }
  } catch {
    // 继续抛错
  }
  throw new Error(`未找到 ${name}，请先安装 apps/front 或 apps/desktop 依赖`);
}

function collectCandidates(root) {
  const candidates = new Set();
  const stack = [root];
  while (stack.length > 0) {
    const dir = stack.pop();
    for (const name of readdirSync(dir)) {
      const file = join(dir, name);
      if (statSync(file).isDirectory()) {
        stack.push(file);
        continue;
      }
      if (!/\.(html|js|svg|css)$/.test(name)) continue;
      const text = readFileSync(file, "utf8");
      const stringRe = /(["'])((?:\\\\.|(?!\1)[^\\])*)\1/g;
      let match;
      while ((match = stringRe.exec(text)) !== null) {
        for (const token of match[2].split(/\s+/)) {
          if (token) candidates.add(token);
        }
      }
      const classRe = /class="([^"]+)"/g;
      while ((match = classRe.exec(text)) !== null) {
        for (const token of match[1].split(/\s+/)) {
          if (token) candidates.add(token);
        }
      }
    }
  }
  return candidates;
}

async function build() {
  const nodePkg = resolveNodePackage("@tailwindcss/node");
  const { compile } = await import(pathToFileURL(nodePkg).href);
  const inputCss = readFileSync(join(projectRoot, "src", "input.css"), "utf8");
  const candidates = collectCandidates(join(projectRoot, "static"));
  collectCandidates(join(projectRoot, "plugins")).forEach((c) => candidates.add(c));
  collectCandidates(join(projectRoot, "src")).forEach((c) => candidates.add(c));

  const compiled = await compile(inputCss, {
    base: frontRoot,
    onDependency() {},
  });
  const css = compiled.build([...candidates]);
  const outPath = join(projectRoot, "static", "css", "tailwind.css");
  mkdirSync(join(projectRoot, "static", "css"), { recursive: true });
  writeFileSync(outPath, css);
  console.log(`tailwind.css 已生成：${css.length} 字节，候选类名 ${candidates.size} 个`);
}

if (process.argv.includes("--watch")) {
  const targets = [join(projectRoot, "static"), join(projectRoot, "plugins"), join(projectRoot, "src")];
  targets.forEach((dir) => watch(dir, { recursive: true }, () => build()));
  console.log("监听 static/ plugins/ src/ 变更，Ctrl+C 退出");
} else {
  await build();
}
