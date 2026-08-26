import { gzipSync } from 'node:zlib'
import { readFile, readdir, stat } from 'node:fs/promises'
import { basename, join } from 'node:path'

const distDir = new URL('../dist/', import.meta.url)
const assetsDir = new URL('../dist/assets/', import.meta.url)
const indexHtml = await readFile(new URL('index.html', distDir), 'utf8')
const initialAssets = new Set(
  [...indexHtml.matchAll(/(?:src|href)="\/assets\/([^"]+\.js)"/g)].map((match) => match[1]),
)
const assetNames = (await readdir(assetsDir)).filter((name) => name.endsWith('.js'))

const limits = {
  initialRaw: 600 * 1024,
  initialGzip: 190 * 1024,
  routeRaw: 320 * 1024,
  chartsRaw: 1_200 * 1024,
  chartsGzip: 410 * 1024,
}

const sizes = []
for (const name of assetNames) {
  const file = join(assetsDir.pathname, name)
  const contents = await readFile(file)
  sizes.push({ name: basename(name), raw: (await stat(file)).size, gzip: gzipSync(contents).length })
}

const initial = sizes.filter((item) => initialAssets.has(item.name))
const initialRaw = initial.reduce((total, item) => total + item.raw, 0)
const initialGzip = initial.reduce((total, item) => total + item.gzip, 0)
const failures = []

if (initialRaw > limits.initialRaw) failures.push(`首屏 JS ${initialRaw} > ${limits.initialRaw} bytes`)
if (initialGzip > limits.initialGzip) failures.push(`首屏 gzip JS ${initialGzip} > ${limits.initialGzip} bytes`)

for (const item of sizes) {
  if (item.name.startsWith('vendor-charts-') || item.name.startsWith('charts-')) {
    if (item.raw > limits.chartsRaw) failures.push(`${item.name} ${item.raw} > ${limits.chartsRaw} bytes`)
    if (item.gzip > limits.chartsGzip) failures.push(`${item.name} gzip ${item.gzip} > ${limits.chartsGzip} bytes`)
    continue
  }
  if (item.raw > limits.routeRaw) failures.push(`${item.name} ${item.raw} > ${limits.routeRaw} bytes`)
}

const kb = (value) => `${(value / 1024).toFixed(1)} KiB`
console.log(
  `[bundle-budget] initial ${initial.length} files · ${kb(initialRaw)} raw · ${kb(initialGzip)} gzip; ` +
    `largest ${sizes.sort((a, b) => b.raw - a.raw).slice(0, 3).map((item) => `${item.name} ${kb(item.raw)}`).join(', ')}`,
)

if (failures.length) {
  console.error(`[bundle-budget] failed\n- ${failures.join('\n- ')}`)
  process.exit(1)
}

console.log('[bundle-budget] passed')
