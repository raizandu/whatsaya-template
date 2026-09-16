// Marketing: o funil das landing pages cruzado com quem de fato chegou no
// WhatsApp. Lê só GET /api/marketing (features.marketing). Sessão é aba do
// navegador; "chegou" é a primeira mensagem viva do contato com o id da LP ou
// com origem nativa de anúncio (Click-to-WhatsApp).
import { useState } from 'preact/hooks';
import { html, useApi, post, fmt, Tile, Card, ErrorBox, Empty, BarChart, dateTime, isAdmin } from '../lib.js';

const PERIOD_LABEL = { hoje: 'hoje', '7d': 'nos últimos 7 dias', '30d': 'nos últimos 30 dias' };
const STEP_LABEL = { view: 'Viram', start: 'Começaram', complete: 'Terminaram', whatsapp_click: 'Clicaram no WhatsApp', arrived: 'Chegaram no WhatsApp' };

const dayLabel = (iso) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;

function originLabel(origin) {
  if (origin.medium === 'nativa') return html`<span>${origin.source}</span><span class="tag">anúncio nativo</span>`;
  const parts = [origin.source, origin.medium, origin.campaign].filter(Boolean);
  return html`<span>${parts.join(' · ')}</span>`;
}

const EMPTY_PAGE = {
  slug: '', niche: '', title: '', description: '', h1: '', sub: '', niche_intro: '', niche_pains: '',
  question: 'Qual é a sua atuação?', question_sub: '', options: '', pixel_id: '', enabled: true,
};
const lines = (value) => (Array.isArray(value) ? value.join('\n') : value || '');

