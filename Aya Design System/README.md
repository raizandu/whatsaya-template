# Aya Design System

Sistema visual do **WhatsAya** e de seus painéis operacionais. Esta versão
preserva a estrutura, a densidade, os componentes, a tipografia, os estados e
os critérios de qualidade do Actuar Design System usado como referência. A
identidade cromática foi substituída pela paleta oficial da Aya.

## Fonte de verdade

- Contexto e regras do produto: [`../DESIGN.md`](../DESIGN.md)
- Tokens consumíveis: [`colors_and_type.css`](colors_and_type.css)
- Referência visual: [`preview/`](preview/)
- Componentes de exemplo: [`ui_kits/aya-platform/`](ui_kits/aya-platform/)
- Catálogo de ícones: [`assets/icons-catalog/`](assets/icons-catalog/)

## Paleta oficial

| Token base | Valor | Uso principal |
|---|---:|---|
| `--aya-orange` | `#F26E22` | Identidade, CTA principal, seleção e alerta |
| `--aya-beige` | `#F0E7DD` | Fundo da aplicação e superfícies suaves |
| `--aya-green` | `#4CDE59` | WhatsApp, conexão, sucesso e confirmação |
| `--aya-black` | `#070B0D` | Texto, header, navegação e superfícies escuras |

Branco é usado apenas como superfície ou contraste. Variações de borda, muted,
fade e feedback são transparências desses quatro tons. Hover, active, borda
inferior de botão e a versão "texto" do laranja e do verde são **tons
derivados**: sombreamento em OKLCH da cor de marca (matiz preservado), fixados
em hex no token layer (`--primary-hover`, `--primary-active`, `--primary-edge`,
`--primary-deep`, `--green-*`). Nenhum outro hex existe fora dessa lista. Não
acrescente cor de marca nem tom derivado sem atualizar o `DESIGN.md` e os
previews de tokens.

### Regras de cor

- O header é sempre preto (`#070B0D`), inclusive no tema claro.
- O laranja é a ação principal. Use-o com parcimônia em CTA, item ativo e marca.
- O verde comunica WhatsApp, conexão e sucesso; não o use como decoração.
- O bege é o canvas da aplicação. Cards permanecem brancos no tema claro.
- Texto sobre laranja e sobre verde é **preto** (`--primary-foreground`):
  branco sobre `#F26E22` dá 2.99:1 e falha AA; preto dá 6.61:1.
- Laranja ou verde **como texto, link ou ring** no tema claro usam o tom
  derivado (`--primary-deep`, `--green-deep`); o hex de marca puro fica
  reservado a superfície preenchida, marcador de 2px e texto ≥ 24px.
- Ação destrutiva é `--destructive` = laranja profundo com texto branco. Preto
  preenchido fica para ações irreversíveis, uma vez por tela.
- Badges e callouts usam sempre o par `*-fade` + `*-foreground`.
- Estados de foco usam `--focus-ring` (2px de respiro em `--ring-offset` + 2px
  em `--ring`); nunca remova `:focus-visible`.

## Tipografia

O sistema mantém a hierarquia tipográfica validada na referência:

- **Open Sans** 300/400/500/600/700 para toda a interface.
- **Geist** 100/600/700 exclusivamente para números, métricas, valores e moeda.
- **Aya** (arquivo de display herdado do kit de referência) 400/700 apenas para
  marca, hero e comunicação institucional.

O corpo padrão é 14px. Títulos de página usam 24px/600 e títulos de seção
18px/600. Números de destaque usam Geist, chegando a 64px em KPIs hero.

Nunca use ALL CAPS em títulos. A única exceção é o micro-label de 8px acima de
KPIs, com `letter-spacing: 1px`.

## Voz e conteúdo

O WhatsAya fala de forma direta, calma e operacional. A interface deve ajudar o
responsável a entender o estado do atendimento e agir sem ambiguidades.

- Prefira verbos concretos: **Pausar IA**, **Retomar atendimento**, **Mover
  etapa**, **Bloquear contato**, **Ver conversa**.
- Use termos do domínio: **lead**, **conversa**, **follow-up**, **handoff**,
  **WhatsApp**, **atendimento**, **fila** e **conexão**.
- Títulos têm de 2 a 5 palavras; subtítulos explicam a consequência em uma frase.
- Mensagens de erro dizem o que ocorreu e qual ação é possível.
- Não use emoji na interface de produto. Use ícones regulares arredondados.

## Componentes e geometria

- Botões: 24px pequeno, 32px padrão desktop, 44px padrão mobile.
- Inputs: 6px de raio (`--radius`), borda `--hairline-strong` e sempre dentro do padrão label + campo + hint ou erro.
- Cards e modais: 6px de raio por padrão; 8px em superfícies maiores; popover
  usa `--popover-radius` (raio do gatilho + 2) e seus itens raio − 4.
