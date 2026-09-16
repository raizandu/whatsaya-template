// Aba Atendimento (#atendimento e #atendimento/<chat_id>): filas à esquerda,
// conversa com o composer compartilhado no meio, painel do contato à direita.
// A lista e a conversa aberta se atualizam sozinhas; quem move atendimento é a
// API (assumir, devolver, resolver, reatribuir) e a reconciliação do servidor.
import { useEffect, useState } from 'preact/hooks';
import { html, Fragment, api, useApi, post, fmt, ErrorBox, Empty, Icon, Select, isAdmin as isAdminUser, dateTime, normalize, DEFAULT_STAGES, MEETING_OUTCOMES, VER_TODOS } from '../lib.js';
import { Conversation, Composer } from './conversation.js';

const canSeeAll = (me) => !!me && (me.role === 'admin' || (me.permissions || []).includes(VER_TODOS));

const EVENTO_LABEL = {
  aberto: 'Atendimento aberto', assumido: 'Assumido', devolvido: 'Devolvido para a IA',
  devolvido_auto: 'Devolvido para a IA automaticamente', resolvido: 'Resolvido', handoff: 'A IA pediu um humano',
  reatribuido: 'Reatribuído', responsavel_removido: 'Ficou sem responsável',
};

const filas = (assistantName, verTodos) => [
  ['meus', 'Meus'],
  ['sem_responsavel', 'Sem responsável'],
  ...(verTodos ? [['com_ia', `Com a ${assistantName}`], ['todos', 'Todos']] : []),
];

const rel = (seconds) => {
  const s = Math.max(0, Math.floor(seconds || 0));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  if (s < 86400) return `${Math.floor(s / 3600)} h`;
  return `${Math.floor(s / 86400)} d`;
};
const hhmm = (iso) => (iso ? new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '—');
// Silêncio temporizado do bridge, com quem o causou. Handoff tem chip próprio.
const SILENCIO_LABEL = { leitura: 'Dono leu', dono: 'Dono respondeu', painel: 'Painel silenciou' };

function nomeDe(responsavel, assistantName, users) {
  if (!responsavel) return '';
  if (responsavel.tipo === 'ia') return assistantName;
  if (responsavel.tipo === 'dono') return 'Dono';
  if (responsavel.tipo === 'atendente') {
    const user = (users || []).find((u) => u.username === responsavel.user);
    return user ? user.name : responsavel.user;
  }
  return 'Sem responsável';
}

function Responsavel({ responsavel, assistantName, users }) {
  const tipo = responsavel ? responsavel.tipo : 'nenhum';
  const tone = tipo === 'nenhum' ? 'orange' : tipo === 'ia' ? 'mint' : '';
  return html`<span class=${`tag ${tone}`}>${nomeDe(responsavel, assistantName, users)}</span>`;
}

function SlaClock({ titulo, sla, alvo }) {
  return html`<div class=${`atd-sla${sla.estourado ? ' estourado' : ''}`}>
    <span>${titulo}</span><b>${rel(sla.decorrido_s)}</b><small>alvo ${alvo}${sla.estourado ? ' · estourado' : ''}</small>
  </div>`;
}

function FilaRow({ item, active, onSelect, assistantName, users }) {
  const espera = item.aguardando_nos ? `aguardando há ${rel(item.espera_s)}` : null;
  const estourado = item.sla.primeira.estourado || item.sla.resolucao.estourado;
  return html`<button type="button" class=${`contacts-row atd-row${active ? ' active' : ''}${item.aguardando_nos ? ' urgent' : ''}`} onClick=${() => onSelect(item)} aria-current=${active ? 'true' : null}>
    <span class="contacts-avatar">${fmt.initials(item.nome)}</span>
    <span class="contacts-row-main">
      <span class="contacts-row-top"><b>${item.nome}</b><time>${hhmm(item.ultima_msg_utc)}</time></span>
      <span class="atd-row-preview">${item.preview || 'Sem mensagem recente'}</span>
      <span class="atd-row-bottom">
        <${Responsavel} responsavel=${item.responsavel} assistantName=${assistantName} users=${users}/>
        ${espera ? html`<small class="atd-espera">${espera}</small>` : null}
        ${estourado ? html`<small class="atd-estourado">SLA</small>` : null}
      </span>
    </span>
  </button>`;
}

