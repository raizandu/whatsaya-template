# Checklist de adoção — WhatsAya × Aya Design System

Use esta lista ao migrar uma tela do painel. O kit de referência preserva os
mesmos padrões estruturais e de interação do design system de origem; a paleta
Aya é a única fonte cromática permitida.

## Fundação

- [ ] CSS importa `colors_and_type.css` ou replica seus tokens semanticamente.
- [ ] Não existem cores de marca fora de `#F26E22`, `#F0E7DD`, `#4CDE59` e
      `#070B0D`; branco, transparências e os tons derivados do token layer
      (`--primary-hover/active/edge/deep`, `--green-*`) são o único suporte.
- [ ] Nenhum `var(--x)` sem definição em `colors_and_type.css`; nenhuma sombra,
      duração ou z-index hardcoded fora dos tokens.
- [ ] Tema claro e escuro foram verificados.
- [ ] Header permanece preto nos dois temas.
- [ ] Open Sans é usada na UI; Geist apenas em números; Aya apenas em display.
- [ ] Títulos não usam ALL CAPS.

## Componentes

- [ ] Botões respeitam alturas 24/32px no desktop e 44px no mobile.
- [ ] Botões têm `:hover`, `:active` (translateY 1px + sombra colapsa),
      `:focus-visible` com `--focus-ring` e `:disabled`; texto sobre laranja e
      verde é preto.
- [ ] Inputs têm label, campo, hint/erro e foco visível.
- [ ] Cada superfície declara um nível de elevação (hairline/xs/sm/md/lg/xl)
      pareado com o `--z-*` correspondente; cards não interativos ficam em
      `raised` ou abaixo.
- [ ] Popover, select, combo-box e date-picker usam `--shadow-md`,
      `--popover-radius`, `--popover-offset` e animam entrada e saída.
- [ ] Transições usam `--duration-*` e `--ease-*` e animam só transform,
      opacity, cor e sombra.
- [ ] Tema escuro usa `--surface-*`/`--popover`/`--dialog`, não sombra preta.
- [ ] Badges combinam token `*-fade` com `*-foreground`.
- [ ] Tabelas ficam dentro de cards e mantêm header visualmente distinto.
- [ ] Loading usa spinner ou skeleton; estado disabled reduz opacidade.
- [ ] Ícones funcionais usam `fi fi-rr-*`.

## Produto

- [ ] A tela usa termos do WhatsAya: lead, conversa, atendimento, handoff,
      follow-up, fila e conexão.
- [ ] Ações têm rótulos concretos e deixam a consequência explícita.
- [ ] Verde está reservado a WhatsApp, conexão e sucesso.
- [ ] Laranja identifica CTA principal, seleção e alerta.
- [ ] A interface não envia mensagem por um caminho que contorne o fluxo oficial
      do bot.

## Qualidade

- [ ] Todos os assets e imports locais resolvem.
- [ ] JSX e JavaScript passam em verificação sintática/lint.
- [ ] Os previews principais foram abertos em viewport desktop e mobile.
- [ ] Contraste e foco por teclado foram conferidos.
- [ ] Manifesto e bundle foram atualizados depois da mudança.
