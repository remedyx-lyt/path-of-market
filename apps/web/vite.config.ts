import { defineConfig } from 'vite'
import type { ProxyOptions } from 'vite'
import react from '@vitejs/plugin-react'

const defaultProxy: ProxyOptions = {
  target: process.env.JAVA_SERVER_URL || 'http://127.0.0.1:8080',
  changeOrigin: true,
  proxyTimeout: 20_000,
  configure(proxy) {
    proxy.on('error', (_error, _request, response) => {
      if ('writeHead' in response && !response.headersSent && !response.writableEnded && !response.destroyed) {
        response.writeHead(503, { 'Content-Type': 'application/json; charset=utf-8' })
        response.end(JSON.stringify({ error: { code: 'SERVER_UNAVAILABLE', message: '应用服务暂时不可用。' } }))
      }
    })
  },
}
const apiProxy: Record<string, ProxyOptions> = {
  '/api/research/model': { ...defaultProxy, proxyTimeout: 100_000 },
  '/api': defaultProxy,
}

export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy: apiProxy },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true, proxy: apiProxy },
})