// Eventos do atendimento entram na timeline como eventos de sistema, ao lado
// do handoff e dos follow-ups que a conversa já mostra.
function timelineComEventos(detail) {
  const eventos = (detail.atendimento && detail.atendimento.eventos) || [];
  const extras = eventos.map((e) => ({
    type: 'event', event: 'atendimento', at: e.at_utc,
    label: EVENTO_LABEL[e.tipo] || e.tipo,
    reason: [e.ator !== 'sistema' && e.ator !== 'ia' ? `por ${e.ator}` : null, e.detalhe].filter(Boolean).join(' · ') || null,
  }));
  if (!extras.length) return detail.timeline;
  return [...detail.timeline, ...extras].sort((a, b) => String(a.at || '').localeCompare(String(b.at || '')));
}

function PainelContato({ detail, atd, config, chatId, setToast, reload, assistantName, onBack }) {
  const stages = (config && config.pipeline && config.pipeline.stages) || DEFAULT_STAGES;
  const updateStage = async (stage) => {
    try { await post('/api/actions/stage', { chat_id: chatId, stage }); setToast('Etapa alterada'); reload(); }
    catch (err) { setToast(`Não alterei a etapa: ${err.message}`); }
  };
  const saveValue = async (event) => {
    event.preventDefault();
    const value = event.currentTarget.elements.value_brl.value;
    try { await post('/api/actions/value', { chat_id: chatId, value_brl: value }); setToast('Valor salvo'); reload(); }
    catch (err) { setToast(`Não salvei o valor: ${err.message}`); }
  };
  const lead = detail.lead || {};
  return html`<${Fragment}>
    <header class="atd-panel-head">
      <button class="lead-back-button atd-back" onClick=${onBack} aria-label="Voltar para a conversa"><${Icon.left}/></button>
      <b>Detalhes do contato</b>
    </header>
    <div class="atd-panel-body">
      ${atd ? html`<div class="detail-pair"><span>Protocolo</span><b class="atd-protocolo">${atd.protocolo}</b></div>` : html`<div class="detail-pair"><span>Protocolo</span><b>Sem atendimento aberto</b></div>`}
      ${atd ? html`<div class="atd-sla-grid">
        <${SlaClock} titulo="1ª resposta" sla=${atd.sla.primeira} alvo=${`${atd.sla.primeira.alvo_min} min`}/>
        <${SlaClock} titulo="Resolução" sla=${atd.sla.resolucao} alvo=${`${atd.sla.resolucao.alvo_h} h`}/>
      </div>` : null}
      <label class="atd-field"><span>Etapa</span>
        <${Select} value=${lead.stage} ariaLabel="Etapa" options=${stages.map((s) => ({ value: s.id, label: s.label }))} onChange=${updateStage}/>
      </label>
      <form class="atd-field" onSubmit=${saveValue}><span>Valor (R$)</span>
        <div class="atd-value-row"><input class="input" name="value_brl" inputmode="decimal" defaultValue=${lead.estimated_value_cents == null ? '' : (lead.estimated_value_cents / 100).toFixed(2).replace('.', ',')} placeholder="Ex.: 4.800,00"/><button type="submit" class="btn sm">Salvar</button></div>
      </form>
      <div class="detail-pair"><span>Próximo follow-up</span><b>${lead.next_followup_utc ? dateTime(lead.next_followup_utc) : 'Não agendado'}</b></div>
      <div class="detail-pair"><span>Reunião</span><b>${detail.meeting ? `${dateTime(detail.meeting.start)} · ${MEETING_OUTCOMES[detail.meeting.outcome || 'no_status']}` : 'Nenhuma'}</b></div>
      <div class="detail-pair"><span>Notas do contato</span><p class="atd-notas">${(detail.profile && detail.profile.notes) || 'Sem notas.'}</p></div>
      ${detail.profile && detail.profile.summary ? html`<div class="detail-pair"><span>Resumo de ${assistantName}</span><p class="atd-notas">${detail.profile.summary}</p></div>` : null}
    </div>
  </${Fragment}>`;
}

