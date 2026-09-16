// Páginas de nicho da aba Marketing (admin). Lista em tabela (padrão) ou cards,
// cada página com funil de 30 dias e diagnóstico vindos de /api/marketing/pages.
// Criar e editar é um stepper em tela cheia, uma seção por tela, com blocos
// para dores, opções e provas sociais em vez de um textarea por lista. Salvar publica.
import { useEffect, useState } from 'preact/hooks';
import { html, useApi, post, fmt, Empty, ErrorBox } from '../lib.js';

const STEPS = [
  { id: 'identidade', label: 'Identidade', hint: 'Endereço, nicho e o que o Google mostra.' },
  { id: 'abertura', label: 'Abertura', hint: 'A primeira tela: título e subtítulo.' },
  { id: 'nicho', label: 'Bloco do nicho', hint: 'O texto que fala com esse segmento. É o que dá SEO próprio à página.' },
  { id: 'quiz', label: 'Pergunta do quiz', hint: 'Substitui "Qual é o seu negócio?" e vai na mensagem do WhatsApp.' },
  { id: 'prova', label: 'Prova social', hint: 'Frases no rodapé durante o quiz. Marque a opção para personalizar.' },
  { id: 'publicar', label: 'Publicação', hint: 'Pixel, estado e o botão que gera o HTML.' },
];
const EMPTY_PAGE = {
  slug: '', niche: '', title: '', description: '', h1: '', sub: '', niche_intro: '', niche_pains: [],
  question: 'Qual é a sua atuação?', question_sub: 'Isso muda o jeito da AYA falar com quem chega.', options: [],
  pixel_id: '', enabled: true, proofs: [],
};
const LIMITS = { title: 120, description: 300, h1: 160, sub: 400, niche: 80, niche_intro: 1200, question: 160, question_sub: 300 };
const MODE_KEY = 'mk_pages_mode';

const pageUrl = (base, slug) => `${base || ''}/${slug ? slug + '/' : ''}`;
const pagePath = (slug) => (slug ? `/${slug}/` : '/ (raiz)');
const stepReady = (i, d) => [
  () => d.title.trim() && d.description.trim(),
  () => d.h1.trim(),
  () => true,
  () => d.question.trim() && d.options.filter((o) => o.trim()).length >= 2,
  () => true,
  () => true,
][i]();

function Counter({ value, limit }) {
  const n = (value || '').length;
  return html`<small class=${'mk-counter' + (n > limit ? ' over' : '')}>${n}/${limit}</small>`;
}

function Text({ label, value, onInput, limit, hint, required, multiline, placeholder, mono }) {
  return html`<label class="field-label mk-field"><span class="mk-field-head">${label}${required ? html`<i>*</i>` : null}${limit ? html`<${Counter} value=${value} limit=${limit}/>` : null}</span>
    ${multiline
      ? html`<textarea class="input" value=${value} onInput=${onInput} placeholder=${placeholder || ''} maxlength=${limit || undefined}></textarea>`
      : html`<input class=${'input' + (mono ? ' mk-mono' : '')} value=${value} onInput=${onInput} placeholder=${placeholder || ''} maxlength=${limit || undefined}/>`}
    ${hint ? html`<small class="mk-hint">${hint}</small>` : null}
  </label>`;
}

// Lista de blocos: um item por linha com remover, Enter adiciona o próximo.
function Blocks({ label, items, onChange, placeholder, min = 0, max = 8, hint }) {
  const set = (i, value) => onChange(items.map((item, j) => (j === i ? value : item)));
  const remove = (i) => onChange(items.filter((_, j) => j !== i));
  const add = () => { if (items.length < max) onChange([...items, '']); };
  return html`<div class="mk-blocks">
    <span class="mk-field-head">${label}${min ? html`<i>*</i>` : null}<small class="mk-counter">${items.length}/${max}</small></span>
    ${items.length === 0 ? html`<div class="mk-blocks-empty">${placeholder}</div>` : null}
    ${items.map((item, i) => html`<div class="mk-block" key=${i}>
      <span class="mk-block-n">${i + 1}</span>
      <input class="input" value=${item} placeholder=${placeholder} onInput=${(e) => set(i, e.target.value)}
        onKeyDown=${(e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } }}/>
      <button type="button" class="btn sm mk-block-remove" aria-label="Remover" onClick=${() => remove(i)}>×</button>
    </div>`)}
    <button type="button" class="btn sm" disabled=${items.length >= max} onClick=${add}>+ Adicionar</button>
    ${hint ? html`<small class="mk-hint">${hint}</small>` : null}
  </div>`;
}