- Bordas: 1px com `--border-solid`. Borda que carrega informação (input,
  check, radio) usa `--hairline-strong`, que passa 3:1.

### Elevação

Toda superfície declara um nível, e cada nível é um par sombra + z-index:

| Nível | Sombra | z-index | Onde |
|---|---|---|---|
| flat | `--shadow-hairline` | `--z-base` | card em lista densa, tabela, input |
| raised | `--shadow-xs` | `--z-raised` | card padrão, botão secondary, toggle |
| hover | `--shadow-sm` | `--z-raised` | card interativo em hover, item arrastado |
| overlay | `--shadow-md` | `--z-dropdown` | popover, select, combo-box, date-picker, menu, tooltip |
| modal | `--shadow-lg` | `--z-modal` | dialog, drawer, command menu |
| toast | `--shadow-xl` | `--z-toast` | toast, notificação |

- A sombra é **tintada no matiz do bege** (`--shadow-tint: 32 30% 16%`), nunca
  preto neutro, e começa sempre por uma hairline de 1px.
- No tema escuro a elevação é **tonal**: a superfície clareia por nível
  (`--surface-1..4`), a hairline vira branca e a sombra fica mais opaca.
- Botão preenchido tem `--inset-highlight` no topo e borda inferior em
  `--primary-edge`; no `:active` o highlight some e a sombra colapsa.
- Card só ganha sombra acima de `raised` quando é interativo, e a ganha em
  hover, não fixa.

### Movimento

- Durações e curvas vêm dos tokens `--duration-*` e `--ease-*`. Nada de
  `transition: all`, nem valor solto em ms.
- Anime só `transform`, `opacity`, `background-color`, `border-color` e
  `box-shadow`. Nunca `top`, `left`, `width`, `height`.
- Popover entra em `--duration-base` com `--ease-out`, `scale(.96)` e 4px de
  deslocamento a partir do lado do gatilho (`transform-origin`); sai em
  `--duration-fast` com `--ease-in`. Modais entram com fade + slide em
  `--duration-moderate`.
- Clique tem feedback tátil: `translateY(1px)` em `--duration-instant`, com
  colapso da sombra. Spring, bounce e overshoot continuam proibidos.
- `prefers-reduced-motion` zera as durações pelos tokens; não reimplemente.

## Iconografia

Use `@flaticon/flaticon-uicons` v3.3.1, variante **regular-rounded**:

```html
<link
  rel="stylesheet"
  href="https://cdn.jsdelivr.net/npm/@flaticon/flaticon-uicons@3.3.1/css/regular/rounded.css"
>
<i class="fi fi-rr-comments"></i>
```

O catálogo completo está em
`assets/icons-catalog/uicons-regular-rounded.json`. Ícones funcionais devem ser
vetoriais; PNG/WebP ficam restritos a logos e imagens de referência.

## Como usar

Inclua o CSS na página ou no entrypoint da aplicação:

```html
<link rel="stylesheet" href="./colors_and_type.css">
```

Use os tokens sem copiar hexadecimais para componentes:

```css
.primary-action {
  color: var(--primary-foreground);
  background: var(--primary);
  border: 1px solid var(--primary);
  border-radius: var(--radius);
}

.success-badge {
  color: var(--success-foreground);
  background: var(--success-fade);
}
```

Adicione `.dark` ao elemento raiz para o tema escuro. Adicione `.whatsapp`
quando o contexto exigir que o verde se torne a ação dominante:

```html
<main class="dark whatsapp">...</main>
```

## Estrutura

- `colors_and_type.css` — tokens, fontes e classes tipográficas.
- `fonts/` — Open Sans, Geist e fonte display Aya.
- `assets/` — logos, ilustrações e catálogo de ícones herdados da referência.
- `preview/` — páginas isoladas de cores, tipo, estados e componentes.
- `ui_kits/aya-platform/` — shell e telas React de referência.
- `_ds_manifest.json` — índice consumido pelo visualizador do design system.
- `_ds_bundle.js` — bundle do UI kit para o visualizador.
- `_adherence.oxlintrc.json` — regras de aderência para consumidores.

## Critério de manutenção

Depois de alterar CSS, JSX ou metadados dos previews, regenere os artefatos:

```bash
node scripts/build-design-system.mjs
```

O script compila o bundle, recalcula hashes, extrai cards/tokens/fontes e grava
o manifesto.

Uma mudança só está completa quando:

1. o token foi alterado em `colors_and_type.css`;
2. previews claros e escuros continuam legíveis;
3. componentes não introduzem hexadecimais fora da paleta;
4. `_ds_manifest.json` e `_ds_bundle.js` refletem a fonte atual;
5. links, fontes, assets e JSX passam pelas verificações locais.