function Detalhe({ chatId, me, status, assistantName, config, setToast, go, users, onListChanged, painelAberto, setPainelAberto, setMobileView }) {
  const resource = useApi(`/api/lead/${encodeURIComponent(chatId)}`, { every: 5000, deps: [chatId] });
  const detail = resource.data;
  const isAdmin = isAdminUser(me);
  const [busy, setBusy] = useState(false);
  if (!chatId) return html`<div class="contacts-detail-empty"><${Empty}>Escolha um atendimento para abrir a conversa.</${Empty}></div>`;
  if (resource.error && !detail) return html`<div class="contacts-detail-empty"><${Empty}>${resource.error}</${Empty}></div>`;
  if (!detail) return html`<div class="contacts-detail-empty"><${Empty}>Carregando conversa…</${Empty}></div>`;

  const atd = detail.atendimento;
  const responsavel = atd ? { tipo: atd.responsavel_tipo, user: atd.responsavel_user } : null;
  const meu = !!atd && atd.responsavel_tipo === 'atendente' && atd.responsavel_user === me.username;
  const outroHumano = !!atd && (atd.responsavel_tipo === 'dono' || (atd.responsavel_tipo === 'atendente' && !meu));
  const lockedReason = outroHumano && !isAdmin ? `Este atendimento é ${atd.responsavel_tipo === 'dono' ? 'do Dono' : `de ${nomeDe(responsavel, assistantName, users)}`}.` : null;
  const aiOff = !!(detail.ai && !detail.ai.enabled);
  const blocked = !!(detail.lead && detail.lead.blocked);
  const devolverTitulo = blocked ? 'Contato bloqueado — a IA não pode voltar a atender.' : aiOff ? 'A IA está desligada para este contato.' : null;
  const silencio = detail.silence || {};
  const silenciadaAte = silencio.silenced && !silencio.hold && silencio.reason !== 'handoff'
    ? new Date(Date.now() + (silencio.time_left_s || 0) * 1000) : null;

  const run = async (path, body, okText) => {
    setBusy(true);
    try {
      const result = await post(path, { chat_id: chatId, ...body });
      setToast(result && result.warning ? result.warning : okText);
      resource.reload();
      onListChanged();
    } catch (err) {
      setToast(err.message);
    } finally {
      setBusy(false);
    }
  };
  const detailComEventos = { ...detail, timeline: timelineComEventos(detail) };
  const podeAssumir = atd && atd.status === 'aberto' && !meu && (!outroHumano || isAdmin);
  const podeDevolver = atd && atd.status === 'aberto' && (meu || isAdmin || atd.responsavel_tipo === 'nenhum');
  const podeResolver = atd && atd.status === 'aberto' && (!outroHumano || isAdmin);

  return html`<${Fragment}>
    <header class="contacts-detail-header atd-conv-head">
      <button class="lead-back-button atd-back" onClick=${() => { setMobileView('lista'); go('atendimento'); }} aria-label="Voltar para a fila"><${Icon.left}/></button>
      <span class="avatar mint">${fmt.initials(detail.name)}</span>
      <div class="grow">
        <b>${detail.name}</b>
        <span>${detail.phone}${atd ? html` · <span class="atd-protocolo">${atd.protocolo}</span>` : ''}</span>
      </div>
      <div class="atd-conv-tags">
        <${Responsavel} responsavel=${responsavel} assistantName=${assistantName} users=${users}/>
        ${silenciadaAte ? html`<span class="tag amber">${SILENCIO_LABEL[silencio.reason] || 'Silenciada'} · até ${hhmm(silenciadaAte.toISOString())}</span>` : null}
        ${atd && atd.handoff_utc ? html`<span class="tag orange">Handoff</span>` : null}
      </div>
      <button class="lead-header-action atd-panel-toggle" type="button" onClick=${() => { setPainelAberto(!painelAberto); setMobileView('painel'); }} aria-label=${painelAberto ? 'Recolher painel' : 'Abrir painel'} title=${painelAberto ? 'Recolher painel' : 'Abrir painel'}>${painelAberto ? html`<${Icon.right}/>` : html`<${Icon.left}/>`}</button>
    </header>
    ${atd && atd.status === 'aberto' ? html`<div class="atd-actions">
      ${podeAssumir ? html`<button class="btn primary sm" disabled=${busy} onClick=${() => run('/api/actions/atendimento/assumir', {}, 'Atendimento assumido')}>Assumir</button>` : null}
      ${podeDevolver ? html`<button class="btn sm" disabled=${busy || !!devolverTitulo} title=${devolverTitulo} onClick=${() => run('/api/actions/atendimento/devolver', {}, `Devolvido para ${assistantName}`)}>Devolver para a IA</button>` : null}
      ${podeResolver ? html`<button class="btn sm" disabled=${busy} onClick=${() => run('/api/actions/atendimento/resolver', {}, 'Atendimento resolvido')}>Resolver</button>` : null}
      ${isAdmin && users && users.length ? html`<${Select} value="" allowEmpty=${true} emptyLabel="Reatribuir para…" ariaLabel="Reatribuir" size="sm"
        options=${users.filter((u) => u.active && !(atd.responsavel_tipo === 'atendente' && atd.responsavel_user === u.username)).map((u) => ({ value: u.username, label: u.name }))}
        onChange=${(para) => para && window.confirm(`Reatribuir este atendimento para ${para}?`) && run('/api/actions/atendimento/reatribuir', { para }, `Reatribuído para ${para}`)}/>` : null}
    </div>` : atd ? null : html`<div class="atd-actions"><small class="atd-hint">Sem atendimento aberto. A próxima mensagem do contato abre um.</small></div>`}
    <section class="card conversation-card contacts-conversation-card">
      <${Conversation} chatId=${chatId} detail=${detailComEventos} assistantName=${assistantName}/>
      <${Composer} chatId=${chatId} detail=${detail} status=${status} me=${me} lockedReason=${lockedReason} onSent=${() => { resource.reload(); onListChanged(); }}/>
    </section>
    <aside class=${`atd-panel${painelAberto ? '' : ' collapsed'}`}>
      ${painelAberto ? html`<${PainelContato} detail=${detail} atd=${atd} config=${config} chatId=${chatId} setToast=${setToast} reload=${() => resource.reload()} assistantName=${assistantName} onBack=${() => setMobileView('conversa')}/>` : null}
    </aside>
  </${Fragment}>`;
}