// Provas sociais como blocos de três campos; a opção vem das opções do quiz.
function ProofBlocks({ items, options, onChange }) {
  const set = (i, patch) => onChange(items.map((item, j) => (j === i ? { ...item, ...patch } : item)));
  const remove = (i) => onChange(items.filter((_, j) => j !== i));
  const add = () => { if (items.length < 24) onChange([...items, { option: '', who: 'AYA', quote: '' }]); };
  return html`<div class="mk-blocks">
    <span class="mk-field-head">Provas sociais<small class="mk-counter">${items.length}/24</small></span>
    ${items.length === 0 ? html`<div class="mk-blocks-empty">Nenhuma frase ainda. Sem frases, o toast não aparece.</div>` : null}
    ${items.map((item, i) => html`<div class="mk-proof" key=${i}>
      <div class="mk-proof-row">
        <select class="input" value=${item.option || ''} onChange=${(e) => set(i, { option: e.target.value })} aria-label="Para quem">
          <option value="">Para todos</option>
          ${options.filter(Boolean).map((o) => html`<option value=${o} key=${o}>${o}</option>`)}
        </select>
        <input class="input" value=${item.who || ''} placeholder="Quem disse (ex.: AYA, ou nome e cargo)" onInput=${(e) => set(i, { who: e.target.value })}/>
        <button type="button" class="btn sm mk-block-remove" aria-label="Remover" onClick=${() => remove(i)}>×</button>
      </div>
      <textarea class="input" value=${item.quote || ''} placeholder="A frase, curta e concreta." onInput=${(e) => set(i, { quote: e.target.value })}></textarea>
    </div>`)}
    <button type="button" class="btn sm" disabled=${items.length >= 24} onClick=${add}>+ Adicionar frase</button>
    <small class="mk-hint">Não invente depoimento com nome de cliente. Frases da própria AYA valem; depoimento real substitui depois.</small>
  </div>`;
}

function Funnel({ s }) {
  const rows = [['Viram', s.view], ['Começaram', s.start], ['Terminaram', s.complete], ['Clicaram', s.whatsapp_click], ['Chegaram', s.arrived]];
  const max = Math.max(1, s.view);
  return html`<div class="mk-funnel">${rows.map(([label, value]) => html`<div class="mk-funnel-row" key=${label}>
    <span>${label}</span><i><b style=${`width:${Math.max(2, (value / max) * 100)}%`}></b></i><em>${fmt.int(value)}</em>
  </div>`)}</div>`;
}

function Insight({ insight, compact }) {
  return html`<div class=${'mk-insight ' + insight.tone + (compact ? ' compact' : '')}><span class="dot"></span><span>${insight.text}</span></div>`;
}

