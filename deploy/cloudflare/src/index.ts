import { Container, getRandom } from '@cloudflare/containers'
import { gateway, instanceCount } from './gateway'

export class OcrContainer extends Container<Env> {
  defaultPort = 8000
  sleepAfter = this.env.CONTAINER_IDLE_TIMEOUT
  enableInternet = false
  envVars = {
    DOCUMENT_OCR_KYC_LANGS: this.env.DOCUMENT_OCR_KYC_LANGS,
    API_TOKEN: this.env.API_TOKEN,
  }
}

export default {
  async fetch(request, env) {
    return gateway(request, env.API_TOKEN, async (incoming) => {
      const container = await getRandom(env.OCR, instanceCount(env.CONTAINER_INSTANCES))
      return container.fetch(incoming)
    })
  },
} satisfies ExportedHandler<Env>