export default function Atendimento({ assistantName = 'AYA', setToast, go, status, chatId = '', me, config }) {
  const verTodos = canSeeAll(me);
  const isAdmin = isAdminUser(me);
  const [fila, setFila] = useState('meus');
  const [query, setQuery] = useState('');
  const [painelAberto, setPainelAberto] = useState(true);
  const [mobileView, setMobileView] = useState(chatId ? 'conversa' : 'lista');
  // ponytail: a fila inteira a cada 5 s; o cursor desde_rev da API fica para quando a lista pesar.
  const lista = useApi(`/api/atendimentos?fila=${fila}`, { every: 5000, deps: [fila] });
  // Só admin lista usuários (reatribuir e nome do responsável).
  const [users, setUsers] = useState(null);
  useEffect(() => {
    if (!isAdmin) return;
    api('/api/users').then((body) => setUsers(body.users)).catch(() => setUsers(null));
  }, [isAdmin]);
  const data = lista.data;

  useEffect(() => { setMobileView(chatId ? 'conversa' : 'lista'); }, [chatId]);
  useEffect(() => { if (!verTodos && (fila === 'com_ia' || fila === 'todos')) setFila('meus'); }, [verTodos]);

  const needle = normalize(query.trim());
  const itens = (data ? data.itens : []).filter((item) => !needle
    || normalize([item.nome, item.telefone, item.preview].join(' ')).includes(needle));
  const contagens = (data && data.contagens) || {};

  return html`<div class="contacts-page contacts-split atd-page">
    <${ErrorBox} error=${lista.error}/>
    ${data && data.bot_paused ? html`<div class="banner warn atd-banner"><b>IA pausada.</b><span class="grow">Nada novo chega até alguém retomar em Configurações.</span></div>` : null}
    <section class="contacts-surface">
      <div class=${`atd-grid${chatId ? ' has-selection' : ''}${painelAberto ? '' : ' panel-collapsed'}`} data-mobile-view=${mobileView}>
        <div class="atd-lista">
          <header class="contacts-master-toolbar">
            <div class="contacts-scopes" role="group" aria-label="Filas">
              ${filas(assistantName, verTodos).map(([id, label]) => html`<button key=${id} type="button" class=${fila === id ? 'active' : ''} onClick=${() => setFila(id)}>${label}<b>${contagens[id] || 0}</b></button>`)}
            </div>
            <label class="contacts-search"><span>Buscar na fila</span><div><input type="search" value=${query} onInput=${(event) => setQuery(event.target.value)} placeholder="Nome, telefone ou mensagem" autocomplete="off"/></div></label>
          </header>
          <div class="contacts-list" role="list">
            ${itens.map((item) => html`<${FilaRow} key=${item.id} item=${item} active=${chatId === item.contato} assistantName=${assistantName} users=${users} onSelect=${(i) => go(`atendimento/${encodeURIComponent(i.contato)}`)}/>`)}
            ${data && !itens.length ? html`<${Empty}>${needle ? 'Nenhum atendimento corresponde à busca.' : 'Nada nesta fila agora.'}</${Empty}>` : null}
          </div>
        </div>
        <div class="atd-detalhe">
          <${Detalhe} chatId=${chatId} me=${me} status=${status} assistantName=${assistantName} config=${config} setToast=${setToast} go=${go} users=${users}
            onListChanged=${() => lista.reload()} painelAberto=${painelAberto} setPainelAberto=${setPainelAberto} setMobileView=${setMobileView}/>
        </div>
      </div>
    </section>
  </div>`;
}