function PageEditor({ initial, isNew, baseUrl, pages, onClose, onSaved, setToast }) {
  const [draft, setDraft] = useState({ ...EMPTY_PAGE, ...initial });
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const set = (key) => (e) => setDraft((d) => ({ ...d, [key]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }));
  const patch = (key) => (value) => setDraft((d) => ({ ...d, [key]: value }));
  const current = STEPS[step];
  const ready = stepReady(step, draft);
  const slugTaken = isNew && pages.some((p) => p.slug === draft.slug.trim().toLowerCase());
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    addEventListener('keydown', onKey);
    return () => removeEventListener('keydown', onKey);
  }, [onClose]);

  const save = async () => {
    setSaving(true);
    try {
      const payload = { ...draft, slug: draft.slug.trim().toLowerCase(), niche_pains: draft.niche_pains.filter((x) => x.trim()),
        options: draft.options.filter((x) => x.trim()), proofs: draft.proofs.filter((p) => (p.quote || '').trim()) };
      const result = await post('/api/actions/marketing/page-save', payload);
      setToast(result.published ? `${pagePath(payload.slug)} publicada` : result.warning || 'Salvo, não publicado');
      onSaved();
    } catch (err) { setToast(`Não consegui salvar: ${err.message}`); }
    finally { setSaving(false); }
  };
  const remove = async () => {
    if (!confirmDelete) { setConfirmDelete(true); return; }
    try {
      const result = await post('/api/actions/marketing/page-delete', { slug: draft.slug });
      setToast(result.published ? `${pagePath(draft.slug)} apagada e site republicado` : result.warning || 'Apagada');
      onSaved();
    } catch (err) { setToast(`Não consegui apagar: ${err.message}`); }
  };

  return html`<div class="mk-editor" role="dialog" aria-modal="true" aria-label=${isNew ? 'Nova página' : `Editar ${pagePath(draft.slug)}`}>
    <header class="mk-editor-head">
      <button type="button" class="btn sm" onClick=${onClose}>‹ Páginas</button>
      <div class="mk-editor-title"><span class="kpi-eyebrow">${isNew ? 'Nova página' : pagePath(draft.slug)}</span><b>Passo ${step + 1} de ${STEPS.length} · ${current.label}</b></div>
      <i class="mk-progress"><b style=${`width:${((step + 1) / STEPS.length) * 100}%`}></b></i>
      <ol class="mk-stepper">${STEPS.map((s, i) => html`<li key=${s.id} class=${i === step ? 'current' : i < step ? 'done' : ''}><button type="button" onClick=${() => setStep(i)} disabled=${i > step && !ready}><i>${i < step ? '✓' : i + 1}</i><span>${s.label}</span></button></li>`)}</ol>
    </header>

    <section class="mk-editor-body">
      <h2>${current.label}</h2>
      <p class="mk-editor-hint">${current.hint}</p>
      ${current.id === 'identidade' ? html`
        <div class="mk-two">
          <${Text} label="Slug" value=${draft.slug} onInput=${set('slug')} mono placeholder="psicologos" hint=${slugTaken ? 'Já existe uma página com esse slug.' : `Vira ${pageUrl(baseUrl, draft.slug.trim().toLowerCase())}. Vazio é a raiz.`}/>
          <${Text} label="Nicho" value=${draft.niche} onInput=${set('niche')} limit=${LIMITS.niche} placeholder="Clínica de psicologia" hint="Entra na mensagem do WhatsApp antes da resposta do quiz."/>
        </div>
        <${Text} label="Título SEO" value=${draft.title} onInput=${set('title')} limit=${LIMITS.title} required placeholder="AYA para psicólogos — atendimento no WhatsApp sem perder paciente"/>
        <${Text} label="Descrição para o Google" value=${draft.description} onInput=${set('description')} limit=${LIMITS.description} required multiline hint="Entre 120 e 155 caracteres é o que aparece inteiro no resultado."/>
      ` : current.id === 'abertura' ? html`
        <${Text} label="Título da abertura (H1)" value=${draft.h1} onInput=${set('h1')} limit=${LIMITS.h1} required placeholder="Quantos pacientes você perde enquanto está em sessão?"/>
        <${Text} label="Subtítulo" value=${draft.sub} onInput=${set('sub')} limit=${LIMITS.sub} multiline hint="Use **assim** para destacar um trecho em laranja."/>
      ` : current.id === 'nicho' ? html`
        <${Text} label="Texto do nicho" value=${draft.niche_intro} onInput=${set('niche_intro')} limit=${LIMITS.niche_intro} multiline placeholder="Quem procura terapia costuma escrever num momento difícil e decide rápido."/>
        <${Blocks} label="Dores do nicho" items=${draft.niche_pains} onChange=${patch('niche_pains')} placeholder="Paciente pergunta o valor e some" hint="Cada dor vira um item com marcador laranja na abertura e um sub-item no llms.txt."/>
      ` : current.id === 'quiz' ? html`
        <${Text} label="Pergunta" value=${draft.question} onInput=${set('question')} limit=${LIMITS.question} required/>
        <${Text} label="Complemento" value=${draft.question_sub} onInput=${set('question_sub')} limit=${LIMITS.question_sub}/>
        <${Blocks} label="Opções" items=${draft.options} onChange=${patch('options')} placeholder="Clínica com pacientes particulares" min=${2} hint='Mínimo duas. "Outro" abre um campo de texto para a pessoa escrever.'/>
      ` : current.id === 'prova' ? html`
        <${ProofBlocks} items=${draft.proofs} options=${draft.options} onChange=${patch('proofs')}/>
      ` : html`
        <${Text} label="Pixel da Meta" value=${draft.pixel_id} onInput=${set('pixel_id')} mono placeholder="só dígitos; vazio desliga" hint="Cada página pode ter o seu. Vazio não carrega o script."/>
        <label class="field-label settings-check mk-switch"><span>Página no ar</span><input type="checkbox" class="switch" checked=${draft.enabled} onChange=${set('enabled')}/><small>Desligada, o endereço redireciona para a raiz e sai do sitemap.</small></label>
        <div class="mk-summary">
          <div><span>Endereço</span><b>${pageUrl(baseUrl, draft.slug.trim().toLowerCase())}</b></div>
          <div><span>Título</span><b>${draft.title || '—'}</b></div>
          <div><span>Pergunta</span><b>${draft.question} · ${draft.options.filter((o) => o.trim()).length} opções</b></div>
          <div><span>Dores e provas</span><b>${draft.niche_pains.filter((x) => x.trim()).length} dores · ${draft.proofs.filter((p) => (p.quote || '').trim()).length} frases</b></div>
        </div>
        ${!isNew && draft.slug ? html`<div class="mk-danger"><span>Apagar remove o registro e o HTML na próxima publicação. Prefira desligar.</span><button type="button" class=${'btn sm' + (confirmDelete ? ' danger' : '')} onClick=${remove}>${confirmDelete ? 'Confirmar exclusão' : 'Apagar página'}</button></div>` : null}
      `}
    </section>

    <footer class="mk-editor-foot">
      <button type="button" class="btn" disabled=${step === 0} onClick=${() => setStep(step - 1)}>Voltar</button>
      ${step < STEPS.length - 1
        ? html`<button type="button" class="btn primary" disabled=${!ready || slugTaken} onClick=${() => setStep(step + 1)}>Continuar</button>`
        : html`<button type="button" class="btn primary" disabled=${saving || slugTaken} onClick=${save}>${saving ? 'Publicando…' : 'Salvar e publicar'}</button>`}
    </footer>
  </div>`;
}

