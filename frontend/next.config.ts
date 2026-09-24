import type { NextConfig } from "next";

/**
 * Os cabecalhos de seguranca que NAO dependem da requisicao (TEC-356,
 * RNF-FE-09).
 *
 * A CSP nao esta aqui, e a divisao e deliberada: ela carrega um nonce novo por
 * requisicao, e configuracao estatica nao consegue produzir isso. Ela mora em
 * `src/proxy.ts`.
 *
 * **Estes tres moram aqui, e nao no proxy, por ALCANCE.** O matcher do proxy
 * exclui `_next/static` -- e deve mesmo, porque asset nao tem script a
 * autorizar --, mas `nosniff` importa exatamente nos assets: e neles que
 * sniffing de tipo tem consequencia. A referencia de `headers` e explicita em
 * que esta configuracao os alcanca:
 *
 *     Headers are checked before the filesystem which includes pages and
 *     `/public` files.
 *
 * O risco da divisao -- alguem mexer numa morada e achar que mexeu nas duas --
 * e o que o teste de integracao ataca, afirmando o conjunto INTEIRO sobre a
 * mesma resposta em vez de um teste por cabecalho. Ver a D2 do desenho.
 */
const cabecalhosDeSeguranca = [
  {
    key: "X-Content-Type-Options",
    value: "nosniff",
  },
  {
    key: "Referrer-Policy",
    value: "strict-origin-when-cross-origin",
  },
  {
    // Um ano, como a card pede.
    //
    // **`preload` fica de fora de proposito.** Entrar na lista de preload dos
    // navegadores e rapido; sair leva meses e so chega ao usuario na versao
    // seguinte do navegador. E um compromisso sobre TODOS os subdominios,
    // inclusive os que ainda nao existem -- e este projeto nem escolheu a
    // nuvem (TEC-219). Ver a D4 e a lacuna L3 do desenho.
    //
    // Em desenvolvimento e inofensivo: o navegador ignora HSTS recebido por
    // HTTP.
    key: "Strict-Transport-Security",
    value: "max-age=31536000; includeSubDomains",
  },
];

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: cabecalhosDeSeguranca,
      },
    ];
  },
};

export default nextConfig;
