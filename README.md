# RSL Automação

Aplicação local (abre no navegador) que organiza revisões sistemáticas da literatura **dentro do seu vault do Obsidian** e automatiza o que pode ser automatizado sem comprometer o método: protocolo, strings por base, registro das buscas, deduplicação, triagem assistida por IA, notas de extração e fluxo PRISMA.

Segue as diretrizes de Kitchenham et al. e registra o que o PRISMA 2020 pede para relatar. **A IA nunca decide sozinha**: ela sugere, você decide.

---

## Requisitos

- **Python 3.10 ou mais recente** — [python.org](https://www.python.org/downloads/) (no Windows, marque *Add Python to PATH* na instalação).
- **Claude Code** instalado e logado na sua conta Pro: no terminal, rode `claude` uma vez e faça o login. É ele que gera as sugestões de triagem.
- **Obsidian** com o vault onde a revisão vai morar.

## Iniciar

- **Windows:** dois cliques em `iniciar.bat`.
- **macOS:** dois cliques em `iniciar.command` (na primeira vez: botão direito → Abrir). Se o macOS reclamar de permissão, rode no Terminal `chmod +x iniciar.command`.
- **Linux:** `./iniciar.command`.

Na primeira vez ele prepara o ambiente (um minuto). Depois abre `http://127.0.0.1:5077`. Para encerrar, feche a janela do terminal.

Primeiro passo: **Configurações → pasta do vault** (a pasta que contém a pasta oculta `.obsidian`).

---

## Fluxo

| Etapa | Onde | O que o app registra no vault |
|---|---|---|
| 1. Protocolo | Novo protocolo / Protocolo | `00 Protocolo/Protocolo.md`, versões congeladas, emendas no *Histórico de decisões* |
| 2. Strings | Buscas | `01 Buscas/Strings por base.md`, ajustes com motivo |
| 3. Piloto e conjunto de controle | Buscas | Uma nota por execução com string exata, totais, hash dos arquivos e quais artigos de controle foram recuperados |
| 4. Congelar protocolo | Painel | Cópia datada em `00 Protocolo/Versões` |
| 5. Buscas definitivas | Buscas (RIS ou API) | Notas de execução + `Registro de buscas.md` |
| 6. Duplicatas e resumos | Seleção | `02 Seleção/Deduplicação.md`; resumos faltantes via OpenAlex |
| 7. Calibração da IA | Seleção | Amostra aleatória triada às cegas → Kappa, sensibilidade e divergências em `Calibração.md` |
| 8. Triagem | Seleção → Triar | Decisão registro a registro, com critério; lotes em `02 Seleção/Triagem`; trilha de auditoria em `_dados/decisoes.jsonl` |
| 9. Leitura completa e qualidade | Obsidian | Uma nota por estudo em `03 Estudos`, com critérios, checklist de qualidade e um campo de extração por questão (FQ) |
| 10. PRISMA | Seleção / Painel | `02 Seleção/PRISMA.md` com diagrama (Mermaid) e tabela de números |

Na leitura completa, preencha nas propriedades da nota de estudo `leitura_completa` (incluir/excluir), `motivo_exclusao` e as notas `q_Q1`, `q_Q2`… (1, 0.5 ou 0). Clique em **Atualizar PRISMA** e os números descem pelo fluxo.

### Para um novo artigo

**Novo protocolo** na página inicial. Cada revisão vira uma pasta própria em `Revisões/` no vault, com a mesma estrutura. O protocolo de 19/10/2026 (IA na educação empreendedora) já vem como exemplo pronto: botão *Criar a partir do protocolo de 19/10/2026*.

No formulário do protocolo, quase tudo é uma linha por item com `|`:

```
FQ1 | Competencies (CHA) | What are entrepreneurial competencies ...? | Quais são ...?
IC1 | O estudo é empírico e primário ...
EC2 | O estudo é duplicado | auto
```

A terceira coluna dos critérios diz onde ele se aplica: `triagem` (padrão; a IA considera), `auto` (o app aplica, como duplicatas) ou `texto-completo`.

---

## Regras metodológicas embutidas

- **Protocolo versionado.** Congelar cria uma cópia datada. Mudanças depois disso viram emenda (nova versão) e exigem motivo, registrado no histórico. Buscas definitivas feitas antes de congelar ficam anotadas.
- **Integridade das buscas.** Cada arquivo importado ganha hash SHA-256; o mesmo arquivo não pode ser importado duas vezes. Para buscas via API, a resposta bruta (JSON) é guardada junto do RIS convertido.
- **Calibração cega.** Na amostra de calibração, as sugestões ficam ocultas até você terminar e a IA rodar. Só então o app compara.
- **A IA só sugere.** Excluir exige marcar o critério. O PRISMA registra 0 exclusões por automação.
- **Rastreabilidade.** Cada sugestão guarda modelo, data e o *hash* do prompt; o prompt completo fica em `Calibração.md`. Se você mudar os critérios depois da calibração, o app avisa que o prompt mudou.
- **Na dúvida, segue.** "Dúvida" encaminha à leitura completa, como recomenda a triagem inclusiva.

## Triagem com o Claude Code (plano Pro)

O app chama `claude -p` sem ferramentas, com um prompt montado a partir das suas questões e critérios, enviando título, resumo, palavras-chave, tipo, veículo, idioma e ano de cada registro. Cada chamada leva vários registros (padrão 10; ajuste em Configurações) e **consome o limite de uso do seu plano**. Se o limite acabar no meio, o app para; rode de novo depois e ele continua só com os que faltam.

Modelo padrão: `sonnet`. Use `haiku` para economizar ou `opus` para casos difíceis. Recalibre se trocar o modelo.

## Buscas via API (experimental)

| Base | API | Observação |
|---|---|---|
| Scopus | Elsevier Search API ([dev.elsevier.com](https://dev.elsevier.com)) | Resumos exigem acesso institucional (rede da universidade ou *insttoken*) |
| IEEE Xplore | Metadata Search API ([developer.ieee.org](https://developer.ieee.org)) | Cota diária limitada |
| SpringerLink | Springer Nature Meta API ([dev.springernature.com](https://dev.springernature.com)) | Busca em todos os metadados |
| Web of Science | Starter API ([developer.clarivate.com](https://developer.clarivate.com/apis/wos-starter)) | Não devolve resumos; plano gratuito com 50 requisições/dia |
| ACM, ScienceDirect, Wiley | — | Exportação RIS manual |

Os conectores foram escritos a partir da documentação pública e **não puderam ser testados com chaves reais**. Faça primeiro uma busca *piloto* via API e compare com o total do site. Os totais via API podem diferir da interface web; registre os dois no relato. Para registros sem resumo, use **Completar resumos via OpenAlex** antes da triagem.

## Como relatar no artigo (modelo)

> A triagem por título, resumo e palavras-chave foi realizada pela pesquisadora com apoio de um modelo de linguagem (Claude, Anthropic, via Claude Code; modelo `<modelo>`), usado exclusivamente para sugerir uma decisão e o critério correspondente para cada registro. Todas as decisões foram tomadas pela pesquisadora. Antes do uso, a ferramenta foi calibrada em uma amostra aleatória de `<n>` registros (semente `<s>`), triada às cegas, obtendo Kappa de Cohen de `<k>` e sensibilidade de `<sens>`. O prompt e os registros de cada sugestão estão disponíveis no material suplementar.

Os números estão em `02 Seleção/Calibração.md`.

## Onde ficam os dados

- **No vault:** tudo que é documentação (notas) e os dados da revisão em `_dados/` (protocolo, registros, execuções, decisões). Faça backup do vault normalmente.
- **Fora do vault:** `~/.rsl-automacao/config.json`, com o caminho do vault e as chaves de API.

## Problemas comuns

- **"Comando 'claude' não encontrado"**: instale o Claude Code e abra um terminal novo; ou informe o caminho completo do executável em Configurações.
- **Sugestões não aparecem**: veja a mensagem de erro na página Seleção. Em geral é limite de uso do plano; tente mais tarde.
- **Links "abrir no Obsidian" não funcionam**: o vault precisa estar aberto no Obsidian.
- **Diagrama do PRISMA não aparece**: o Obsidian renderiza Mermaid nativamente no modo de leitura.