// Páginas de nicho (admin): registro no painel, HTML gerado no volume ao salvar.
function PagesCard({ setToast }) {
  const pages = useApi('/api/marketing/pages', { every: 0 });
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState('');
  const p = pages.data;
  const set = (key) => (event) => setForm((f) => ({ ...f, [key]: event.target.type === 'checkbox' ? event.target.checked : event.target.value }));
  const edit = (page) => setForm({ ...EMPTY_PAGE, ...page, niche_pains: lines(page.niche_pains), options: lines(page.options) });
  const publicUrl = (slug) => `${p && p.base_url ? p.base_url : ''}/${slug ? slug + '/' : ''}`;

  const save = async (event) => {
    event.preventDefault();
    setSaving(true);
    try {
      const result = await post('/api/actions/marketing/page-save', form);
      setToast(result.published ? `Página ${form.slug || 'raiz'} publicada` : result.warning || 'Salvo, não publicado');
      setForm(null); pages.reload();
    } catch (err) { setToast(`Não consegui salvar: ${err.message}`); }
    finally { setSaving(false); }
  };
  const remove = async (slug) => {
    if (confirmDelete !== slug) { setConfirmDelete(slug); return; }
    try {
      const result = await post('/api/actions/marketing/page-delete', { slug });
      setToast(result.published ? `Página ${slug} apagada e site republicado` : result.warning || 'Apagada');
      setConfirmDelete(''); pages.reload();
    } catch (err) { setToast(`Não consegui apagar: ${err.message}`); }
  };

  return html`<${Card} title="Páginas" sub="Uma página por nicho: título, texto de abertura e a pergunta do quiz próprios. Salvar já publica o HTML e o sitemap."
    action=${html`<button type="button" class="btn primary sm" onClick=${() => setForm(form ? null : { ...EMPTY_PAGE })}>${form ? 'Fechar' : 'Nova página'}</button>`}>
    <${ErrorBox} error=${pages.error}/>
    ${p && !p.template_ready ? html`<div class="overview-warning"><span class="dot bad"></span><span><b>Template mestre não encontrado no volume</b><small>Sem ele, salvar guarda o registro mas não gera a página.</small></span></div>` : null}
    ${p && !p.base_url ? html`<div class="overview-warning"><span class="dot warn"></span><span><b>Falta marketing.base_url no panel.config.json</b><small>É o domínio do canonical e do sitemap.</small></span></div>` : null}
    ${form ? html`<form class="page-form" style="display:grid;gap:12px;margin-bottom:16px" onSubmit=${save}>
      <div class="grid c2" style="gap:12px">
        <label class="field-label">Slug<input class="input" value=${form.slug} onInput=${set('slug')} placeholder="ex.: psicologos (vazio = raiz)" pattern="[a-z0-9-]*"/><small style="font-weight:400;color:var(--muted)">Vira ${publicUrl(form.slug)}</small></label>
        <label class="field-label">Nicho<input class="input" value=${form.niche} onInput=${set('niche')} placeholder="ex.: Clínica de psicologia"/><small style="font-weight:400;color:var(--muted)">Entra na mensagem do WhatsApp antes da resposta do quiz.</small></label>
      </div>
      <label class="field-label">Título SEO<input class="input" value=${form.title} onInput=${set('title')} maxlength="120" required/></label>
      <label class="field-label">Descrição (meta)<textarea class="input" value=${form.description} onInput=${set('description')} maxlength="300" required></textarea></label>
      <label class="field-label">Título da abertura (H1)<input class="input" value=${form.h1} onInput=${set('h1')} maxlength="160" required/></label>
      <label class="field-label">Subtítulo<textarea class="input" value=${form.sub} onInput=${set('sub')} maxlength="400"></textarea><small style="font-weight:400;color:var(--muted)">Use **assim** para destacar um trecho em laranja.</small></label>
      <div class="grid c2" style="gap:12px">
        <label class="field-label">Texto do nicho<textarea class="input" value=${form.niche_intro} onInput=${set('niche_intro')} maxlength="1200" placeholder="Um parágrafo falando com esse nicho."></textarea></label>
        <label class="field-label">Dores do nicho (uma por linha)<textarea class="input" value=${form.niche_pains} onInput=${set('niche_pains')} placeholder="Paciente pergunta valor e some"></textarea></label>
      </div>
      <div class="grid c2" style="gap:12px">
        <label class="field-label">Pergunta do quiz<input class="input" value=${form.question} onInput=${set('question')} maxlength="160" required/><small style="font-weight:400;color:var(--muted)">Substitui "Qual é o seu negócio?".</small></label>
        <label class="field-label">Opções (uma por linha, mínimo 2)<textarea class="input" value=${form.options} onInput=${set('options')} required placeholder=${'Clínico\nOrganizacional\nOutro'}></textarea></label>
      </div>
      <div class="grid c2" style="gap:12px">
        <label class="field-label">Complemento da pergunta<input class="input" value=${form.question_sub} onInput=${set('question_sub')} maxlength="300"/></label>
        <label class="field-label">Pixel da Meta<input class="input" value=${form.pixel_id} onInput=${set('pixel_id')} inputmode="numeric" placeholder="só dígitos; vazio desliga"/></label>
      </div>
      <label class="field-label settings-check"><span>Página no ar</span><input type="checkbox" class="switch" checked=${form.enabled} onChange=${set('enabled')}/><small>Desligada, o endereço redireciona para a raiz e sai do sitemap.</small></label>
      <div class="form-row"><button class="btn primary" type="submit" disabled=${saving}>${saving ? 'Publicando…' : 'Salvar e publicar'}</button><button class="btn" type="button" onClick=${() => setForm(null)}>Cancelar</button></div>
    </form>` : null}
    ${p && p.pages.length === 0 ? html`<${Empty}>Nenhuma página ainda. A raiz do site é a primeira.</${Empty}>` : null}
    <div class="row-list">${p ? p.pages.map((page) => html`<div class="item" key=${page.slug || '/'} style="padding:10px 0">
      <span class=${'dot ' + (page.enabled ? 'ok' : 'off')}></span>
      <div class="grow">
        <span class="name" style="font-size:13px">${page.slug ? `/${page.slug}/` : '/ (raiz)'}${page.niche ? html` <span style="font-weight:400;color:var(--muted-2)">· ${page.niche}</span>` : null}</span>
        <span class="meta">${page.title}${page.pixel_id ? ' · Pixel ligado' : ''}</span>
      </div>
      <a class="btn sm" href=${publicUrl(page.slug)} target="_blank" rel="noopener">Abrir</a>
      <button type="button" class="btn sm" onClick=${() => edit(page)}>Editar</button>
      ${page.slug ? html`<button type="button" class=${'btn sm' + (confirmDelete === page.slug ? ' danger' : '')} onClick=${() => remove(page.slug)}>${confirmDelete === page.slug ? 'Confirmar' : 'Apagar'}</button>` : null}
    </div>`) : null}</div>
  </${Card}>`;
}

