// Atendimento.jsx — Atendimento (fila + conversa + painel), Contatos (tabela) e Usuários
// Mock do fase 0 do kit; nenhum dado vem de rede, tudo em memória.
// Reaproveita globais já carregados por Atoms.jsx, DataTable.jsx e WhatsAya.jsx
// (Button, Input, Select, Badge, DxDataGrid, FilterChip, DxAvatar, DxCheck, Modal,
// WhatsAyaPageHeader, WhatsAyaToggle, _surface) — os scripts do kit dividem o mesmo
// escopo global do Babel standalone.

const { useState: useAtdState, useEffect: useAtdEffect } = React;

const ATENDIMENTO_ATENDENTES = [
  { id: 'ana', nome: 'Ana Souza' },
  { id: 'bruno', nome: 'Bruno Reis' },
];
const CURRENT_ATENDENTE = ATENDIMENTO_ATENDENTES[0];

const ETAPA_OPTIONS = [
  { value: 'novo', label: 'Novo lead' },
  { value: 'qualificacao', label: 'Qualificação' },
  { value: 'agendamento', label: 'Agendamento' },
  { value: 'convertido', label: 'Convertido' },
  { value: 'perdido', label: 'Perdido' },
];
const REUNIAO_OPTIONS = [
  { value: 'nao_agendada', label: 'Não agendada' },
  { value: 'agendada', label: 'Agendada' },
  { value: 'realizada', label: 'Realizada' },
  { value: 'nao_compareceu', label: 'Não compareceu' },
];

