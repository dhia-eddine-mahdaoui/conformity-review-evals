// Usage: node ocr.mjs <dir containing eng.traineddata.gz> <png>...
// Prints a JSON array with one recognised text per image.
import { readFileSync } from 'node:fs'
import { createWorker } from 'tesseract.js'

const [, , langPath, ...files] = process.argv
const worker = await createWorker('eng', 1, { langPath, cacheMethod: 'none' })
const out = []
for (const f of files) out.push((await worker.recognize(readFileSync(f))).data.text)
await worker.terminate()
console.log(JSON.stringify(out))
