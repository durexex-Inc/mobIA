import type { Metadata } from 'next'

import { SimuladorWhatsApp } from '@/components/SimuladorWhatsApp'
import { enderecoDoSimulador } from '@/lib/servidor/enderecoDoChat'

export const metadata: Metadata = {
  title: 'Simulador de WhatsApp',
  description: 'Conversar com o agente sem a Cloud API da Meta (ferramenta de desenvolvimento).',
  robots: { index: false, follow: false },
}

/**
 * Ferramenta de desenvolvimento (nao e um recurso de produto): digite um
 * telefone e converse com o agente como se fosse pelo WhatsApp, sem ativar a
 * integracao real com a Meta. Publica, sem sessao -- ver `rotaDoSimulador`
 * em `proxy.ts` -- e o backend recusa a conexao fora de desenvolvimento
 * (`settings.em_producao`, em `api/routes/simulador.py`).
 */
export default function SimuladorWhatsAppPage() {
  return (
    <main className="simulador-whatsapp">
      <h1>Simulador de WhatsApp</h1>
      <p>
        Digite um telefone para conversar com o agente sem precisar da integração real do
        WhatsApp. Reconectar com o mesmo número retoma a mesma conversa.
      </p>
      <SimuladorWhatsApp endereco={enderecoDoSimulador()} />
    </main>
  )
}
