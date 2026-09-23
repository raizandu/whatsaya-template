// Aba Atendimento (#atendimento e #atendimento/<chat_id>): filas à esquerda,
// conversa com o composer compartilhado no meio, painel do contato à direita.
// A lista e a conversa aberta se atualizam sozinhas; quem move atendimento é a
// API (assumir, devolver, resolver, reatribuir) e a reconciliação do servidor.
import { useEffect, useState } from 'preact/hooks';
import { html, Fragment, api, useApi, post, ErrorBox, Empty, Icon, Select, Menu, isAdmin as isAdminUser, dateTime, normalize, DEFAULT_STAGES, MEETING_OUTCOMES, canSeeAllAtendimentos as canSeeAll, Avatar } from '../lib.js';
import { Conversation, Composer, MediaGallery } from './conversation.js';
import NovaConversaDialog from './nova-conversa.js';

// Duas entradas de menu levam à mesma tela: 'meus' (Minha caixa, rota
// #atendimento) e 'todos' (Todas as conversas, rota #atendimento-todas — só
// para quem vê tudo). O filtro de fila muda de opções conforme o escopo.
const BASE_ROUTE = { meus: 'atendimento', todos: 'atendimento-todas' };
const FILA_PADRAO = { meus: 'meus', todos: 'todos' };
const filaOpcoes = (assistantName, escopo) => escopo === 'todos'
  ? [['todos', 'Todos os responsáveis'], ['sem_responsavel', 'Sem responsável'], ['com_ia', `Com a ${assistantName}`]]
  : [['meus', 'Meus'], ['sem_responsavel', 'Sem responsável']];
const lida = (key, fallback) => { try { const v = localStorage.getItem(key); return v || fallback; } catch { return fallback; } };
const grava = (key, value) => { try { localStorage.setItem(key, value); } catch {} };

const EVENTO_LABEL = {
  aberto: 'Atendimento aberto', assumido: 'Assumido', devolvido: 'Devolvido para a IA',
  devolvido_auto: 'Devolvido para a IA automaticamente', resolvido: 'Resolvido', handoff: 'A IA pediu um humano',
  reatribuido: 'Reatribuído', responsavel_removido: 'Ficou sem responsável',
  ia_desativada: 'IA desativada; ficou sem responsável',
};

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

// Pílula de SLA: cinza quando perto do alvo, vermelha quando estourou.
function SlaClock({ titulo, sla, alvo }) {
  return html`<div class=${`atd-sla${sla.estourado ? ' estourado' : ''}`}>
    <span>${titulo}</span><b>${rel(sla.decorrido_s)}</b><small>alvo ${alvo}${sla.estourado ? ' · estourado' : ''}</small>
  </div>`;
}

function SlaBadge({ sla }) {
  if (!sla) return null;
  const primeira = sla.primeira || {};
  const resolucao = sla.resolucao || {};
  const estourado = primeira.estourado || resolucao.estourado;
  const perto = !estourado && primeira.decorrido_s >= (primeira.alvo_min || 0) * 60 * 0.7;
  if (!estourado && !perto) return null;
  return html`<span class=${`atd-sla-badge${estourado ? ' estourado' : ''}`}>SLA${estourado ? ' estourado' : ''}</span>`;
}

// Item da fila (Conversation row B): avatar, título/subtítulo, preview de uma
// linha, chips (canal + responsável) e badge de SLA. Sem "assunto"/"empresa" no
// dado hoje: título é o nome do contato, sem inventar campo que não existe.
function FilaRow({ item, active, onSelect, assistantName, users }) {
  const espera = item.aguardando_nos ? `aguardando há ${rel(item.espera_s)}` : null;
  return html`<button type="button" class=${`contacts-row atd-row${active ? ' active' : ''}${item.aguardando_nos ? ' urgent unread' : ''}`} onClick=${() => onSelect(item)} aria-current=${active ? 'true' : null}>
    <${Avatar} name=${item.nome} url=${item.avatar_url} className="contacts-avatar"/>
    <span class="contacts-row-main">
      <span class="contacts-row-top"><b>${item.nome}</b><time>${hhmm(item.ultima_msg_utc)}</time></span>
      <span class="atd-row-sub">${item.telefone}</span>
      <span class="atd-row-preview">${item.preview || 'Sem mensagem recente'}</span>
      <span class="atd-row-bottom">
        <span class="atd-chip-channel"><i class="fi fi-brands-whatsapp" aria-hidden="true"></i>WhatsApp</span>
        <${Responsavel} responsavel=${item.responsavel} assistantName=${assistantName} users=${users}/>
        ${espera ? html`<small class="atd-espera">${espera}</small>` : null}
        <${SlaBadge} sla=${item.sla}/>
      </span>
    </span>
  </button>`;
}