const ATENDIMENTO_MOCK = [
  {
    id: 'marina', protocolo: '20260915-014',
    contato: { nome: 'Marina Costa', telefone: '(11) 9 8123-4401' },
    responsavel: { tipo: 'atendente', id: 'ana', nome: 'Ana Souza' },
    status: 'aberto', aguardandoNos: true, esperaMin: 6,
    ultimaMensagem: { texto: 'Posso remarcar para sexta?', hora: '10:42' },
    iaDesligada: false, bloqueado: false, silenciadoAte: null,
    sla: {
      primeira: { alvo: '15 min', decorrido: '1 min', estourado: false },
      resolucao: { alvo: '24 h', decorrido: '2h10', estourado: false },
    },
    etapa: 'qualificacao', valor: '450', proximoFollowup: '19/09 15:00', statusReuniao: 'agendada',
    notas: 'Prefere atendimento humano; sensível ao preço.',
    mensagens: [
      { tipo: 'sistema', texto: 'Atendimento aberto.', hora: '10:31' },
      { tipo: 'contato', texto: 'Oi, vi o conteúdo de vocês e queria entender melhor.', hora: '10:31' },
      { tipo: 'ia', texto: 'Oi, Marina. Posso te explicar e também entender o que você busca hoje.', hora: '10:32' },
      { tipo: 'contato', texto: 'Quero entender como funciona a sessão, mas prefiro falar com uma pessoa.', hora: '10:40' },
      { tipo: 'sistema', texto: 'Assumido por Ana Souza.', hora: '10:41' },
      { tipo: 'atendente', autor: 'Ana Souza', texto: 'Oi, Marina! Aqui é a Ana. Posso te explicar certinho como funciona.', hora: '10:41' },
      { tipo: 'contato', texto: 'Posso remarcar para sexta?', hora: '10:42' },
    ],
  },
  {
    id: 'paula', protocolo: '20260915-011',
    contato: { nome: 'Paula Mendes', telefone: '(21) 9 7402-1830' },
    responsavel: { tipo: 'nenhum' },
    status: 'aberto', aguardandoNos: true, esperaMin: 42,
    ultimaMensagem: { texto: 'Tem algum horário livre nesta semana?', hora: '09:18' },
    iaDesligada: false, bloqueado: false, silenciadoAte: null,
    sla: {
      primeira: { alvo: '15 min', decorrido: '42 min', estourado: true },
      resolucao: { alvo: '24 h', decorrido: '42 min', estourado: false },
    },
    etapa: 'agendamento', valor: '380', proximoFollowup: '—', statusReuniao: 'nao_agendada',
    notas: 'Perguntou por horários livres nesta semana.',
    mensagens: [
      { tipo: 'sistema', texto: 'Atendimento aberto.', hora: '09:12' },
      { tipo: 'contato', texto: 'Tem algum horário livre nesta semana?', hora: '09:18' },
    ],
  },
  {
    id: 'luciana', protocolo: '20260914-033',
    contato: { nome: 'Luciana Alves', telefone: '(31) 9 6501-9274' },
    responsavel: { tipo: 'ia' },
    status: 'aberto', aguardandoNos: false, esperaMin: 0,
    ultimaMensagem: { texto: 'Entendi o que você relatou. Posso te fazer duas perguntas rápidas?', hora: '18:08' },
    iaDesligada: false, bloqueado: false, silenciadoAte: null,
    sla: {
      primeira: { alvo: '15 min', decorrido: '2 min', estourado: false },
      resolucao: { alvo: '24 h', decorrido: '20 h', estourado: false },
    },
    etapa: 'novo', valor: '—', proximoFollowup: '—', statusReuniao: 'nao_agendada',
    notas: 'Enviou áudio relatando sintomas.',
    mensagens: [
      { tipo: 'sistema', texto: 'Atendimento aberto.', hora: '18:06' },
      { tipo: 'contato', texto: 'Áudio recebido · 0:38', hora: '18:06', audio: true },
      { tipo: 'sistema', texto: 'Áudio transcrito e anexado ao contexto da conversa.', hora: '18:07' },
      { tipo: 'ia', texto: 'Entendi o que você relatou. Posso te fazer duas perguntas rápidas?', hora: '18:08' },
    ],
  },
  {
    id: 'renata', protocolo: '20260908-002',
    contato: { nome: 'Renata Lima', telefone: '(41) 9 5330-1188' },
    responsavel: { tipo: 'ia' },
    status: 'aberto', aguardandoNos: true, esperaMin: 9,
    ultimaMensagem: { texto: 'Na verdade mudei de ideia, pode me ligar?', hora: '14:30' },
    iaDesligada: false, bloqueado: false, silenciadoAte: '14:32',
    sla: {
      primeira: { alvo: '15 min', decorrido: '1 min', estourado: false },
      resolucao: { alvo: '24 h', decorrido: '30 h', estourado: true },
    },
    etapa: 'convertido', valor: '450', proximoFollowup: 'Hoje, 15:00 (ligação)', statusReuniao: 'realizada',
    notas: 'Cliente ativa; mudou de ideia sobre o follow-up D+2.',
    mensagens: [
      { tipo: 'sistema', texto: 'Atendimento aberto.', hora: '16:20' },
      { tipo: 'contato', texto: 'Vou pensar e te chamo amanhã.', hora: '16:22' },
      { tipo: 'ia', texto: 'Combinado, Renata. Fico à disposição.', hora: '16:23' },
      { tipo: 'sistema', texto: 'Dono leu a conversa no WhatsApp — IA silenciada até 14:32.', hora: '14:22' },
      { tipo: 'contato', texto: 'Na verdade mudei de ideia, pode me ligar?', hora: '14:30' },
    ],
  },
  {
    id: 'camila', protocolo: '20260915-009',
    contato: { nome: 'Camila Rocha', telefone: '(11) 9 7010-3322' },
    responsavel: { tipo: 'atendente', id: 'bruno', nome: 'Bruno Reis' },
    status: 'aberto', aguardandoNos: false, esperaMin: 0,
    ultimaMensagem: { texto: 'Consigo sim, vou verificar os horários livres.', hora: '08:55' },
    iaDesligada: false, bloqueado: false, silenciadoAte: null,
    sla: {
      primeira: { alvo: '15 min', decorrido: '12 min', estourado: false },
      resolucao: { alvo: '24 h', decorrido: '1h', estourado: false },
    },
    etapa: 'agendamento', valor: '380', proximoFollowup: '17/09 10:00', statusReuniao: 'agendada',
    notas: 'Confirmar sala antes do horário.',
    mensagens: [
      { tipo: 'sistema', texto: 'Atendimento aberto.', hora: '08:40' },
      { tipo: 'contato', texto: 'Consigo remarcar para terça?', hora: '08:50' },
      { tipo: 'sistema', texto: 'Assumido por Bruno Reis.', hora: '08:52' },
      { tipo: 'atendente', autor: 'Bruno Reis', texto: 'Consigo sim, vou verificar os horários livres.', hora: '08:55' },
    ],
  },
  {
    id: 'fernanda', protocolo: '20260915-007',
    contato: { nome: 'Fernanda Souza', telefone: '(21) 9 8844-1120' },
    responsavel: { tipo: 'atendente', id: 'ana', nome: 'Ana Souza' },
    status: 'aberto', aguardandoNos: false, esperaMin: 0,
    ultimaMensagem: { texto: 'Vou verificar com o financeiro, um momento.', hora: '11:20' },
    iaDesligada: true, bloqueado: false, silenciadoAte: null,
    sla: {
      primeira: { alvo: '15 min', decorrido: '6 min', estourado: false },
      resolucao: { alvo: '24 h', decorrido: '5h', estourado: false },
    },
    etapa: 'novo', valor: '—', proximoFollowup: '—', statusReuniao: 'nao_agendada',
    notas: 'Reclamação de cobrança — IA desligada para este contato até resolver.',
    mensagens: [
      { tipo: 'sistema', texto: 'Atendimento aberto.', hora: '11:00' },
      { tipo: 'contato', texto: 'Recebi uma cobrança que não reconheço.', hora: '11:05' },
      { tipo: 'sistema', texto: 'Assumido por Ana Souza.', hora: '11:06' },
      { tipo: 'atendente', autor: 'Ana Souza', texto: 'Vou verificar com o financeiro, um momento.', hora: '11:20' },
    ],
  },
  {
    id: 'juliana', protocolo: '20260914-021',
    contato: { nome: 'Juliana Prado', telefone: '(31) 9 2210-7788' },
    responsavel: { tipo: 'atendente', id: 'ana', nome: 'Ana Souza' },
    status: 'aberto', aguardandoNos: false, esperaMin: 0,
    ultimaMensagem: { texto: 'Conteúdo identificado como spam.', hora: '20:03' },
    iaDesligada: false, bloqueado: true, silenciadoAte: null,
    sla: {
      primeira: { alvo: '15 min', decorrido: '5 min', estourado: false },
      resolucao: { alvo: '24 h', decorrido: '1h', estourado: false },
    },
    etapa: 'novo', valor: '—', proximoFollowup: '—', statusReuniao: 'nao_agendada',
    notas: 'Spam confirmado — contato bloqueado.',
    mensagens: [
      { tipo: 'sistema', texto: 'Atendimento aberto.', hora: '19:50' },
      { tipo: 'contato', texto: 'Promoção imperdível, clique aqui!', hora: '19:51' },
      { tipo: 'sistema', texto: 'Assumido por Ana Souza.', hora: '19:55' },
      { tipo: 'atendente', autor: 'Ana Souza', texto: 'Conteúdo identificado como spam.', hora: '20:03' },
    ],
  },
];

