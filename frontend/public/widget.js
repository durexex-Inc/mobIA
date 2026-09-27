/*
 * O loader do chat web da mobIA (TEC-344). Uma linha no site da imobiliaria:
 *
 *   <script src="https://<painel>/widget.js" data-tenant="<slug>" async></script>
 *
 * Desenha um botao com a cor, o lado e o nome configurados, e no primeiro
 * clique abre o chat num iframe. **Nenhuma falha vira erro de JS no site**
 * (D7 do desenho): tudo roda dentro de try/catch, toda promise tem catch, e o
 * que falha deixa o site sem botao.
 *
 * JavaScript puro, sem build e sem dependencia (D5): o que esta aqui e o que o
 * navegador baixa, e `npm run verificar:widget` reprova acima de 5 KB gzip.
 * Sem conferencia de tipos -- o `tsconfig` nao inclui `.js` de `public/` --, e
 * por isso a rede sao os testes de `src/widget/widget.test.ts`, que executam
 * este arquivo.
 */
;(function () {
  'use strict'

  var TEMPO_DA_APARENCIA_MS = 5000
  var TEMPO_DO_PRONTO_MS = 10000
  var COR = /^#[0-9A-Fa-f]{6}$/
  // O lado do CSS por posicao. Lido so por `hasOwnProperty`: uma posicao
  // chamada "constructor" acharia a funcao herdada e passaria por valida.
  var LADOS = { DIREITA: 'right', ESQUERDA: 'left' }
  var CAMADA = '2147483000'

  try {
    iniciar()
  } catch {
    // D7: nada escapa para o site hospedeiro.
  }

  function iniciar() {
    // `currentScript` so vale durante a execucao sincrona deste arquivo, entao
    // e lido aqui, antes de qualquer `await`.
    var script = acharScript()
    var tenant = script && script.getAttribute('data-tenant')
    if (!tenant || window.__mobiaWidget) {
      return
    }
    window.__mobiaWidget = true
    var origem = new URL(script.src, location.href).origin
    buscarAparencia(origem, tenant)
      .then(function (aparencia) {
        if (aparencia) {
          desenhar(origem, tenant, aparencia)
        }
      })
      .catch(function () {})
  }

  function acharScript() {
    var atual = document.currentScript
    if (atual && atual.getAttribute('data-tenant')) {
      return atual
    }
    return document.querySelector('script[data-tenant][src*="widget.js"]')
  }

  function buscarAparencia(origem, tenant) {
    var controle = new AbortController()
    var prazo = setTimeout(function () {
      controle.abort()
    }, TEMPO_DA_APARENCIA_MS)
    var url = origem + '/embed/aparencia?tenant=' + encodeURIComponent(tenant)
    return fetch(url, { credentials: 'omit', signal: controle.signal })
      .then(function (resposta) {
        return resposta.status === 200 ? resposta.json() : null
      })
      .then(lerAparencia)
      .catch(function () {
        return null
      })
      .then(function (aparencia) {
        clearTimeout(prazo)
        return aparencia
      })
  }

  function lerAparencia(corpo) {
    if (!corpo || typeof corpo !== 'object') {
      return null
    }
    var cor = corpo.corPrimaria
    var posicao = corpo.posicaoDoBotao
    if (typeof cor !== 'string' || !COR.test(cor)) {
      return null
    }
    if (typeof posicao !== 'string' || !Object.prototype.hasOwnProperty.call(LADOS, posicao)) {
      return null
    }
    var nome = typeof corpo.nomeDoAssistente === 'string' ? corpo.nomeDoAssistente : null
    return { cor: cor, lado: LADOS[posicao], nome: nome }
  }

  function desenhar(origem, tenant, aparencia) {
    var hospede = document.createElement('div')
    // Fechado: o CSS do site nao entra, e o script do site nao alcanca o
    // botao por `shadowRoot`.
    var raiz = hospede.attachShadow({ mode: 'closed' })
    var botao = document.createElement('button')
    botao.type = 'button'
    botao.setAttribute(
      'aria-label',
      aparencia.nome ? 'Abrir o chat com ' + aparencia.nome : 'Abrir o chat',
    )
    botao.setAttribute('aria-expanded', 'false')
    // CSSOM, e nao `<style>`: a CSP do proprio site pode bloquear `<style>`
    // injetado, e nao bloqueia `el.style`.
    var estilo = {
      position: 'fixed',
      bottom: '20px',
      width: '56px',
      height: '56px',
      borderRadius: '50%',
      border: '0',
      padding: '0',
      cursor: 'pointer',
      backgroundColor: aparencia.cor,
      color: '#fff',
      boxShadow: '0 4px 12px rgba(0,0,0,.25)',
      zIndex: CAMADA,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
    }
    estilo[aparencia.lado] = '20px'
    Object.assign(botao.style, estilo)
    botao.appendChild(icone())
    raiz.appendChild(botao)

    var painel = null
    botao.addEventListener('click', function () {
      try {
        if (!painel) {
          painel = abrirPainel(origem, tenant, aparencia.lado, raiz, hospede)
        } else {
          painel.style.display = painel.style.display === 'none' ? 'block' : 'none'
        }
        botao.setAttribute('aria-expanded', painel.style.display === 'none' ? 'false' : 'true')
      } catch {
        // D7.
      }
    })
    ;(document.body || document.documentElement).appendChild(hospede)
  }

  function abrirPainel(origem, tenant, lado, raiz, hospede) {
    var painel = document.createElement('div')
    var estilo = {
      position: 'fixed',
      bottom: '88px',
      width: 'min(380px, calc(100vw - 40px))',
      height: 'min(600px, calc(100vh - 120px))',
      borderRadius: '12px',
      overflow: 'hidden',
      boxShadow: '0 8px 24px rgba(0,0,0,.25)',
      background: '#fff',
      zIndex: CAMADA,
      display: 'block',
    }
    estilo[lado] = '20px'
    Object.assign(painel.style, estilo)

    var quadro = document.createElement('iframe')
    quadro.title = 'Chat'
    quadro.src = origem + '/embed/chat?tenant=' + encodeURIComponent(tenant)
    Object.assign(quadro.style, { width: '100%', height: '100%', border: '0' })
    painel.appendChild(quadro)
    raiz.appendChild(painel)

    // D7: iframe de outra origem nao dispara `onerror`. A pagina do chat manda
    // `mobia:pronto`; sem ele no prazo, o chat nao carregou, e botao e painel
    // saem do site. So vale a mensagem da nossa origem E da janela deste
    // iframe -- qualquer outra aba ou frame poderia mandar o mesmo texto.
    var prazo = setTimeout(function () {
      window.removeEventListener('message', aoMensagem)
      hospede.remove()
    }, TEMPO_DO_PRONTO_MS)

    function aoMensagem(evento) {
      try {
        if (evento.origin !== origem || evento.source !== quadro.contentWindow) {
          return
        }
        if (evento.data && evento.data.tipo === 'mobia:pronto') {
          clearTimeout(prazo)
          window.removeEventListener('message', aoMensagem)
        }
      } catch {
        // D7.
      }
    }
    window.addEventListener('message', aoMensagem)
    return painel
  }

  function icone() {
    var ns = 'http://www.w3.org/2000/svg'
    var svg = document.createElementNS(ns, 'svg')
    svg.setAttribute('width', '28')
    svg.setAttribute('height', '28')
    svg.setAttribute('viewBox', '0 0 24 24')
    svg.setAttribute('fill', 'currentColor')
    svg.setAttribute('aria-hidden', 'true')
    var balao = document.createElementNS(ns, 'path')
    balao.setAttribute('d', 'M4 4h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-5 4v-4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z')
    svg.appendChild(balao)
    return svg
  }
})()
