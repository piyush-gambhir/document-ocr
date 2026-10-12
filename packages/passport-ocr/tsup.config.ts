import { defineConfig } from 'tsup'

export default defineConfig({
  entry: ['src/index.ts'],
  format: ['esm', 'cjs'],
  // tsup injects baseUrl into the declaration build, which TypeScript 6
  // deprecates; silence that warning there only.
  dts: { compilerOptions: { ignoreDeprecations: '6.0' } },
  sourcemap: true,
  clean: true,
  outDir: 'dist',
  external: ['@aws-sdk/client-lambda'],
  outExtension({ format }) {
    return {
      js: format === 'cjs' ? '.cjs' : '.js',
    }
  },
})
