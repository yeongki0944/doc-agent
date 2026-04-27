import assert from 'node:assert/strict'
import { mkdtemp, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { build } from 'esbuild'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const srcRoot = path.resolve(__dirname, '..')
const tempDir = await mkdtemp(path.join(tmpdir(), 'appsync-test-'))
const bundlePath = path.join(tempDir, 'bundle.mjs')

const result = await build({
  stdin: {
    contents: `
      export { handleDocumentEvent } from './utils/appsync.ts'
      export { useDocumentStore } from './store/documentStore.ts'
    `,
    resolveDir: srcRoot,
    loader: 'ts',
  },
  bundle: true,
  format: 'esm',
  platform: 'node',
  write: false,
  define: {
    'import.meta.env.VITE_APPSYNC_HTTP_URL': '""',
    'import.meta.env.VITE_APPSYNC_WS_URL': '""',
    'import.meta.env.VITE_APPSYNC_API_KEY': '""',
  },
})

await writeFile(bundlePath, result.outputFiles[0].text)
const { handleDocumentEvent, useDocumentStore } = await import(pathToFileURL(bundlePath))

useDocumentStore.setState({
  version: 1,
  agentStatus: 'idle',
  sections: {},
})

handleDocumentEvent({
  type: 'patch',
  version_before: 1,
  version_after: 2,
  operations: [{ op: 'replace', path: '/sections/cover/title', value: 'Patched Title' }],
})
assert.equal(useDocumentStore.getState().sections.cover.title, 'Patched Title')

handleDocumentEvent({
  type: 'chat_done',
  document: { sections: { cover: { title: 'Legacy Full Document' } } },
}, () => {})
assert.equal(useDocumentStore.getState().sections.cover.title, 'Patched Title')

handleDocumentEvent({ type: 'status', status: 'processing' })
assert.equal(useDocumentStore.getState().agentStatus, 'processing')
