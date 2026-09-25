"""O hash de senha. TEC-201, D3.

**Argon2id**, que e a primeira escolha do OWASP para armazenamento de senha.
`cryptography` -- que ja esta no projeto e oferece `Scrypt` -- foi considerado
e recusado: usa-lo obrigaria a inventar o formato de armazenamento (sal,
parametros, versao) no ponto de maior consequencia desta card. O formato do
Argon2 ja carrega tudo isso dentro da propria string, e e o que permite subir
o custo amanha sem invalidar o que ja foi gravado.

**Nada aqui e reversivel, e e esse o ponto.** A senha nao passa pelo
`infra/crypto.py`: cifra se desfaz com a chave, e quem tiver a chave de
conteudo deste sistema nao deve poder ler senha nenhuma.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Os parametros padrao da biblioteca, deliberadamente nao ajustados.
#
# Eles seguem a RFC 9106 e sao revisados por quem mantem o pacote. Baixar o
# custo aqui seria a otimizacao que nao se percebe ter feito: o login continua
# funcionando identico, e so um ataque offline mostra a diferenca -- quando ja
# e tarde. Quem quiser subir, suba com medicao, e lembre que o formato do
# Argon2 ja permite conviver com hashes antigos.
_HASHER = PasswordHasher()


def gerar_hash(senha: str) -> str:
    """O hash a gravar em `usuarios.senha_hash`.

    Duas chamadas com a MESMA senha devolvem strings diferentes, porque o sal e
    novo a cada vez. Isso nao e curiosidade: e o que impede descobrir, olhando
    a tabela, que duas pessoas usam a mesma senha.
    """
    return _HASHER.hash(senha)


def confere(senha: str, hash_guardado: str) -> bool:
    """Se a senha corresponde ao hash. Nunca levanta por senha errada.

    **`InvalidHashError` tambem devolve False, e nao propaga.** Um hash
    corrompido ou de formato desconhecido significa que aquele usuario nao tem
    credencial utilizavel -- o desfecho certo e "nao entra", nao um 500 que
    diria a quem tenta que aquele registro existe e esta quebrado.

    A biblioteca ja compara em tempo constante; nao ha `compare_digest` aqui
    porque nao ha comparacao nossa a fazer.
    """
    try:
        return _HASHER.verify(hash_guardado, senha)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
