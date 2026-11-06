# Notas de estudo e decisões

Contexto para retomar o projeto em qualquer sessão (minha, do Claude Code ou do Codex).

## Objetivo

Projeto de estudo e portfólio que cobre, com entregáveis concretos, a grade de uma pós em
Engenharia de IA Aplicada (UniPDS / Anhanguera, 12 meses, EAD). Os módulos da grade são
fundamentos de LLMs, APIs e prompt engineering, RAG, MCP, agentes autônomos, arquitetura de
sistemas com IA, fine-tuning e dados, IA aplicada a DevOps, segurança e governança, e projeto
integrador. O mapeamento de cada módulo para um entregável está em `ROADMAP.md`.

A ideia é aprender os mesmos conceitos fazendo, independentemente de cursar a pós ou não.

## Por que este projeto (e não outros)

Ideias descartadas e por quê:
- **Copiloto de pagamentos/legado:** conversa melhor com clientes, mas não empolgou.
- **Camada de IA no Project 722:** o projeto do jogo de cartas está parado, e o escopo da engine
  era grande demais.
- **Jogo de detetive com suspeitos LLM:** bom encaixe, mas a preferência foi IA jogando um jogo
  real num emulador.

Escolhido: **agente jogando Pokémon Yellow no PyBoy**.
- Não exige construir jogo nenhum: o produto é a IA.
- É um problema de longo prazo, mensurável e determinístico (save states → evals reproduzíveis).
- A desmontagem pret/pokeyellow dá os símbolos exatos da RAM.
- O Yellow é melhor que o Red pra estudo: o Pikachu é fixo, não evolui, tem amizade, e é fraco
  contra o Brock. Isso obriga o agente a planejar (capturar Mankey/Nidoran, treinar).
- Precedentes: *Claude Plays Pokémon* (Anthropic) e o agente de RL do Peter Whidden no Red.
- FFT (PS1) fica como bônus futuro, via BizHawk + Lua, depois que a arquitetura estiver madura.

## Divisão de modelos (arquitetura híbrida)

| Papel | Modelo | Por quê |
|---|---|---|
| Planejador (objetivos, estratégia) | Claude (API) | Raciocínio de longo prazo |
| Professor (gera dados rotulados) | Claude | Dataset para o fine-tuning |
| Referência nos benchmarks | Claude, OpenAI | Teto de qualidade |
| Agente de batalha / decisões frequentes | Local (Ollama) | Centenas de turnos por hora, custo zero |
| Alvo do fine-tuning | Local 7–8B (LoRA/QLoRA, Unsloth) | Cabe nos 16 GB |
| Evals em lote | Local | Sem custo de API |

**Hardware local:** GPU RTX 5060 com 16 GB de VRAM.
- Faixa ideal: 7–14B quantizado (família Qwen3), ou gpt-oss 20B para tool calling.
- Evitar 27–32B: transborda para a CPU e a velocidade despenca.
- Os modelos locais mudam rápido; o benchmark da fase 2 decide qual usar.

**Codex (assinatura):**
- Ferramenta de desenvolvimento junto com o Claude Code (implementar × revisar, tarefas paralelas).
- Jogador extra no benchmark via MCP (Claude × GPT × local no mesmo save state).
- Para usar modelos OpenAI dentro do loop do agente, o caminho é a API da OpenAI (cobrança à
  parte), não a assinatura.

## Cuidados combinados

- **Custo:** limite de gasto por sessão desde o primeiro dia; roteamento com o local no comum e o
  Claude no difícil.
- **CI:** o runner padrão do GitHub não tem GPU. Os evals no CI rodam com um conjunto pequeno no
  Claude, ou num self-hosted runner no PC (com o modelo local).
- **ROM:** só dump do próprio cartucho; nada de ROM, save ou asset no repositório.
- **Pontos fracos do encaixe com o curso:**
  - Fine-tuning não é *necessário* aqui; o entregável é a comparação "compensou ou não?".
  - Governança em jogo é mais leve (custo, auditoria, model card).
  - A teoria (transformers, embeddings, tokenização) vale estudar à parte, por exemplo nos
    vídeos do Karpathy.

## Metas

- Fase 1: o Claude Code joga via MCP de um jogo novo até receber o Pikachu.
- Fase 2: vencer o Eevee do rival no laboratório do Oak, sem intervenção.
- Fase 5: **Boulder Badge sem intervenção humana**.
- Posts por fase. Ideias: "três IAs tentando vencer o Brock"; "fine-tuning vs prompt: os números".

## Fontes úteis

- pret/pokeyellow: https://github.com/pret/pokeyellow (o branch `symbols` tem o `.sym`)
- PyBoy: https://github.com/Baekalfen/PyBoy
- Endereços e structs usados: `src/yellow_agent/state.py` (layouts citando `macros/ram.asm`)
