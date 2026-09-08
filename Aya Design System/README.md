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

Branco é usado apenas como superfície ou contraste. Todas as demais variações
de borda, hover, foco, muted e feedback são transparências derivadas desses
quatro tons. Não acrescente outra cor de marca sem atualizar o `DESIGN.md` e os
previews de tokens.

### Regras de cor

- O header é sempre preto (`#070B0D`), inclusive no tema claro.
- O laranja é a ação principal. Use-o com parcimônia em CTA, item ativo e marca.
- O verde comunica WhatsApp, conexão e sucesso; não o use como decoração.
- O bege é o canvas da aplicação. Cards permanecem brancos no tema claro.
- Texto verde sobre branco não atende contraste para corpo pequeno; nesses
  casos use preto e reserve o verde para fundo, ícone grande, borda ou indicador.
- Badges e callouts usam sempre o par `*-fade` + `*-foreground`.
- Estados de foco usam `--ring`; nunca remova `:focus-visible`.

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
- Inputs: 4px de raio e sempre dentro do padrão label + campo + mensagem.
- Cards e modais: 6px de raio por padrão; 8px em superfícies maiores.
- Bordas: 1px com `--border-solid`.
- Cards são planos por padrão; sombra aparece apenas em elevação, drag ou hover.
- Modais entram com fade + slide em 150–250ms.
- Nenhuma animação usa bounce, spring ou redução de escala no clique.

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
