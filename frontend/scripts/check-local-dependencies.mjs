import { existsSync, readFileSync } from 'node:fs';
import { dirname, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const manifest = JSON.parse(readFileSync(resolve(frontendRoot, 'package.json'), 'utf8'));
const dependencyGroups = [
  manifest.dependencies ?? {},
  manifest.devDependencies ?? {},
  manifest.optionalDependencies ?? {},
];

const failures = [];
for (const dependencies of dependencyGroups) {
  for (const [name, specifier] of Object.entries(dependencies)) {
    if (typeof specifier !== 'string' || !specifier.startsWith('file:')) continue;

    const target = resolve(frontendRoot, specifier.slice('file:'.length));
    const relativeTarget = relative(frontendRoot, target);
    const outsideFrontend = relativeTarget === '..' || relativeTarget.startsWith(`..${sep}`);
    if (outsideFrontend) {
      failures.push(`${name}: local dependency escapes the StockPro frontend (${specifier})`);
      continue;
    }

    if (!existsSync(resolve(target, 'package.json'))) {
      failures.push(`${name}: missing local package manifest (${specifier})`);
    }
  }
}

if (failures.length) {
  console.error('Invalid frontend local dependencies:');
  failures.forEach((failure) => console.error(`- ${failure}`));
  process.exit(1);
}

console.log('Frontend local dependencies are repository-contained.');