// Badge estático do menu: aguardando nós em Meus + Sem responsável (história 22).
const ATENDIMENTO_BADGE_COUNT = ATENDIMENTO_MOCK.filter((a) => a.status === 'aberto' && a.aguardandoNos
  && (a.responsavel.tipo === 'nenhum' || (a.responsavel.tipo === 'atendente' && a.responsavel.id === CURRENT_ATENDENTE.id))).length;

const FILAS = [
  { key: 'meus', label: 'Meus' },
  { key: 'sem_responsavel', label: 'Sem responsável' },
  { key: 'com_ia', label: 'Com a IA' },
  { key: 'todos', label: 'Todos' },
];

function filaDoAtendimento(a) {
  if (a.responsavel.tipo === 'atendente' && a.responsavel.id === CURRENT_ATENDENTE.id) return 'meus';
  if (a.responsavel.tipo === 'nenhum') return 'sem_responsavel';
  if (a.responsavel.tipo === 'ia') return 'com_ia';
  return 'outro'; // outro atendente ou Dono — só aparece em "Todos"
}

function horaAtual() {
  return new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

function ResponsavelTag({ responsavel }) {
  if (responsavel.tipo === 'nenhum') return <Badge variant="warning">Sem responsável</Badge>;
  if (responsavel.tipo === 'ia') return <Badge variant="neutral">IA</Badge>;
  if (responsavel.tipo === 'dono') return <Badge variant="neutral">Dono</Badge>;
  return <span style={{ fontSize: 12, fontWeight: 600 }}>{responsavel.nome}</span>;
}

function AtendimentoItem({ atd, ativo, onClick }) {
  const estourado = atd.sla.primeira.estourado || atd.sla.resolucao.estourado;
  return (
    <button onClick={onClick} style={{
      width: '100%', border: 0, textAlign: 'left', cursor: 'pointer', display: 'flex', gap: 10,
      padding: '12px 14px', borderBottom: '1px solid var(--border-solid)',
      borderLeft: atd.aguardandoNos ? '3px solid var(--primary)' : '3px solid transparent',
      background: ativo ? 'var(--primary-10)' : 'var(--card)',
    }}>
      <DxAvatar name={atd.contato.nome} tone="purple" />
      <span style={{ flex: 1, minWidth: 0 }}>
        <span style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
          <strong style={{ fontSize: 12 }}>{atd.contato.nome}</strong>
          <small style={{ color: 'var(--muted-foreground)' }}>{atd.ultimaMensagem.hora}</small>
        </span>
        <span style={{ display: 'block', marginTop: 4, fontSize: 11, color: 'var(--foreground-75)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {atd.ultimaMensagem.texto}
        </span>
        <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 7, gap: 6 }}>
          <span style={{ fontSize: 11, color: 'var(--muted-foreground)' }}>Responsável: <ResponsavelTag responsavel={atd.responsavel} /></span>
          {estourado && <Badge variant="danger" icon="alarm-exclamation" dot={false}>SLA</Badge>}
        </span>
      </span>
    </button>
  );
}

function SlaClock({ titulo, sla }) {
  return (
    <div style={{
      ..._surface, padding: 12, display: 'flex', flexDirection: 'column', gap: 4,
      boxShadow: sla.estourado ? '0 0 0 1px var(--primary-deep), var(--shadow-hairline)' : _surface.boxShadow,
    }}>
      <span style={{ fontSize: 11, color: 'var(--foreground-75)', fontWeight: 600 }}>{titulo}</span>
      <span style={{ font: '700 18px/1.1 var(--font-numeric)' }}>{sla.decorrido}</span>
      <span style={{ fontSize: 10, color: 'var(--muted-foreground)' }}>Alvo: {sla.alvo}</span>
      {sla.estourado && <Badge variant="danger" icon="alarm-exclamation" dot={false}>Estourado</Badge>}
    </div>
  );
}

function WhatsAyaAtendimento({ botPaused, selecionadoId, onSelecionar }) {
  const [atendimentos, setAtendimentos] = useAtdState(ATENDIMENTO_MOCK);
  const [verTodos, setVerTodos] = useAtdState(true);
  const [fila, setFila] = useAtdState('meus');
  const [busca, setBusca] = useAtdState('');
  const [selecaoInterna, setSelecaoInterna] = useAtdState(ATENDIMENTO_MOCK[0].id);
  const [painelAberto, setPainelAberto] = useAtdState(true);
  const [mobileView, setMobileView] = useAtdState('lista');
  const [composerValor, setComposerValor] = useAtdState('');

  useAtdEffect(() => {
    if (selecionadoId) {
      if (atendimentos.some((a) => a.id === selecionadoId)) {
        setSelecaoInterna(selecionadoId);
        setMobileView('conversa');
      }
      onSelecionar && onSelecionar(null);
    }
  }, [selecionadoId]);

  const atualizar = (id, mudanca) => setAtendimentos((prev) => prev.map((a) => (a.id !== id ? a : {
    ...a, ...(typeof mudanca === 'function' ? mudanca(a) : mudanca),
  })));
  const evento = (a, texto) => ({ mensagens: [...a.mensagens, { tipo: 'sistema', texto, hora: horaAtual() }] });

  const assumir = (id) => atualizar(id, (a) => ({
    responsavel: { tipo: 'atendente', id: CURRENT_ATENDENTE.id, nome: CURRENT_ATENDENTE.nome },
    ...evento(a, `Assumido por ${CURRENT_ATENDENTE.nome}.`),
  }));
  const devolverParaIa = (id) => atualizar(id, (a) => ({
    responsavel: { tipo: 'ia' },
    ...evento(a, 'Devolvido para a IA.'),
  }));
  const resolver = (id) => atualizar(id, (a) => ({
    status: 'resolvido',
    ...evento(a, `Resolvido por ${CURRENT_ATENDENTE.nome}.`),
  }));
  const reatribuir = (id, atendenteId) => {
    const alvo = ATENDIMENTO_ATENDENTES.find((u) => u.id === atendenteId);
    if (!alvo) return;
    atualizar(id, (a) => ({
      responsavel: { tipo: 'atendente', id: alvo.id, nome: alvo.nome },
      ...evento(a, `Reatribuído para ${alvo.nome}.`),
    }));
  };
  const enviarMensagem = (id, texto) => atualizar(id, (a) => {
    const jaSouEu = a.responsavel.tipo === 'atendente' && a.responsavel.id === CURRENT_ATENDENTE.id;
    const base = jaSouEu ? a : { ...a, responsavel: { tipo: 'atendente', id: CURRENT_ATENDENTE.id, nome: CURRENT_ATENDENTE.nome }, ...evento(a, `Assumido por ${CURRENT_ATENDENTE.nome}.`) };
    return {
      responsavel: base.responsavel,
      aguardandoNos: false,
      mensagens: [...base.mensagens, { tipo: 'atendente', autor: CURRENT_ATENDENTE.nome, texto, hora: horaAtual() }],
    };
  });

  const filasVisiveis = verTodos ? FILAS : FILAS.filter((f) => f.key === 'meus' || f.key === 'sem_responsavel');
  const filaEfetiva = filasVisiveis.some((f) => f.key === fila) ? fila : 'meus';
  const contarFila = (key) => atendimentos.filter((a) => a.status === 'aberto' && (key === 'todos' ? true : filaDoAtendimento(a) === key)).length;

  const needle = busca.trim().toLowerCase();
  const listaFiltrada = atendimentos
    .filter((a) => a.status === 'aberto')
    .filter((a) => (filaEfetiva === 'todos' ? true : filaDoAtendimento(a) === filaEfetiva))
    .filter((a) => !needle || `${a.contato.nome} ${a.contato.telefone}`.toLowerCase().includes(needle))
    .sort((a, b) => (a.aguardandoNos === b.aguardandoNos ? b.esperaMin - a.esperaMin : (a.aguardandoNos ? -1 : 1)));

  const selected = atendimentos.find((a) => a.id === selecaoInterna) || atendimentos[0];
  const mostrarAssumir = selected.status === 'aberto' && (selected.responsavel.tipo === 'nenhum' || selected.responsavel.tipo === 'ia');
  const mostrarDevolver = selected.status === 'aberto' && (selected.responsavel.tipo === 'atendente' || selected.responsavel.tipo === 'dono');
  const devolverDesabilitado = selected.bloqueado || selected.iaDesligada;
  const devolverTitulo = selected.bloqueado ? 'Contato bloqueado — a IA não pode voltar a atender.'
    : selected.iaDesligada ? 'IA desligada para este contato.' : undefined;
  const outroHumano = selected.responsavel.tipo === 'dono'
    || (selected.responsavel.tipo === 'atendente' && selected.responsavel.id !== CURRENT_ATENDENTE.id);

  return (
    <div>
      <WhatsAyaPageHeader eyebrow="Atendimento" title="Atendimento"
        subtitle="Fila, conversa e contexto do lead em um único lugar."
        actions={[
          <span key="perm" style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--foreground-75)' }}>
            Ver todos os atendimentos
            <WhatsAyaToggle checked={verTodos} onChange={() => setVerTodos(!verTodos)} label="Alternar permissão de ver todos os atendimentos" />
          </span>,
        ]} />

      {botPaused && (
        <div style={{ ..._surface, padding: '10px 14px', marginBottom: 12, background: 'var(--warning-fade)',
          display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, fontWeight: 600 }}>
          <i className="fi fi-rr-pause" /> IA pausada globalmente — nenhum contato recebe resposta automática até retomar.
        </div>
      )}

      <div className="wa-atd-layout" data-mobile-view={mobileView} style={{
        ..._surface, display: 'grid',
        gridTemplateColumns: `300px minmax(0, 1fr) ${painelAberto ? '300px' : '56px'}`,
        minHeight: 620, overflow: 'hidden',
      }}>
        <aside className="wa-atd-col-lista" style={{ borderRight: '1px solid var(--border-solid)', display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <div style={{ padding: '14px 14px 10px', display: 'flex', flexDirection: 'column', gap: 10, borderBottom: '1px solid var(--border-solid)' }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {filasVisiveis.map((f) => (
                <FilterChip key={f.key} label={f.label} count={contarFila(f.key)} active={filaEfetiva === f.key} onClick={() => setFila(f.key)} />
              ))}
            </div>
            <Input icon="search" full value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="Buscar por nome ou telefone" />
          </div>
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {listaFiltrada.map((a) => (
              <AtendimentoItem key={a.id} atd={a} ativo={a.id === selected.id}
                onClick={() => { setSelecaoInterna(a.id); setMobileView('conversa'); }} />
            ))}
            {listaFiltrada.length === 0 && (
              <div style={{ padding: 28, textAlign: 'center', color: 'var(--muted-foreground)', fontSize: 12 }}>Nenhum atendimento nesta fila.</div>
            )}
          </div>
        </aside>

        <section className="wa-atd-col-conversa" style={{ minWidth: 0, display: 'flex', flexDirection: 'column', background: 'var(--muted-solid)' }}>
          <header style={{ padding: '12px 16px', background: 'var(--card)', borderBottom: '1px solid var(--border-solid)',
            display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <button className="wa-atd-back" onClick={() => setMobileView('lista')} style={{
                  border: 0, background: 'transparent', cursor: 'pointer', color: 'var(--foreground-75)', display: 'none',
                }}><i className="fi fi-rr-arrow-left" /></button>
                <div>
                  <strong style={{ display: 'block', fontSize: 13 }}>{selected.contato.nome}</strong>
                  <span style={{ fontSize: 10, color: 'var(--muted-foreground)' }}>
                    {selected.contato.telefone} · Protocolo {selected.protocolo}
                  </span>
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <ResponsavelTag responsavel={selected.responsavel} />
                {selected.status === 'resolvido' && <Badge variant="success" icon="check">Resolvido</Badge>}
                {selected.responsavel.tipo === 'ia' && selected.silenciadoAte && (
                  <Badge variant="neutral" icon="volume-mute">{`Silenciada até ${selected.silenciadoAte}`}</Badge>
                )}
                <span className="wa-atd-abrir-painel">
                  <Button variant="ghost" size="sm" icon="info"
                    onClick={() => { setPainelAberto(true); setMobileView('painel'); }} title="Detalhes do contato" />
                </span>
              </div>
            </div>
            {selected.status === 'aberto' && (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {mostrarAssumir && <Button variant="primary" size="sm" icon="user-add" onClick={() => assumir(selected.id)}>Assumir</Button>}
                {mostrarDevolver && (
                  <Button variant="outline" size="sm" icon="rotate-left" disabled={devolverDesabilitado} title={devolverTitulo}
                    onClick={() => devolverParaIa(selected.id)}>Devolver para a IA</Button>
                )}
                <Button variant="outline" size="sm" icon="check" onClick={() => resolver(selected.id)}>Resolver</Button>
                {verTodos && (
                  <Select value="" onChange={(e) => e.target.value && reatribuir(selected.id, e.target.value)} options={[
                    { value: '', label: 'Reatribuir para…' },
                    ...ATENDIMENTO_ATENDENTES.filter((u) => u.id !== selected.responsavel.id).map((u) => ({ value: u.id, label: u.nome })),
                  ]} />
                )}
              </div>
            )}
          </header>

          <div style={{ flex: 1, padding: 20, display: 'flex', flexDirection: 'column', gap: 8, overflowY: 'auto' }}>
            {selected.mensagens.map((m, i) => {
              if (m.tipo === 'sistema') {
                return (
                  <div key={i} style={{ alignSelf: 'center', maxWidth: 460, textAlign: 'center', padding: '6px 11px',
                    borderRadius: 6, background: 'var(--muted-solid)', color: 'var(--foreground-75)', fontSize: 10 }}>{m.texto}</div>
                );
              }
              const saindo = m.tipo !== 'contato';
              const bg = m.tipo === 'ia' ? 'var(--success-fade)' : 'var(--card)';
              const border = m.tipo === 'ia' ? 'var(--success)' : 'var(--border-solid)';
              return (
                <div key={i} style={{ alignSelf: saindo ? 'flex-end' : 'flex-start', maxWidth: '72%', padding: '10px 12px',
                  background: bg, border: `1px solid ${border}`,
                  borderRadius: saindo ? '8px 2px 8px 8px' : '2px 8px 8px 8px', fontSize: 12, lineHeight: 1.5 }}>
                  {(m.tipo === 'atendente' || m.tipo === 'dono') && (
                    <small style={{ display: 'block', fontWeight: 700, marginBottom: 3 }}>{m.tipo === 'dono' ? 'Dono' : m.autor}</small>
                  )}
                  {m.audio && <i className="fi fi-rr-waveform-path" style={{ marginRight: 7, color: 'var(--primary)' }} />}
                  {m.texto}
                  <small style={{ display: 'block', marginTop: 5, textAlign: 'right', color: 'var(--muted-foreground)', fontSize: 9 }}>{m.hora}</small>
                </div>
              );
            })}
          </div>

          <footer style={{ padding: 14, background: 'var(--card)', borderTop: '1px solid var(--border-solid)' }}>
            {outroHumano ? (
              <div style={{ padding: '11px 12px', borderRadius: 6, background: 'var(--muted-solid)', color: 'var(--foreground-75)',
                fontSize: 11, display: 'flex', alignItems: 'center', gap: 8 }}>
                <i className="fi fi-rr-lock" />
                {`Este atendimento é ${selected.responsavel.tipo === 'dono' ? 'do Dono' : `de ${selected.responsavel.nome}`}.`}
              </div>
            ) : selected.status === 'resolvido' ? (
              <div style={{ padding: '11px 12px', borderRadius: 6, background: 'var(--muted-solid)', color: 'var(--foreground-75)', fontSize: 11 }}>
                Atendimento resolvido. Uma nova mensagem do contato abre outro atendimento.
              </div>
            ) : (
              <form onSubmit={(e) => { e.preventDefault(); if (!composerValor.trim()) return; enviarMensagem(selected.id, composerValor.trim()); setComposerValor(''); }}
                style={{ display: 'flex', gap: 8 }}>
                <textarea value={composerValor} onChange={(e) => setComposerValor(e.target.value)} placeholder="Escreva uma mensagem…" rows={1}
                  style={{ flex: 1, resize: 'none', border: '1px solid var(--hairline-strong)', borderRadius: 6, padding: '8px 10px',
                    font: '400 13px/1.4 Open Sans, sans-serif', color: 'var(--foreground)', background: 'var(--input-bg)' }} />
                <Button type="submit" variant="primary" icon="paper-plane" disabled={!composerValor.trim()}>Enviar</Button>
              </form>
            )}
          </footer>
        </section>

        <aside className="wa-atd-col-painel" style={{ borderLeft: '1px solid var(--border-solid)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div style={{ padding: painelAberto ? 14 : '14px 8px', display: 'flex', alignItems: 'center', justifyContent: painelAberto ? 'space-between' : 'center' }}>
            <button className="wa-atd-back" onClick={() => setMobileView('conversa')} style={{
              border: 0, background: 'transparent', cursor: 'pointer', color: 'var(--foreground-75)', display: 'none',
            }}><i className="fi fi-rr-arrow-left" /></button>
            {painelAberto && <strong style={{ fontSize: 13 }}>Detalhes do contato</strong>}
            <Button variant="ghost" size="sm" icon={painelAberto ? 'angle-small-right' : 'angle-small-left'}
              onClick={() => setPainelAberto(!painelAberto)} title={painelAberto ? 'Recolher painel' : 'Expandir painel'} />
          </div>
          {painelAberto && (
            <div style={{ padding: '0 14px 14px', display: 'flex', flexDirection: 'column', gap: 14, overflowY: 'auto' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                <SlaClock titulo="1ª resposta" sla={selected.sla.primeira} />
                <SlaClock titulo="Resolução" sla={selected.sla.resolucao} />
              </div>
              <Select full label="Etapa" value={selected.etapa} onChange={(e) => atualizar(selected.id, { etapa: e.target.value })} options={ETAPA_OPTIONS} />
              <Input full label="Valor (R$)" value={selected.valor} onChange={(e) => atualizar(selected.id, { valor: e.target.value })} />
              <Input full label="Próximo follow-up" value={selected.proximoFollowup} onChange={(e) => atualizar(selected.id, { proximoFollowup: e.target.value })} />
              <Select full label="Status da reunião" value={selected.statusReuniao} onChange={(e) => atualizar(selected.id, { statusReuniao: e.target.value })} options={REUNIAO_OPTIONS} />
              <label className="aya-field" data-full="">
                <span className="aya-label">Notas</span>
                <textarea value={selected.notas} onChange={(e) => atualizar(selected.id, { notas: e.target.value })} rows={4}
                  style={{ border: '1px solid var(--hairline-strong)', borderRadius: 6, padding: '8px 10px', resize: 'vertical',
                    font: '400 13px/1.5 Open Sans, sans-serif', color: 'var(--foreground)', background: 'var(--input-bg)' }} />
              </label>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Contatos — tabela do kit (DxDataGrid), escopos lendo o atendimento aberto.
// ---------------------------------------------------------------------------

const CONTATOS_MOCK = [
  { id: 'marina', nome: 'Marina Costa', telefone: '(11) 9 8123-4401', categoria: 'Lead', etapa: 'Qualificação', responsavel: { tipo: 'atendente', nome: 'Ana Souza' }, ultima: 'Hoje, 10:42', iaLigada: true, bloqueado: false },
  { id: 'paula', nome: 'Paula Mendes', telefone: '(21) 9 7402-1830', categoria: 'Lead', etapa: 'Novo lead', responsavel: null, ultima: 'Hoje, 09:18', iaLigada: true, bloqueado: false },
  { id: 'luciana', nome: 'Luciana Alves', telefone: '(31) 9 6501-9274', categoria: 'Lead', etapa: 'Novo lead', responsavel: { tipo: 'ia' }, ultima: 'Ontem, 18:08', iaLigada: true, bloqueado: false },
  { id: 'renata', nome: 'Renata Lima', telefone: '(41) 9 5330-1188', categoria: 'Cliente', etapa: 'Cliente', responsavel: { tipo: 'ia' }, ultima: 'Hoje, 14:31', iaLigada: true, bloqueado: false },
  { id: 'camila', nome: 'Camila Rocha', telefone: '(11) 9 7010-3322', categoria: 'Lead', etapa: 'Agendamento', responsavel: { tipo: 'atendente', nome: 'Bruno Reis' }, ultima: 'Hoje, 08:55', iaLigada: true, bloqueado: false },
  { id: 'fernanda', nome: 'Fernanda Souza', telefone: '(21) 9 8844-1120', categoria: 'Revisar', etapa: 'Incerto', responsavel: { tipo: 'atendente', nome: 'Ana Souza' }, ultima: 'Hoje, 11:20', iaLigada: false, bloqueado: false },
  { id: 'juliana', nome: 'Juliana Prado', telefone: '(31) 9 2210-7788', categoria: 'Spam/irrelevante', etapa: 'Spam', responsavel: { tipo: 'atendente', nome: 'Ana Souza' }, ultima: 'Ontem, 20:03', iaLigada: true, bloqueado: true },
  { id: 'vanessa', nome: 'Vanessa Melo', telefone: '(51) 9 3345-2210', categoria: 'Cliente', etapa: 'Cliente', responsavel: { tipo: 'dono' }, ultima: 'Seg, 16:40', iaLigada: true, bloqueado: false },
  { id: 'bianca', nome: 'Bianca Freitas', telefone: '(41) 9 9812-0044', categoria: 'Pessoal', etapa: 'Pessoal', responsavel: null, ultima: 'Sex, 12:00', iaLigada: false, bloqueado: false },
];

const CONTATOS_ESCOPOS = [
  { key: 'todos', label: 'Todos' },
  { key: 'atencao', label: 'Pedem atenção' },
  { key: 'com_ia', label: 'Com a IA' },
  { key: 'sem_responsavel', label: 'Sem responsável' },
  { key: 'ia_desligada', label: 'IA desligada' },
  { key: 'bloqueados', label: 'Bloqueados' },
];

function contatoEmEscopo(c, escopo) {
  if (escopo === 'atencao') return c.bloqueado || !c.iaLigada || !c.responsavel;
  if (escopo === 'com_ia') return c.responsavel && c.responsavel.tipo === 'ia';
  if (escopo === 'sem_responsavel') return !c.responsavel;
  if (escopo === 'ia_desligada') return !c.iaLigada;
  if (escopo === 'bloqueados') return c.bloqueado;
  return true;
}

function responsavelContatoLabel(responsavel) {
  if (!responsavel) return '—';
  if (responsavel.tipo === 'ia') return 'IA';
  if (responsavel.tipo === 'dono') return 'Dono';
  return responsavel.nome;
}

function WhatsAyaContatos({ onAbrirAtendimento }) {
  const [busca, setBusca] = useAtdState('');
  const [escopo, setEscopo] = useAtdState('todos');
  const [sortKey, setSortKey] = useAtdState('nome');
  const [sortDir, setSortDir] = useAtdState('asc');
  const [page, setPage] = useAtdState(1);
  const [size, setSize] = useAtdState(10);

  const needle = busca.trim().toLowerCase();
  const filtrados = CONTATOS_MOCK
    .filter((c) => contatoEmEscopo(c, escopo))
    .filter((c) => !needle || `${c.nome} ${c.telefone}`.toLowerCase().includes(needle))
    .sort((a, b) => {
      const va = sortKey === 'responsavel' ? responsavelContatoLabel(a.responsavel) : a[sortKey];
      const vb = sortKey === 'responsavel' ? responsavelContatoLabel(b.responsavel) : b[sortKey];
      const cmp = String(va).localeCompare(String(vb), 'pt-BR');
      return sortDir === 'asc' ? cmp : -cmp;
    });
  const paginados = filtrados.slice((page - 1) * size, page * size);

  const abrir = (id) => onAbrirAtendimento && onAbrirAtendimento(id);
  const clicavel = (c, node) => <span onClick={() => abrir(c.id)} style={{ cursor: 'pointer', display: 'block' }}>{node}</span>;

  const columns = [
    { key: 'nome', label: 'Contato', sortable: true, render: (c) => clicavel(c, (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
        <DxAvatar name={c.nome} tone="purple" /><strong>{c.nome}</strong>
      </span>
    )) },
    { key: 'telefone', label: 'Telefone', sortable: true, render: (c) => clicavel(c, <span style={{ fontFamily: 'Geist, ui-sans-serif' }}>{c.telefone}</span>) },
    { key: 'categoria', label: 'Categoria', sortable: true, render: (c) => clicavel(c, <Badge variant="neutral">{c.categoria}</Badge>) },
    { key: 'etapa', label: 'Etapa', sortable: true, render: (c) => clicavel(c, c.etapa) },
    { key: 'responsavel', label: 'Responsável', sortable: true, render: (c) => clicavel(c, responsavelContatoLabel(c.responsavel)) },
    { key: 'ultima', label: 'Última mensagem', sortable: true, render: (c) => clicavel(c, <span style={{ color: 'var(--muted-foreground)' }}>{c.ultima}</span>) },
    { key: 'iaLigada', label: 'IA', render: (c) => clicavel(c, <Badge variant={c.iaLigada ? 'success' : 'neutral'}>{c.iaLigada ? 'Ligada' : 'Desligada'}</Badge>) },
    { key: 'bloqueado', label: 'Bloqueio', render: (c) => clicavel(c, c.bloqueado ? <Badge variant="danger" icon="ban">Bloqueado</Badge> : <span style={{ color: 'var(--muted-foreground)' }}>—</span>) },
  ];

  return (
    <div>
      <WhatsAyaPageHeader eyebrow="Base comercial" title="Contatos" subtitle="Procure pessoas; a linha abre o atendimento dela." />
      <DxDataGrid
        columns={columns} rows={paginados} selectable={false}
        filters={CONTATOS_ESCOPOS.map((e) => ({ key: e.key, label: e.label, count: CONTATOS_MOCK.filter((c) => contatoEmEscopo(c, e.key)).length }))}
        activeFilter={escopo} onFilterClick={setEscopo}
        search={busca} searchPlaceholder="Buscar por nome ou telefone" onSearchChange={(e) => { setBusca(e.target.value); setPage(1); }}
        sortKey={sortKey} sortDir={sortDir}
        onSort={(k) => { if (k === sortKey) setSortDir(sortDir === 'asc' ? 'desc' : 'asc'); else { setSortKey(k); setSortDir('asc'); } }}
        page={page} size={size} total={filtrados.length}
        onPage={setPage} onSize={(s) => { setSize(s); setPage(1); }}
        selectedCountLabel={`${filtrados.length} de ${CONTATOS_MOCK.length} contatos`}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Usuários — lista + Modal de criar/editar com permissão "ver todos".
// ---------------------------------------------------------------------------

const USUARIOS_MOCK = [
  { id: 'ana', nome: 'Ana Souza', login: 'ana', papel: 'admin', ativo: true, verTodos: true },
  { id: 'bruno', nome: 'Bruno Reis', login: 'bruno', papel: 'atendente', ativo: true, verTodos: false },
  { id: 'carla', nome: 'Carla Dias', login: 'carla', papel: 'atendente', ativo: false, verTodos: false },
];

function UsuarioForm({ usuario, onSave, onClose }) {
  const [nome, setNome] = useAtdState(usuario ? usuario.nome : '');
  const [login, setLogin] = useAtdState(usuario ? usuario.login : '');
  const [senha, setSenha] = useAtdState('');
  const [papel, setPapel] = useAtdState(usuario ? usuario.papel : 'atendente');
  const [ativo, setAtivo] = useAtdState(usuario ? usuario.ativo : true);
  const [verTodos, setVerTodos] = useAtdState(usuario ? usuario.verTodos : false);
  const isAdmin = papel === 'admin';
  const podeSalvar = nome.trim() && login.trim() && (usuario || senha.trim());

  return (
    <Modal open title={usuario ? 'Editar usuário' : 'Novo usuário'}
      subtitle={usuario ? `Alterando o acesso de ${usuario.nome}.` : 'Defina o login e o papel no painel.'}
      onClose={onClose}
      actions={[
        <Button key="cn" variant="ghost" onClick={onClose}>Cancelar</Button>,
        <Button key="ok" variant="primary" disabled={!podeSalvar}
          onClick={() => onSave({ nome, login, papel, ativo, verTodos: isAdmin || verTodos })}>
          {usuario ? 'Salvar' : 'Criar usuário'}
        </Button>,
      ]}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Input full label="Nome" value={nome} onChange={(e) => setNome(e.target.value)} />
        <Input full label="Login" value={login} onChange={(e) => setLogin(e.target.value)} />
        {!usuario && <Input full type="password" label="Senha" value={senha} onChange={(e) => setSenha(e.target.value)} hint="Só é definida na criação." />}
        <Select full label="Papel" value={papel} onChange={(e) => setPapel(e.target.value)}
          options={[{ value: 'atendente', label: 'Atendente' }, { value: 'admin', label: 'Admin' }]} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, opacity: isAdmin ? 0.6 : 1 }}>
          <DxCheck checked={isAdmin || verTodos} onChange={() => !isAdmin && setVerTodos(!verTodos)} />
          <span style={{ fontSize: 13 }}>Ver todos os atendimentos{isAdmin ? ' (incluso no papel Admin)' : ''}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>Usuário ativo</span>
          <WhatsAyaToggle checked={ativo} onChange={() => setAtivo(!ativo)} label="Alternar usuário ativo" />
        </div>
      </div>
    </Modal>
  );
}

function WhatsAyaUsuarios() {
  const [usuarios, setUsuarios] = useAtdState(USUARIOS_MOCK);
  const [modal, setModal] = useAtdState(null); // null | 'novo' | usuário em edição

  const editando = modal && modal !== 'novo' ? modal : null;
  const salvar = (dados) => {
    if (editando) setUsuarios((prev) => prev.map((u) => (u.id === editando.id ? { ...u, ...dados } : u)));
    else setUsuarios((prev) => [...prev, { id: dados.login, ...dados }]);
    setModal(null);
  };

  return (
    <div>
      <WhatsAyaPageHeader eyebrow="Painel" title="Usuários" subtitle="Quem responde pelo painel e o que cada um pode ver."
        actions={<Button icon="user-add" onClick={() => setModal('novo')}>Novo usuário</Button>} />
      <section style={{ ..._surface, padding: 0, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr style={{ background: 'var(--muted-solid)' }}>
            {['Nome', 'Login', 'Papel', 'Ver todos os atendimentos', 'Ativo', ''].map((l) => (
              <th key={l} style={{ padding: '10px 16px', textAlign: 'left', fontSize: 11, fontWeight: 700, color: 'var(--foreground-75)', borderBottom: '1px solid var(--border-solid)' }}>{l}</th>
            ))}
          </tr></thead>
          <tbody>
            {usuarios.map((u) => (
              <tr key={u.id} style={{ borderTop: '1px solid var(--border-solid-50)' }}>
                <td style={{ padding: '10px 16px', fontSize: 13, fontWeight: 600 }}>{u.nome}</td>
                <td style={{ padding: '10px 16px', fontSize: 13, color: 'var(--muted-foreground)' }}>{u.login}</td>
                <td style={{ padding: '10px 16px' }}><Badge variant="neutral" icon={u.papel === 'admin' ? 'shield-check' : undefined}>{u.papel === 'admin' ? 'Admin' : 'Atendente'}</Badge></td>
                <td style={{ padding: '10px 16px', fontSize: 13 }}>{(u.papel === 'admin' || u.verTodos) ? 'Sim' : 'Não'}</td>
                <td style={{ padding: '10px 16px' }}><Badge variant={u.ativo ? 'success' : 'neutral'}>{u.ativo ? 'Ativo' : 'Inativo'}</Badge></td>
                <td style={{ padding: '10px 16px', textAlign: 'right' }}>
                  <Button variant="ghost" size="sm" icon="edit" onClick={() => setModal(u)}>Editar</Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {modal && <UsuarioForm usuario={editando} onSave={salvar} onClose={() => setModal(null)} />}
    </div>
  );
}

Object.assign(window, { WhatsAyaAtendimento, WhatsAyaContatos, WhatsAyaUsuarios, ATENDIMENTO_BADGE_COUNT });