export default function Pages({ setToast }) {
  const pages = useApi('/api/marketing/pages', { every: 60000 });
  const [mode, setMode] = useState(() => { try { return localStorage.getItem(MODE_KEY) || 'table'; } catch { return 'table'; } });
  const [sort, setSort] = useState('arrived');
  const [editing, setEditing] = useState(null);
  const p = pages.data;
  const list = p ? p.pages : [];
  const choose = (next) => { setMode(next); try { localStorage.setItem(MODE_KEY, next); } catch { /* sem storage */ } };
  const sorted = [...list].sort((a, b) => (sort === 'slug' ? a.slug.localeCompare(b.slug) : (b.stats[sort] || 0) - (a.stats[sort] || 0)));
  const th = (key, label) => html`<th class=${key === 'slug' ? '' : 'num'}><button type="button" class=${'mk-sort' + (sort === key ? ' active' : '')} onClick=${() => setSort(key)}>${label}</button></th>`;

  if (editing) {
    return html`<${PageEditor} initial=${editing.page} isNew=${editing.isNew} baseUrl=${p && p.base_url} pages=${list}
      onClose=${() => setEditing(null)} onSaved=${() => { setEditing(null); pages.reload(); }} setToast=${setToast}/>`;
  }

  return html`<section class="mk-pages" aria-label="Páginas de nicho">
    <header class="mk-pages-head">
      <div><span class="kpi-eyebrow">Páginas</span><h2>${list.length ? `${list.length} páginas · últimos 30 dias` : 'Páginas de nicho'}</h2></div>
      <div class="mk-pages-tools">
        <div class="segment" role="tablist" aria-label="Modo de exibição">
          <button type="button" role="tab" class=${mode === 'table' ? 'active' : ''} aria-selected=${mode === 'table'} onClick=${() => choose('table')}>Tabela</button>
          <button type="button" role="tab" class=${mode === 'cards' ? 'active' : ''} aria-selected=${mode === 'cards'} onClick=${() => choose('cards')}>Cards</button>
        </div>
        <button type="button" class="btn primary sm" onClick=${() => setEditing({ page: EMPTY_PAGE, isNew: true })}>Nova página</button>
      </div>
    </header>
    <${ErrorBox} error=${pages.error}/>
    ${p && !p.template_ready ? html`<div class="overview-warning"><span class="dot bad"></span><span><b>Template mestre não encontrado no volume</b><small>Sem ele, salvar guarda o registro mas não gera a página.</small></span></div>` : null}
    ${p && !p.base_url ? html`<div class="overview-warning"><span class="dot warn"></span><span><b>Falta marketing.base_url no panel.config.json</b><small>É o domínio do canonical e do sitemap.</small></span></div>` : null}
    ${p && list.length === 0 ? html`<${Empty}>Nenhuma página ainda. A raiz do site é a primeira.</${Empty}>` : null}

    ${mode === 'table' && list.length ? html`<div class="card mk-table-card"><div class="mk-table-scroll"><table class="plain mk-table">
      <thead><tr>${th('slug', 'Página')}<th>Status</th>${th('view', 'Sessões')}${th('whatsapp_click', 'Cliques')}${th('click_rate', '% clique')}${th('arrived', 'Chegaram')}${th('arrive_rate', '% chegada')}<th>Diagnóstico</th><th></th></tr></thead>
      <tbody>${sorted.map((page) => html`<tr key=${page.slug || '/'}>
        <td><b>${pagePath(page.slug)}</b><small class="mk-sub">${page.niche || 'Geral'}</small></td>
        <td><span class=${'status-pill ' + (page.enabled ? 'ok' : 'warn')}>${page.enabled ? 'No ar' : 'Pausada'}</span></td>
        <td class="num">${fmt.int(page.stats.view)}</td>
        <td class="num">${fmt.int(page.stats.whatsapp_click)}</td>
        <td class="num">${page.stats.click_rate}%</td>
        <td class="num"><b>${fmt.int(page.stats.arrived)}</b></td>
        <td class="num">${page.stats.arrive_rate}%</td>
        <td><${Insight} insight=${page.insight} compact/></td>
        <td class="mk-actions"><button type="button" class="btn sm" onClick=${() => setEditing({ page, isNew: false })}>Editar</button><a class="btn sm" href=${pageUrl(p.base_url, page.slug)} target="_blank" rel="noopener">Abrir</a></td>
      </tr>`)}</tbody>
    </table></div></div>` : null}

    ${mode === 'cards' && list.length ? html`<div class="mk-cards">
      ${sorted.map((page) => html`<article class="card mk-card" key=${page.slug || '/'}>
        <header><div><b>${page.niche || 'Página raiz'}</b><small class="mk-sub">${pagePath(page.slug)}</small></div><span class=${'status-pill ' + (page.enabled ? 'ok' : 'warn')}>${page.enabled ? 'No ar' : 'Pausada'}</span></header>
        <div class="mk-kpis"><div><b>${fmt.int(page.stats.view)}</b><span>sessões</span></div><div><b>${page.stats.click_rate}%</b><span>clicam</span></div><div><b>${fmt.int(page.stats.arrived)}</b><span>chegaram</span></div></div>
        <${Funnel} s=${page.stats}/>
        <${Insight} insight=${page.insight}/>
        <footer><button type="button" class="btn sm primary" onClick=${() => setEditing({ page, isNew: false })}>Editar</button><a class="btn sm" href=${pageUrl(p.base_url, page.slug)} target="_blank" rel="noopener">Abrir</a></footer>
      </article>`)}
    </div>` : null}
  </section>`;
}
