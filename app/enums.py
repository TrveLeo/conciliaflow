"""Enums do domínio.

Sem SQLAlchemy aqui de propósito: a lógica de normalização e de conciliação
importa este módulo sem precisar de driver de banco instalado.
"""

import enum


class JobStatus(str, enum.Enum):
    """Ciclo de vida de uma execução de conciliação."""

    criado = "criado"
    importando = "importando"
    pronto = "pronto"          # dados importados, aguardando conciliação
    conciliando = "conciliando"
    concluido = "concluido"
    erro = "erro"


class SourceSide(str, enum.Enum):
    """De qual arquivo o registro veio.

    `a` e `b` são as duas fontes obrigatórias; `c` é a opcional.
    """

    a = "a"
    b = "b"
    c = "c"


class MatchStatus(str, enum.Enum):
    conciliado = "conciliado"
    divergente = "divergente"
    pendente = "pendente"


class MatchRule(str, enum.Enum):
    """Qual regra fechou o par.

    Substitui o campo `confidence` da especificação original: com regras
    determinísticas, um score de confiança seria inventado. Saber *qual* regra
    casou é informação real e explica a divergência para o usuário.
    """

    exata = "exata"                      # valor + referência iguais
    janela_data = "janela_data"          # valor igual, data dentro da janela
    tolerancia_valor = "tolerancia_valor"  # referência igual, centavos de diferença
    nenhuma = "nenhuma"                  # não casou