export default function Marketing({ period, config, me, go, setToast }) {
  const report = useApi(`/api/marketing?period=${period}`, { every: 60000 });
  const r = report.data;
  const t = r ? r.totals : null;
  const periodLabel = PERIOD_LABEL[period] || PERIOD_LABEL['7d'];
  const stages = (config && config.pipeline && config.pipeline.stages) || [];
  const stageLabel = (id) => (stages.find((s) => s.id === id) || {}).label || id || 'sem etapa';

  return html`
    <${ErrorBox} error=${report.error}/>
    <div class="grid c4">
      <${Tile} dark label="Sessões na LP" value=${t ? fmt.int(t.sessions) : '…'} sub=${periodLabel}/>
      <${Tile} label="Clicaram no WhatsApp" value=${t ? fmt.int(t.clicks) : '…'} pct=${t ? fmt.pct(t.clicks, t.sessions) : ''} sub="das sessões"/>
      <${Tile} label="Chegaram no WhatsApp" green value=${t ? fmt.int(t.arrived) : '…'} sub=${t ? `${fmt.int(t.arrived_lp)} pela LP · ${fmt.int(t.arrived_native)} por anúncio nativo` : 'carregando'}/>
      <${Tile} label="No funil de leads" value=${t ? fmt.int(t.in_funnel) : '…'} sub=${t ? `${fmt.int(t.won)} ${t.won === 1 ? 'ganho' : 'ganhos'}` : 'carregando'}/>
    </div>

    <div class="grid wide-15 start">
      <div style="display:flex;flex-direction:column;gap:16px">
        <${Card} title="Funil da landing page" sub="Sessões únicas em cada passo. Chegou no WhatsApp é a primeira mensagem com o id da sessão.">
          ${r && r.lps.length === 0 ? html`<${Empty}>Nenhuma sessão na LP ${periodLabel}. O beacon da página grava aqui assim que alguém abrir.</${Empty}>` : null}
          ${r && r.lps.length ? html`<table class="plain">
            <thead><tr><th>Landing page</th>${Object.values(STEP_LABEL).map((label) => html`<th class="num" key=${label}>${label}</th>`)}</tr></thead>
            <tbody>${r.lps.map((lp) => html`<tr key=${lp.lp}>
              <td><b>${lp.lp}</b></td>
              ${Object.keys(STEP_LABEL).map((step) => html`<td class="num" key=${step}>${fmt.int(lp[step])}${step !== 'view' && lp.view ? html`<small style="color:var(--muted-2)"> · ${fmt.pct(lp[step], lp.view)}</small>` : null}</td>`)}
            </tr>`)}</tbody>
          </table>` : null}
        </${Card}>

        <${Card} title="Por origem" sub="UTM da sessão da LP, ou o referral que o WhatsApp entrega quando o lead vem de anúncio.">
          ${r && r.origins.length === 0 ? html`<${Empty}>Nenhuma origem registrada ${periodLabel}.</${Empty}>` : null}
          ${r && r.origins.length ? html`<table class="plain">
            <thead><tr><th>Origem</th><th class="num">Sessões</th><th class="num">Cliques</th><th class="num">Chegaram</th><th class="num">No funil</th><th class="num">Ganhos</th></tr></thead>
            <tbody>${r.origins.map((o) => html`<tr key=${`${o.source}|${o.medium}|${o.campaign}`}>
              <td><div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">${originLabel(o)}</div></td>
              <td class="num">${o.medium === 'nativa' ? '—' : fmt.int(o.sessions)}</td>
              <td class="num">${o.medium === 'nativa' ? '—' : fmt.int(o.clicks)}</td>
              <td class="num"><b>${fmt.int(o.arrived)}</b></td>
              <td class="num">${fmt.int(o.in_funnel)}</td>
              <td class="num">${fmt.int(o.won)}</td>
            </tr>`)}</tbody>
          </table>` : null}
        </${Card}>
      </div>

      <div style="display:flex;flex-direction:column;gap:16px">
        <${Card} title="Movimento do período" sub=${period === 'hoje' ? 'Hoje' : period === '7d' ? 'Últimos 7 dias' : 'Últimos 30 dias'}
          action=${html`<div class="legend"><span><i class="swatch" style="background:var(--green)"></i>Chegaram no WhatsApp</span><span><i class="swatch" style="background:var(--orange)"></i>Clicaram na LP</span></div>`}>
          ${r ? html`<${BarChart} series=${r.days.map((d) => ({ label: dayLabel(d.date), a: d.arrived, b: d.clicks }))} tip=${(s) => `${s.a} chegaram · ${s.b} clicaram`}/>` : null}
        </${Card}>

        ${isAdmin(me) ? html`<${PagesCard} setToast=${setToast}/>` : null}

        <${Card} title="Leads com origem" sub="Quem chegou no período e de onde veio.">
          ${r && r.arrivals.length === 0 ? html`<${Empty}>Nenhum lead com origem ${periodLabel}.</${Empty}>` : null}
          <div class="row-list">${r ? r.arrivals.slice(0, 30).map((a) => html`<div class="item" key=${a.chat_id} style="padding:10px 0">
            <span class="avatar">${fmt.initials(a.name || a.chat_id)}</span>
            <div class="grow">
              <span class="name" style="font-size:13px">${a.name || a.chat_id.split('@')[0]}</span>
              <span class="meta">${a.kind === 'lp' ? `LP · ${[a.source, a.medium].filter(Boolean).join(' / ')}` : `anúncio · ${a.source}`} · ${stageLabel(a.stage)}</span>
            </div>
            <span class="when">${dateTime(a.arrived_at, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
            <button type="button" class="btn sm" onClick=${() => go(`lead/${encodeURIComponent(a.chat_id)}`)}>Ver lead</button>
          </div>`) : null}</div>
        </${Card}>
      </div>
    </div>`;
}