// Eventos do atendimento entram na timeline como eventos de sistema, ao lado
// do handoff e dos follow-ups que a conversa já mostra.
function timelineComEventos(detail) {
  const eventos = (detail.atendimento && detail.atendimento.eventos) || [];
  const extras = eventos.map((e) => ({
    type: 'event', event: 'atendimento', tipo: e.tipo, at: e.at_utc,
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
      <div class="atd-field"><span>Mídias</span><${MediaGallery} chatId=${chatId}/></div>
    </div>
  </${Fragment}>`;
}

function Detalhe({ chatId, me, status, assistantName, config, setToast, go, users, onListChanged, painelAberto, setPainelAberto, setMobileView, baseRoute }) {
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

  // "…" reúne as ações que já existiam na barra antiga (assumir, devolver,
  // reatribuir por usuário); resolver ganha botão próprio no cabeçalho.
  const menuItems = [];
  if (podeAssumir) menuItems.push({ label: 'Assumir', icon: 'user', onClick: () => run('/api/actions/atendimento/assumir', {}, 'Atendimento assumido') });
  if (podeDevolver) menuItems.push({ label: `Devolver para ${assistantName}`, icon: 'undo', disabled: !!devolverTitulo, onClick: () => run('/api/actions/atendimento/devolver', {}, `Devolvido para ${assistantName}`) });
  if (isAdmin && users && users.length) {
    const alvos = users.filter((u) => u.active && !(atd && atd.responsavel_tipo === 'atendente' && atd.responsavel_user === u.username));
    if (alvos.length) {
      menuItems.push({ heading: 'Reatribuir para' });
      alvos.forEach((u) => menuItems.push({
        label: u.name, icon: 'arrow-right',
        onClick: () => window.confirm(`Reatribuir este atendimento para ${u.name}?`) && run('/api/actions/atendimento/reatribuir', { para: u.username }, `Reatribuído para ${u.name}`),
      }));
    }
  }

  return html`<${Fragment}>
    <header class="contacts-detail-header atd-conv-head">
      <button class="lead-back-button atd-back" onClick=${() => { setMobileView('lista'); go(baseRoute); }} aria-label="Voltar para a fila"><${Icon.left}/></button>
      <${Avatar} name=${detail.name} url=${detail.avatar_url} className="avatar mint"/>
      <div class="grow">
        <b>${detail.name}</b>
        <span>${atd ? html`<span class="atd-protocolo">${atd.protocolo}</span> · ` : ''}WhatsApp${responsavel ? html` · ${nomeDe(responsavel, assistantName, users)}` : ''}</span>
      </div>
      <div class="atd-conv-tags">
        ${silenciadaAte ? html`<span class="tag amber">${SILENCIO_LABEL[silencio.reason] || 'Silenciada'} · até ${hhmm(silenciadaAte.toISOString())}</span>` : null}
        ${atd && atd.handoff_utc ? html`<span class="tag orange">Handoff</span>` : null}
        ${atd ? html`<${SlaBadge} sla=${atd.sla}/>` : null}
        ${podeResolver ? html`<button class="btn sm atd-resolve" disabled=${busy} onClick=${() => run('/api/actions/atendimento/resolver', {}, 'Atendimento resolvido')}>Resolver</button>` : null}
        ${menuItems.length ? html`<${Menu} label="Mais ações" items=${menuItems} size="sm"/>` : null}
      </div>
      <button class="lead-header-action atd-panel-toggle" type="button" onClick=${() => { setPainelAberto(!painelAberto); setMobileView('painel'); }} aria-label=${painelAberto ? 'Recolher painel' : 'Abrir painel'} title=${painelAberto ? 'Recolher painel' : 'Abrir painel'}>${painelAberto ? html`<${Icon.right}/>` : html`<${Icon.left}/>`}</button>
    </header>
    ${!atd ? html`<div class="atd-actions"><small class="atd-hint">Sem atendimento aberto. A próxima mensagem do contato abre um.</small></div>` : null}
    <section class="card conversation-card contacts-conversation-card">
      <${Conversation} chatId=${chatId} detail=${detailComEventos} assistantName=${assistantName}/>
      <${Composer} chatId=${chatId} detail=${detail} status=${status} me=${me} lockedReason=${lockedReason} config=${config} onSent=${() => { resource.reload(); onListChanged(); }}/>
    </section>
    <aside class=${`atd-panel${painelAberto ? '' : ' collapsed'}`}>
      ${painelAberto ? html`<${PainelContato} detail=${detail} atd=${atd} config=${config} chatId=${chatId} setToast=${setToast} reload=${() => resource.reload()} assistantName=${assistantName} onBack=${() => setMobileView('conversa')}/>` : null}
    </aside>
  </${Fragment}>`;
}

export default function Atendimento({ assistantName = 'AYA', setToast, go, status, chatId = '', me, config, escopo = 'meus' }) {
  const verTodos = canSeeAll(me);
  const isAdmin = isAdminUser(me);
  const escopoEfetivo = escopo === 'todos' && verTodos ? 'todos' : 'meus';
  const baseRoute = BASE_ROUTE[escopoEfetivo];
  const [fila, setFila] = useState(() => lida(`atd_fila_${escopoEfetivo}`, FILA_PADRAO[escopoEfetivo]));
  const [aba, setAba] = useState(() => lida('atd_aba', 'nao_lidos'));
  const [ordem, setOrdem] = useState(() => lida('atd_ordem', 'desc'));
  const [query, setQuery] = useState('');
  const [painelAberto, setPainelAberto] = useState(true);
  const [mobileView, setMobileView] = useState(chatId ? 'conversa' : 'lista');
  const [novaAberta, setNovaAberta] = useState(false);
  // Trocar de escopo (Minha caixa ↔ Todas) retoma a fila salva daquele escopo.
  useEffect(() => { setFila(lida(`atd_fila_${escopoEfetivo}`, FILA_PADRAO[escopoEfetivo])); }, [escopoEfetivo]);
  const escolherFila = (id) => { setFila(id); grava(`atd_fila_${escopoEfetivo}`, id); };
  const escolherAba = (id) => { setAba(id); grava('atd_aba', id); };
  const alternarOrdem = () => { const next = ordem === 'desc' ? 'asc' : 'desc'; setOrdem(next); grava('atd_ordem', next); };
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
  useEffect(() => { if (!verTodos && !filaOpcoes(assistantName, escopoEfetivo).some(([id]) => id === fila)) escolherFila(FILA_PADRAO[escopoEfetivo]); }, [verTodos, escopoEfetivo]);

  const needle = normalize(query.trim());
  const buscados = (data ? data.itens : []).filter((item) => !needle
    || normalize([item.nome, item.telefone, item.preview].join(' ')).includes(needle));
  const naoLidos = buscados.filter((item) => item.aguardando_nos);
  const itens = [...(aba === 'nao_lidos' ? naoLidos : buscados)]
    .sort((a, b) => (ordem === 'asc' ? 1 : -1) * String(a.ultima_msg_utc || '').localeCompare(String(b.ultima_msg_utc || '')));

  const opcoesFila = filaOpcoes(assistantName, escopoEfetivo);
  const filtroAtivo = fila !== FILA_PADRAO[escopoEfetivo];
  const menuFila = opcoesFila.map(([id, label]) => ({ label, icon: fila === id ? 'check' : undefined, onClick: () => escolherFila(id) }));

  return html`<div class="contacts-page contacts-split atd-page">
    <${ErrorBox} error=${lista.error}/>
    ${data && data.bot_paused ? html`<div class="banner warn atd-banner"><b>IA pausada.</b><span class="grow">Nada novo chega até alguém retomar em Configurações.</span></div>` : null}
    <section class="contacts-surface">
      <div class=${`atd-grid${chatId ? ' has-selection' : ''}${painelAberto ? '' : ' panel-collapsed'}`} data-mobile-view=${mobileView}>
        <div class="atd-lista">
          <header class="atd-toolbar">
            <div class="atd-toolbar-title">
              <b>${escopoEfetivo === 'todos' ? 'Todas as conversas' : 'Minha caixa de entrada'}</b>
              <div class="atd-toolbar-tools">
                <button type="button" class="btn primary sm atd-nova-btn" title="Nova conversa" aria-label="Nova conversa" onClick=${() => setNovaAberta(true)}>
                  <i class="fi fi-rr-edit" aria-hidden="true"></i>
                </button>
                <${Menu} label="Filtrar fila" icon="filter" items=${menuFila} align="end" className=${'atd-filter-menu' + (filtroAtivo ? ' has-filter' : '')}/>
                <button type="button" class="shell-icon-btn" onClick=${alternarOrdem} aria-label=${ordem === 'desc' ? 'Mais recentes primeiro' : 'Mais antigas primeiro'} title=${ordem === 'desc' ? 'Mais recentes primeiro' : 'Mais antigas primeiro'}>
                  <i class=${'fi fi-rr-sort-alt' + (ordem === 'asc' ? ' is-asc' : '')} aria-hidden="true"></i>
                </button>
              </div>
            </div>
            <div class="atd-tabs" role="tablist" aria-label="Filtrar por leitura">
              <button type="button" role="tab" aria-selected=${aba === 'nao_lidos'} class=${'atd-tab' + (aba === 'nao_lidos' ? ' active' : '')} onClick=${() => escolherAba('nao_lidos')}>
                <i class="fi fi-rr-envelope" aria-hidden="true"></i>Não lidos<b>${naoLidos.length}</b>
              </button>
              <button type="button" role="tab" aria-selected=${aba === 'todos'} class=${'atd-tab' + (aba === 'todos' ? ' active' : '')} onClick=${() => escolherAba('todos')}>
                <i class="fi fi-rr-inbox" aria-hidden="true"></i>Todos<b>${buscados.length}</b>
              </button>
            </div>
            <label class="contacts-search"><span>Buscar na fila</span><div><input type="search" value=${query} onInput=${(event) => setQuery(event.target.value)} placeholder="Nome, telefone ou mensagem" autocomplete="off"/></div></label>
          </header>
          <div class="contacts-list" role="list">
            ${itens.map((item) => html`<${FilaRow} key=${item.id} item=${item} active=${chatId === item.contato} assistantName=${assistantName} users=${users} onSelect=${(i) => go(`${baseRoute}/${encodeURIComponent(i.contato)}`)}/>`)}
            ${data && !itens.length ? html`<${Empty}>${needle ? 'Nenhum atendimento corresponde à busca.' : aba === 'nao_lidos' ? 'Nada aguardando resposta agora.' : 'Nada nesta fila agora.'}</${Empty}>` : null}
          </div>
        </div>
        <div class="atd-detalhe">
          <${Detalhe} chatId=${chatId} me=${me} status=${status} assistantName=${assistantName} config=${config} setToast=${setToast} go=${go} users=${users} baseRoute=${baseRoute}
            onListChanged=${() => lista.reload()} painelAberto=${painelAberto} setPainelAberto=${setPainelAberto} setMobileView=${setMobileView}/>
        </div>
      </div>
    </section>
    ${novaAberta ? html`<${NovaConversaDialog} assistantName=${assistantName} dailyLimit=${(config && config.atendimento && config.atendimento.novas_conversas_por_dia) || 20}
      setToast=${setToast} onClose=${() => setNovaAberta(false)}
      onCreated=${(novoChatId) => { setNovaAberta(false); lista.reload(); go(`${baseRoute}/${encodeURIComponent(novoChatId)}`); }}/>` : null}
  </div>`;
}
