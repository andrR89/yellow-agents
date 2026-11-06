# Diário de sessões

Cada sessão de trabalho gera um arquivo aqui: `AAAA-MM-DD-NN.md` (NN = número da sessão no
projeto, sequencial). A página renderiza esses arquivos como uma linha do tempo, do
planejamento até zerar o jogo.

Escrito em pt-BR (idioma original); a página traduz para os outros idiomas.

## Regras

- Escreva **no fim de cada sessão**, enquanto os detalhes estão frescos.
- Problemas reais, com o sintoma como ele apareceu, não a versão arrumada depois.
- Toda afirmação de resultado vem com evidência: número, commit, trace ou save state.
- Becos sem saída também entram: o que foi tentado e não funcionou é parte do relatório.
- Não invente números. Se não mediu, escreva "não medido".

## Modelo

```markdown
---
sessao: 3
data: 2026-11-07
fase: 1
titulo: "Um botão, um tile"
duracao_h: 2.5
custo_usd: 0.00          # gasto com APIs na sessão
commits: [abc1234, def5678]
marco: null              # ex.: "primeira badge" quando houver
---

## Objetivo
O que a sessão pretendia fazer.

## Problemas e soluções

### 1. Título curto do problema
- **Sintoma:** o que se viu.
- **Causa:** o que estava acontecendo de fato.
- **Solução:** o que foi feito.
- **Evidência:** número, commit, trace, save state.

## Decisões
Escolhas de arquitetura tomadas (e link para o ADR, se houver).

## Números
Métricas da sessão (taxa de sucesso, frames, custo, latência…).

## Próxima sessão
O que fica para depois.
```
