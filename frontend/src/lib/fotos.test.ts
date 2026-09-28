import { describe, expect, it } from 'vitest'

import {
  FOTO_LIMITE_POR_IMOVEL,
  FOTO_TETO_DE_BYTES,
  mensagemDeErroDoEnvio,
  recusaDoArquivo,
  remover,
  reordenar,
} from './fotos'

function arquivo(nome: string, tamanho: number): File {
  const f = new File(['x'], nome)
  Object.defineProperty(f, 'size', { value: tamanho })
  return f
}

describe('recusaDoArquivo (D6)', () => {
  it('aceita um jpeg dentro do teto', () => {
    expect(recusaDoArquivo(arquivo('foto.jpg', FOTO_TETO_DE_BYTES))).toBeNull()
  })

  it('aceita png e webp', () => {
    expect(recusaDoArquivo(arquivo('foto.png', 1024))).toBeNull()
    expect(recusaDoArquivo(arquivo('foto.webp', 1024))).toBeNull()
  })

  it('recusa acima do teto de 5MB', () => {
    const recusa = recusaDoArquivo(arquivo('foto.jpg', FOTO_TETO_DE_BYTES + 1))
    expect(recusa).toContain('5')
  })

  it('recusa extensao que nao e jpeg/png/webp -- checagem so client-side, o backend decide de verdade (D3)', () => {
    const recusa = recusaDoArquivo(arquivo('foto.gif', 1024))
    expect(recusa).toContain('JPEG')
  })
})

describe('reordenar (D5)', () => {
  it('move o item da origem para o destino', () => {
    expect(reordenar(['a', 'b', 'c'], 2, 0)).toEqual(['c', 'a', 'b'])
  })

  it('mover para a mesma posicao nao muda nada', () => {
    expect(reordenar(['a', 'b', 'c'], 1, 1)).toEqual(['a', 'b', 'c'])
  })

  it('indice fora da faixa devolve copia inalterada', () => {
    expect(reordenar(['a', 'b'], -1, 0)).toEqual(['a', 'b'])
    expect(reordenar(['a', 'b'], 0, 5)).toEqual(['a', 'b'])
  })

  it('nao muda o array original', () => {
    const original = ['a', 'b', 'c']
    reordenar(original, 0, 2)
    expect(original).toEqual(['a', 'b', 'c'])
  })
})

describe('remover (D4)', () => {
  it('tira so o indice pedido', () => {
    expect(remover(['a', 'b', 'c'], 1)).toEqual(['a', 'c'])
  })
})

describe('mensagemDeErroDoEnvio', () => {
  it('422 com string mostra o detalhe do backend como veio (D3/D6)', () => {
    expect(mensagemDeErroDoEnvio(422, 'formato nao reconhecido')).toBe('formato nao reconhecido')
  })

  it('401 e 403 tem mensagem propria', () => {
    expect(mensagemDeErroDoEnvio(401, undefined)).toContain('sessão')
    expect(mensagemDeErroDoEnvio(403, undefined)).toContain('permissão')
  })

  it('limite de fotos por imovel e 15', () => {
    expect(FOTO_LIMITE_POR_IMOVEL).toBe(15)
  })
})
