const { useMemo: useWhatsAyaMemo, useState: useWhatsAyaState } = React;

const WHATSAYA_CONTACTS = [
  {
    id: 'marina', name: 'Marina Costa', initials: 'MC', phone: '(11) 9 8123-4401',
    stage: 'Qualificação', last: 'Quero entender como funciona a sessão.', time: '10:42', unread: 2,
    status: 'handoff', automation: false,
    messages: [
      { side: 'lead', body: 'Oi, vi o conteúdo de vocês e queria entender melhor.', time: '10:31' },
      { side: 'aya', body: 'Oi, Marina. Sou a AYA, assistente da Clínica Horizonte. Posso te explicar e também entender o que você busca hoje.', time: '10:32' },
      { side: 'lead', body: 'Quero entender como funciona a sessão.', time: '10:42' },
    ],
  },
  {
    id: 'paula', name: 'Paula Mendes', initials: 'PM', phone: '(21) 9 7402-1830',
    stage: 'Agendamento', last: 'Terça às 15h funciona para mim.', time: '09:18', unread: 0,
    status: 'scheduled', automation: true,
    messages: [
      { side: 'lead', body: 'Tem algum horário livre nesta semana?', time: '09:12' },
      { side: 'aya', body: 'Tenho terça às 15h e quinta às 18h disponíveis. Qual combina melhor com você?', time: '09:14' },
      { side: 'lead', body: 'Terça às 15h funciona para mim.', time: '09:18' },
      { side: 'aya', body: 'Perfeito. Vou reservar e já te confirmo os próximos passos.', time: '09:19' },
    ],
  },
  {
    id: 'luciana', name: 'Luciana Alves', initials: 'LA', phone: '(31) 9 6501-9274',
    stage: 'Novo lead', last: 'Áudio recebido · 0:38', time: 'Ontem', unread: 0,
    status: 'audio', automation: true,
    messages: [
      { side: 'lead', body: 'Áudio recebido · 0:38', time: 'Ontem, 18:06', audio: true },
      { side: 'system', body: 'Áudio transcrito e anexado ao contexto da conversa.', time: '18:07' },
      { side: 'aya', body: 'Entendi o que você relatou. Posso te fazer duas perguntas rápidas para direcionar melhor?', time: '18:08' },
    ],
  },
  {
    id: 'renata', name: 'Renata Lima', initials: 'RL', phone: '(41) 9 5330-1188',
    stage: 'Reativação D+2', last: 'Vou pensar e te chamo amanhã.', time: 'Seg', unread: 0,
    status: 'followup', automation: true,
    messages: [
      { side: 'lead', body: 'Vou pensar e te chamo amanhã.', time: 'Seg, 16:22' },
      { side: 'system', body: 'Follow-up D+2 programado para hoje às 14:30.', time: '16:23' },
    ],
  },
];

const PIPELINE_COLUMNS = [
  {
    key: 'new', label: 'Novos leads', count: 3,
    cards: [
      { name: 'Luciana Alves', detail: 'Entrou por indicação', time: 'há 18 min', badge: 'IA ativa' },
      { name: 'Camila Rocha', detail: 'Primeiro contato recebido', time: 'há 1 h', badge: 'IA ativa' },
      { name: 'Fernanda Souza', detail: 'Aguardando contexto', time: 'há 3 h', badge: 'IA ativa' },
    ],
  },
  {
    key: 'qualified', label: 'Qualificação', count: 2,
    cards: [
      { name: 'Marina Costa', detail: 'Pediu atendimento humano', time: 'há 4 min', badge: 'Handoff', attention: true },
      { name: 'Bianca Freitas', detail: 'Dúvida sobre a sessão', time: 'há 42 min', badge: 'IA ativa' },
    ],
  },
  {
    key: 'scheduled', label: 'Agendamento', count: 2,
    cards: [
      { name: 'Paula Mendes', detail: 'Terça · 15:00', time: 'confirmado', badge: 'Google Agenda', success: true },
      { name: 'Juliana Prado', detail: 'Aguardando escolha de horário', time: 'há 2 h', badge: 'IA ativa' },
    ],
  },
  {
    key: 'converted', label: 'Convertidos', count: 2,
    cards: [
      { name: 'Ana Ribeiro', detail: 'Sessão individual', time: 'hoje', badge: 'Concluído', success: true },
      { name: 'Sofia Martins', detail: 'Método gravado', time: 'ontem', badge: 'Concluído', success: true },
    ],
  },
];

const _surface = {
  background: 'var(--card)', border: '1px solid var(--border-solid)', borderRadius: 8,
};

function WhatsAyaPageHeader({ eyebrow, title, subtitle, actions }) {
  return (
    <div className="wa-page-header" style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 20, marginBottom: 24 }}>
      <div>
        <div style={{ color: 'var(--primary)', fontSize: 11, lineHeight: 1.2, fontWeight: 700, marginBottom: 7 }}>{eyebrow}</div>
        <h1 style={{ margin: 0, font: '600 24px/1.25 var(--font-sans)', letterSpacing: '-.01em' }}>{title}</h1>
        <p style={{ margin: '6px 0 0', color: 'var(--foreground-75)', fontSize: 13, lineHeight: 1.5 }}>{subtitle}</p>
      </div>
      {actions && <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>{actions}</div>}
    </div>
  );
}

function WhatsAyaStatus({ tone = 'neutral', children }) {
  const styles = tone === 'success'
    ? { background: 'var(--success-fade)', border: 'var(--success)', dot: 'var(--success)' }
    : tone === 'warning'
      ? { background: 'var(--warning-fade)', border: 'var(--warning)', dot: 'var(--warning)' }
      : { background: 'var(--muted-solid)', border: 'var(--border-solid)', dot: 'var(--muted-foreground)' };
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minHeight: 24, padding: '2px 9px', borderRadius: 999,
      background: styles.background, border: `1px solid ${styles.border}`, fontSize: 11, fontWeight: 700, whiteSpace: 'nowrap' }}>
      <span style={{ width: 6, height: 6, borderRadius: 999, background: styles.dot }} />{children}
    </span>
  );
}

function WhatsAyaMetric({ icon, label, value, helper, tone = 'neutral' }) {
  const iconBackground = tone === 'success' ? 'var(--success-fade)' : tone === 'warning' ? 'var(--warning-fade)' : 'var(--muted-solid)';
  const iconColor = tone === 'success' ? 'var(--success)' : tone === 'warning' ? 'var(--primary)' : 'var(--foreground)';
  return (
    <article style={{ ..._surface, padding: 16, minHeight: 130, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--foreground-75)' }}>{label}</span>
        <span style={{ width: 30, height: 30, borderRadius: 6, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', background: iconBackground, color: iconColor }}>
          <i className={`fi fi-rr-${icon}`} style={{ fontSize: 14, lineHeight: 0 }} />
        </span>
      </div>
      <div style={{ font: '700 34px/1 var(--font-numeric)', letterSpacing: '-.03em' }}>{value}</div>
      <div style={{ fontSize: 11, color: 'var(--muted-foreground)' }}>{helper}</div>
    </article>
  );
}

function WhatsAyaSectionHeader({ title, subtitle, action }) {
  return (
    <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 14 }}>
      <div>
        <h2 style={{ margin: 0, font: '600 16px/1.3 var(--font-sans)' }}>{title}</h2>
        {subtitle && <div style={{ marginTop: 3, fontSize: 11, color: 'var(--muted-foreground)' }}>{subtitle}</div>}
      </div>
      {action}
    </header>
  );
}

function WhatsAyaToggle({ checked, onChange, label }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} onClick={onChange}
      style={{ width: 40, height: 22, padding: 2, borderRadius: 999, border: `1px solid ${checked ? 'var(--success)' : 'var(--border-solid)'}`,
        background: checked ? 'var(--success)' : 'var(--muted-solid)', cursor: 'pointer', transition: 'background .18s', flexShrink: 0 }}>
      <span style={{ display: 'block', width: 16, height: 16, borderRadius: 999, background: 'var(--card)',
        transform: checked ? 'translateX(17px)' : 'translateX(0)', transition: 'transform .18s', boxShadow: 'var(--shadow-xs)' }} />
    </button>
  );
}

function WhatsAyaOverview({ onNavigate, botPaused, onToggleBot }) {
  const automationLabel = botPaused ? 'Automação pausada' : 'Automação ativa';
  return (
    <div>
      <WhatsAyaPageHeader eyebrow="Dr. Exemplo · Clínica Horizonte" title="Bom dia, Dr. Exemplo."
        subtitle="Acompanhe o atendimento da AYA e veja o que precisa da sua decisão agora."
        actions={[
          <WhatsAyaStatus key="preview" tone="neutral">Dados demonstrativos</WhatsAyaStatus>,
          <Button key="bot" variant={botPaused ? 'primary' : 'outline'} icon={botPaused ? 'play' : 'pause'} onClick={onToggleBot}>
            {botPaused ? 'Retomar IA' : 'Pausar IA'}
          </Button>,
        ]} />

      <section style={{ ..._surface, background: 'var(--header)', color: 'var(--header-foreground)', padding: 20, marginBottom: 16,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 18, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <span style={{ width: 42, height: 42, borderRadius: 8, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            background: 'var(--success)', color: 'var(--aya-black)', fontSize: 20 }}><i className="fi fi-rr-comment-alt" /></span>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <strong style={{ fontSize: 15 }}>WhatsApp conectado</strong>
              <WhatsAyaStatus tone={botPaused ? 'warning' : 'success'}>{automationLabel}</WhatsAyaStatus>
            </div>
            <div style={{ color: 'var(--header-foreground-50)', fontSize: 11, marginTop: 5 }}>Sessão estável há 3d 8h · última sincronização agora</div>
          </div>
        </div>
        <Button variant="outline" icon="settings" onClick={() => onNavigate('operations')}>Ver conexão</Button>
      </section>

      <div className="wa-metrics" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 12, marginBottom: 16 }}>
        <WhatsAyaMetric icon="users-alt" label="Leads migrados" value="9" helper="base Clínica Horizonte preparada" />
        <WhatsAyaMetric icon="comment-alt" label="Mensagens históricas" value="179" helper="somente leitura no contexto" />
        <WhatsAyaMetric icon="calendar-check" label="Agendamentos" value="2" helper="1 aguardando reconciliação" tone="success" />
        <WhatsAyaMetric icon="headset" label="Fila humana" value="1" helper="handoff com prioridade" tone="warning" />
      </div>

      <div className="wa-two-columns" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.45fr) minmax(300px, .75fr)', gap: 16 }}>
        <section style={{ ..._surface, padding: 18 }}>
          <WhatsAyaSectionHeader title="Quem precisa de você" subtitle="Handoffs e situações que a IA não deve decidir sozinha"
            action={<Button variant="ghost" size="sm" onClick={() => onNavigate('conversations')}>Ver conversas</Button>} />
          <button onClick={() => onNavigate('conversations')} style={{ width: '100%', padding: 14, borderRadius: 6, border: '1px solid var(--primary)',
            background: 'var(--warning-fade)', display: 'flex', alignItems: 'center', gap: 12, textAlign: 'left', cursor: 'pointer' }}>
            <span style={{ width: 36, height: 36, borderRadius: 999, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              background: 'var(--card)', fontWeight: 700 }}>MC</span>
            <span style={{ flex: 1, minWidth: 0 }}>
              <strong style={{ display: 'block', fontSize: 13 }}>Marina Costa pediu atendimento humano</strong>
              <span style={{ display: 'block', marginTop: 3, color: 'var(--foreground-75)', fontSize: 11 }}>Dúvida sensível sobre a sessão · esperando há 4 min</span>
            </span>
            <i className="fi fi-rr-arrow-right" style={{ color: 'var(--primary)' }} />
          </button>
          <div style={{ marginTop: 12, padding: '13px 14px', background: 'var(--muted-solid)', borderRadius: 6, display: 'flex', gap: 10, alignItems: 'center' }}>
            <i className="fi fi-rr-shield-check" style={{ color: 'var(--success)', fontSize: 17 }} />
            <span style={{ fontSize: 11, color: 'var(--foreground-75)' }}>Nenhuma conversa sem resposta e nenhum alerta crítico nas últimas 24 horas.</span>
          </div>
        </section>

        <section style={{ ..._surface, padding: 18 }}>
          <WhatsAyaSectionHeader title="Próximas ações" subtitle="Fila automática aprovada" />
          {[
            ['14:30', 'Follow-up D+2', 'Renata Lima'],
            ['16:00', 'Retomar qualificação', 'Bianca Freitas'],
            ['Amanhã', 'Oferta final', 'Carolina Dias'],
          ].map((item, index) => (
            <div key={item[2]} style={{ display: 'grid', gridTemplateColumns: '58px 1fr', gap: 10, padding: '11px 0',
              borderTop: index ? '1px solid var(--border-solid)' : 'none' }}>
              <span style={{ font: '600 11px/1.4 var(--font-numeric)', color: 'var(--primary)' }}>{item[0]}</span>
              <span><strong style={{ display: 'block', fontSize: 12 }}>{item[1]}</strong><small style={{ color: 'var(--muted-foreground)' }}>{item[2]}</small></span>
            </div>
          ))}
          <Button variant="neutral" full onClick={() => onNavigate('reactivation')}>Abrir reativação</Button>
        </section>
      </div>
    </div>
  );
}

function WhatsAyaConversations() {
  const [selectedId, setSelectedId] = useWhatsAyaState('marina');
  const [query, setQuery] = useWhatsAyaState('');
  const [pausedIds, setPausedIds] = useWhatsAyaState(new Set(['marina']));
  const selected = WHATSAYA_CONTACTS.find((contact) => contact.id === selectedId) || WHATSAYA_CONTACTS[0];
  const visibleContacts = useWhatsAyaMemo(() => WHATSAYA_CONTACTS.filter((contact) =>
    `${contact.name} ${contact.phone}`.toLowerCase().includes(query.toLowerCase())), [query]);
  const paused = pausedIds.has(selected.id);
  const togglePaused = () => {
    const next = new Set(pausedIds);
    paused ? next.delete(selected.id) : next.add(selected.id);
    setPausedIds(next);
  };

  return (
    <div>
      <WhatsAyaPageHeader eyebrow="Atendimento" title="Conversas"
        subtitle="Histórico do WhatsApp, contexto comercial e takeover humano em um único lugar."
        actions={<WhatsAyaStatus tone="success">WhatsApp conectado</WhatsAyaStatus>} />
      <div className="wa-chat-layout" style={{ ..._surface, display: 'grid', gridTemplateColumns: '320px minmax(0, 1fr)', minHeight: 620, overflow: 'hidden' }}>
        <aside style={{ borderRight: '1px solid var(--border-solid)', minWidth: 0 }}>
          <div style={{ padding: 14, borderBottom: '1px solid var(--border-solid)' }}>
            <Input full icon="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar conversa" label="Leads" />
          </div>
          <div className="wa-chat-list" style={{ overflowY: 'auto' }}>
            {visibleContacts.map((contact) => {
              const active = contact.id === selected.id;
              return (
                <button key={contact.id} onClick={() => setSelectedId(contact.id)} style={{ width: '100%', border: 0,
                  borderBottom: '1px solid var(--border-solid)', borderLeft: active ? '3px solid var(--primary)' : '3px solid transparent',
                  background: active ? 'var(--warning-fade)' : 'var(--card)', padding: '13px 12px', display: 'flex', gap: 10, textAlign: 'left', cursor: 'pointer' }}>
                  <span style={{ width: 36, height: 36, borderRadius: 999, background: active ? 'var(--primary)' : 'var(--muted-solid)',
                    color: active ? 'var(--primary-foreground)' : 'var(--foreground)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 11, flexShrink: 0 }}>
                    {contact.initials}
                  </span>
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                      <strong style={{ fontSize: 12 }}>{contact.name}</strong><small style={{ color: 'var(--muted-foreground)' }}>{contact.time}</small>
                    </span>
                    <span style={{ display: 'block', marginTop: 4, fontSize: 11, color: 'var(--foreground-75)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{contact.last}</span>
                    <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 7 }}>
                      <small style={{ color: 'var(--muted-foreground)' }}>{contact.stage}</small>
                      {contact.unread > 0 && <span style={{ minWidth: 18, height: 18, padding: '0 5px', borderRadius: 999, background: 'var(--success)',
                        display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 700 }}>{contact.unread}</span>}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </aside>

        <section style={{ minWidth: 0, display: 'flex', flexDirection: 'column', background: 'var(--muted-solid)' }}>
          <header style={{ padding: '13px 16px', background: 'var(--card)', borderBottom: '1px solid var(--border-solid)',
            display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <div>
              <strong style={{ display: 'block', fontSize: 13 }}>{selected.name}</strong>
              <span style={{ fontSize: 10, color: 'var(--muted-foreground)' }}>{selected.phone} · {selected.stage}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <WhatsAyaStatus tone={paused ? 'warning' : 'success'}>{paused ? 'Handoff humano' : 'IA ativa'}</WhatsAyaStatus>
              <Button variant={paused ? 'primary' : 'outline'} size="sm" icon={paused ? 'play' : 'pause'} onClick={togglePaused}>
                {paused ? 'Retomar IA' : 'Pausar IA'}
              </Button>
            </div>
          </header>

          <div style={{ flex: 1, padding: 20, display: 'flex', flexDirection: 'column', gap: 8, overflowY: 'auto' }}>
            <div style={{ alignSelf: 'center', fontSize: 10, color: 'var(--muted-foreground)', padding: '4px 9px', background: 'var(--card)', borderRadius: 999 }}>Hoje</div>
            {selected.messages.map((message, index) => {
              if (message.side === 'system') {
                return <div key={index} style={{ alignSelf: 'center', maxWidth: 440, textAlign: 'center', padding: '7px 11px',
                  borderRadius: 6, background: 'var(--success-fade)', border: '1px solid var(--success)', fontSize: 10 }}>{message.body}</div>;
              }
              const outgoing = message.side === 'aya';
              return (
                <div key={index} style={{ alignSelf: outgoing ? 'flex-end' : 'flex-start', maxWidth: '72%', padding: '10px 12px',
                  background: outgoing ? 'var(--success-fade)' : 'var(--card)', border: `1px solid ${outgoing ? 'var(--success)' : 'var(--border-solid)'}`,
                  borderRadius: outgoing ? '8px 2px 8px 8px' : '2px 8px 8px 8px', fontSize: 12, lineHeight: 1.5 }}>
                  {message.audio && <i className="fi fi-rr-waveform-path" style={{ marginRight: 7, color: 'var(--primary)' }} />}
                  {message.body}
                  <small style={{ display: 'block', marginTop: 5, textAlign: 'right', color: 'var(--muted-foreground)', fontSize: 9 }}>{message.time}</small>
                </div>
              );
            })}
          </div>
          <footer style={{ padding: 14, background: 'var(--card)', borderTop: '1px solid var(--border-solid)' }}>
            <div style={{ border: '1px solid var(--border-solid)', borderRadius: 6, padding: '11px 12px', display: 'flex', alignItems: 'center', gap: 10,
              color: 'var(--foreground-75)', background: 'var(--muted-solid)', fontSize: 11 }}>
              <i className="fi fi-rr-lock" />
              <span style={{ flex: 1 }}>Somente leitura. Responda pelo WhatsApp para manter o fluxo oficial de entrega e silenciar a IA automaticamente.</span>
              <Button variant="neutral" size="sm" icon="comment-alt">Abrir WhatsApp</Button>
            </div>
          </footer>
        </section>
      </div>
    </div>
  );
}

function WhatsAyaPipeline({ onOpenConversation }) {
  const [query, setQuery] = useWhatsAyaState('');
  const columns = PIPELINE_COLUMNS.map((column) => ({
    ...column,
    cards: column.cards.filter((card) => card.name.toLowerCase().includes(query.toLowerCase())),
  }));
  return (
    <div>
      <WhatsAyaPageHeader eyebrow="Comercial" title="Pipeline de leads"
        subtitle="A etapa organiza o próximo passo; mudanças no funil recalculam o follow-up da AYA."
        actions={<Input icon="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar lead" />} />
      <div className="wa-pipeline" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(220px, 1fr))', gap: 12, alignItems: 'start' }}>
        {columns.map((column) => (
          <section key={column.key} style={{ background: 'var(--muted-transparent)', border: '1px solid var(--border-solid)', borderRadius: 8, padding: 10 }}>
            <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '3px 4px 11px' }}>
              <span style={{ fontSize: 12, fontWeight: 700 }}>{column.label}</span>
              <span style={{ minWidth: 22, height: 22, padding: '0 7px', borderRadius: 999, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                background: 'var(--card)', border: '1px solid var(--border-solid)', font: '600 10px/1 var(--font-numeric)' }}>{column.cards.length}</span>
            </header>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {column.cards.map((card) => (
                <button key={card.name} onClick={onOpenConversation} style={{ ..._surface, padding: 12, textAlign: 'left', cursor: 'pointer', width: '100%', boxShadow: card.attention ? 'inset 3px 0 0 var(--primary)' : 'none' }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
                    <strong style={{ fontSize: 12 }}>{card.name}</strong>
                    <i className="fi fi-rr-menu-dots" style={{ color: 'var(--muted-foreground)' }} />
                  </div>
                  <div style={{ marginTop: 6, color: 'var(--foreground-75)', fontSize: 10, lineHeight: 1.45 }}>{card.detail}</div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6, marginTop: 11 }}>
                    <WhatsAyaStatus tone={card.attention ? 'warning' : card.success ? 'success' : 'neutral'}>{card.badge}</WhatsAyaStatus>
                    <small style={{ color: 'var(--muted-foreground)', fontSize: 9 }}>{card.time}</small>
                  </div>
                </button>
              ))}
              {column.cards.length === 0 && <div style={{ padding: 22, textAlign: 'center', color: 'var(--muted-foreground)', fontSize: 11 }}>Nenhum lead</div>}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function WhatsAyaReactivation() {
  const [enabled, setEnabled] = useWhatsAyaState(false);
  const [jobs, setJobs] = useWhatsAyaState([
    { id: 1, name: 'Renata Lima', step: 'D+2', scheduled: 'Hoje, 14:30', state: 'Pronto', paused: false },
    { id: 2, name: 'Carolina Dias', step: 'Oferta final', scheduled: 'Amanhã, 10:15', state: 'Aguardando', paused: false },
    { id: 3, name: 'Vanessa Melo', step: 'D+1', scheduled: 'Amanhã, 16:40', state: 'Pausado', paused: true },
  ]);
  const toggleJob = (id) => setJobs(jobs.map((job) => job.id === id ? { ...job, paused: !job.paused, state: job.paused ? 'Aguardando' : 'Pausado' } : job));
  return (
    <div>
      <WhatsAyaPageHeader eyebrow="Cadência comercial" title="Reativação"
        subtitle="Revise a fila herdada da Clínica Horizonte antes de liberar qualquer envio automático."
        actions={<WhatsAyaStatus tone={enabled ? 'success' : 'warning'}>{enabled ? 'Cadência ativa' : 'Aguardando aprovação'}</WhatsAyaStatus>} />
      <section style={{ ..._surface, padding: 18, marginBottom: 16, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 18, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <span style={{ width: 38, height: 38, borderRadius: 8, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            background: enabled ? 'var(--success-fade)' : 'var(--warning-fade)', color: enabled ? 'var(--success)' : 'var(--primary)' }}>
            <i className="fi fi-rr-rotate-right" />
          </span>
          <div><strong style={{ display: 'block', fontSize: 13 }}>Automação de reativação</strong>
            <span style={{ color: 'var(--muted-foreground)', fontSize: 11 }}>Janela de 72h · opt-out e takeover respeitados</span></div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 11, fontWeight: 600 }}>{enabled ? 'Ligada' : 'Desligada'}</span>
          <WhatsAyaToggle checked={enabled} onChange={() => setEnabled(!enabled)} label="Alternar automação de reativação" />
        </div>
      </section>
      <section style={{ ..._surface, padding: 18 }}>
        <WhatsAyaSectionHeader title="Fila preparada" subtitle="3 contatos · nenhuma mensagem foi enviada nesta prévia"
          action={<Button variant="outline" size="sm" icon="settings">Editar política</Button>} />
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 620 }}>
            <thead><tr style={{ background: 'var(--muted-solid)' }}>
              {['Lead', 'Etapa', 'Programado para', 'Estado', 'Ação'].map((label) => <th key={label} style={{ padding: '10px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, borderBottom: '1px solid var(--border-solid)' }}>{label}</th>)}
            </tr></thead>
            <tbody>{jobs.map((job) => (
              <tr key={job.id} style={{ borderBottom: '1px solid var(--border-solid)' }}>
                <td style={{ padding: 12, fontSize: 12, fontWeight: 600 }}>{job.name}</td>
                <td style={{ padding: 12, fontSize: 11 }}>{job.step}</td>
                <td style={{ padding: 12, font: '600 11px/1.4 var(--font-numeric)' }}>{job.scheduled}</td>
                <td style={{ padding: 12 }}><WhatsAyaStatus tone={job.paused ? 'warning' : job.state === 'Pronto' ? 'success' : 'neutral'}>{job.state}</WhatsAyaStatus></td>
                <td style={{ padding: 12 }}><Button variant="ghost" size="sm" icon={job.paused ? 'play' : 'pause'} onClick={() => toggleJob(job.id)}>{job.paused ? 'Retomar' : 'Pausar'}</Button></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function WhatsAyaSettingRow({ icon, title, description, checked, onChange, detail }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 0', borderTop: '1px solid var(--border-solid)' }}>
      <span style={{ width: 32, height: 32, borderRadius: 6, background: 'var(--muted-solid)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        <i className={`fi fi-rr-${icon}`} style={{ fontSize: 14 }} />
      </span>
      <span style={{ flex: 1, minWidth: 0 }}><strong style={{ display: 'block', fontSize: 12 }}>{title}</strong>
        <small style={{ display: 'block', marginTop: 3, color: 'var(--muted-foreground)', lineHeight: 1.45 }}>{description}</small></span>
      {detail || <WhatsAyaToggle checked={checked} onChange={onChange} label={`Alternar ${title}`} />}
    </div>
  );
}

function WhatsAyaOperations({ botPaused, onToggleBot }) {
  const [rejectCalls, setRejectCalls] = useWhatsAyaState(true);
  const [groups, setGroups] = useWhatsAyaState(false);
  const [audio, setAudio] = useWhatsAyaState(true);
  const [media, setMedia] = useWhatsAyaState(true);
  const [notifications, setNotifications] = useWhatsAyaState(true);
  const [rollout, setRollout] = useWhatsAyaState('10');
  return (
    <div>
      <WhatsAyaPageHeader eyebrow="Operação" title="Configurações"
        subtitle="Controles seguros para conexão, automação e integrações do fluxo Clínica Horizonte."
        actions={<Button variant="primary" icon="disk">Salvar alterações</Button>} />

      <section style={{ ..._surface, padding: 18, marginBottom: 16, borderColor: botPaused ? 'var(--primary)' : 'var(--success)' }}>
        <WhatsAyaSectionHeader title="Estado geral" subtitle="O kill switch interrompe respostas automáticas para todos os leads." />
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <WhatsAyaStatus tone={botPaused ? 'warning' : 'success'}>{botPaused ? 'IA pausada globalmente' : 'IA ativa'}</WhatsAyaStatus>
            <span style={{ fontSize: 11, color: 'var(--muted-foreground)' }}>WhatsApp conectado · bridge saudável</span>
          </div>
          <Button variant={botPaused ? 'primary' : 'outline'} icon={botPaused ? 'play' : 'pause'} onClick={onToggleBot}>{botPaused ? 'Retomar atendimento' : 'Pausar IA'}</Button>
        </div>
      </section>

      <div className="wa-settings-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 16 }}>
        <section style={{ ..._surface, padding: 18 }}>
          <WhatsAyaSectionHeader title="WhatsApp" subtitle="Aplicado pela ponte em tempo real" />
          <WhatsAyaSettingRow icon="phone-call" title="Recusar ligações" description="Evita que chamadas interrompam o atendimento." checked={rejectCalls} onChange={() => setRejectCalls(!rejectCalls)} />
          <WhatsAyaSettingRow icon="users-alt" title="Processar grupos" description="Mantém a AYA fora de grupos por padrão." checked={groups} onChange={() => setGroups(!groups)} />
          <WhatsAyaSettingRow icon="hourglass-end" title="Espera inicial" description="Agrupa mensagens picadas antes de responder."
            detail={<span style={{ font: '600 11px/1 var(--font-numeric)', padding: '8px 10px', background: 'var(--muted-solid)', borderRadius: 4 }}>8 segundos</span>} />
        </section>

        <section style={{ ..._surface, padding: 18 }}>
          <WhatsAyaSectionHeader title="Inteligência" subtitle="Comportamento do atendimento" />
          <WhatsAyaSettingRow icon="waveform-path" title="Transcrever áudios" description="Usa transcrição antes de seguir o funil." checked={audio} onChange={() => setAudio(!audio)} />
          <WhatsAyaSettingRow icon="picture" title="Mídia e prova social" description="Libera apenas os materiais aprovados no manifesto." checked={media} onChange={() => setMedia(!media)} />
          <WhatsAyaSettingRow icon="bell" title="Avisar Dr. Exemplo" description="Notifica em handoff, agenda e falha silenciosa." checked={notifications} onChange={() => setNotifications(!notifications)} />
        </section>

        <section style={{ ..._surface, padding: 18 }}>
          <WhatsAyaSectionHeader title="Rollout gradual" subtitle="Percentual determinístico de novos leads atendidos pela IA" />
          <div className="wa-form-row" style={{ display: 'grid', gridTemplateColumns: '1fr 120px', gap: 12, alignItems: 'end' }}>
            <div>
              <div style={{ height: 8, borderRadius: 999, background: 'var(--muted-solid)', overflow: 'hidden', marginBottom: 8 }}>
                <div style={{ width: `${rollout}%`, height: '100%', background: 'var(--primary)' }} />
              </div>
              <span style={{ fontSize: 11, color: 'var(--muted-foreground)' }}>{rollout}% automático · {100 - Number(rollout)}% direto para atendimento humano</span>
            </div>
            <Select full label="Percentual" value={rollout} onChange={(event) => setRollout(event.target.value)} options={[
              { value: '5', label: '5%' }, { value: '10', label: '10%' }, { value: '25', label: '25%' }, { value: '50', label: '50%' }, { value: '100', label: '100%' },
            ]} />
          </div>
        </section>

        <section style={{ ..._surface, padding: 18 }}>
          <WhatsAyaSectionHeader title="Agenda e horários" subtitle="Requer reconciliação antes do corte para produção" />
          <WhatsAyaSettingRow icon="calendar" title="Google Calendar" description="Disponibilidade e criação de evento."
            detail={<WhatsAyaStatus tone="warning">Autorização pendente</WhatsAyaStatus>} />
          <WhatsAyaSettingRow icon="clock" title="Horário comercial" description="Segunda a sexta · America/Sao_Paulo"
            detail={<span style={{ font: '600 11px/1 var(--font-numeric)' }}>09:00–19:00</span>} />
        </section>
      </div>
    </div>
  );
}

const AGENDA_DAYS = [
  { id: 1, name: 'Seg', date: '08 Set', full: 'Segunda-feira', isToday: false },
  { id: 2, name: 'Ter', date: '09 Set', full: 'Terça-feira', isToday: true },
  { id: 3, name: 'Qua', date: '10 Set', full: 'Quarta-feira', isToday: false },
  { id: 4, name: 'Qui', date: '11 Set', full: 'Quinta-feira', isToday: false },
  { id: 5, name: 'Sex', date: '12 Set', full: 'Sexta-feira', isToday: false },
  { id: 6, name: 'Sáb', date: '13 Set', full: 'Sábado', isToday: false, dim: true },
  { id: 7, name: 'Dom', date: '14 Set', full: 'Domingo', isToday: false, dim: true },
];

const AGENDA_EVENTS = [
  {
    id: 'ev-1', dayId: 1, start: '09:00', end: '10:00', startHour: 9, startMin: 0, durationMin: 60,
    kind: 'busy', title: 'Ocupado', subtitle: 'Compromisso particular',
  },
  {
    id: 'ev-2', dayId: 1, start: '11:00', end: '11:50', startHour: 11, startMin: 0, durationMin: 50,
    kind: 'slot', title: 'Horário livre', subtitle: 'Disponível para oferta da IA',
  },
  {
    id: 'ev-3', dayId: 2, start: '10:00', end: '10:50', startHour: 10, startMin: 0, durationMin: 50,
    kind: 'slot', title: 'Horário livre', subtitle: 'Disponível para oferta da IA',
  },
  {
    id: 'ev-4', dayId: 2, start: '15:00', end: '15:50', startHour: 15, startMin: 0, durationMin: 50,
    kind: 'booking', title: 'Marina Costa', subtitle: 'Sessão individual confirmada',
    leadPhone: '(11) 9 8123-4401', meetUrl: 'https://meet.google.com/abc-defg-hij', gcalUrl: 'https://calendar.google.com',
  },
  {
    id: 'ev-5', dayId: 3, start: '10:00', end: '10:50', startHour: 10, startMin: 0, durationMin: 50,
    kind: 'booking', title: 'Paula Mendes', subtitle: 'Sessão inicial agendada',
    leadPhone: '(21) 9 7402-1830', meetUrl: 'https://meet.google.com/xyz-uvwx-rst', gcalUrl: 'https://calendar.google.com',
  },
  {
    id: 'ev-6', dayId: 3, start: '13:00', end: '14:30', startHour: 13, startMin: 0, durationMin: 90,
    kind: 'block', title: 'Bloqueado', subtitle: 'Supervisão clínica',
  },
  {
    id: 'ev-7', dayId: 4, start: '14:00', end: '14:50', startHour: 14, startMin: 0, durationMin: 50,
    kind: 'slot', title: 'Horário livre', subtitle: 'Disponível para oferta da IA',
  },
  {
    id: 'ev-8', dayId: 4, start: '16:00', end: '16:50', startHour: 16, startMin: 0, durationMin: 50,
    kind: 'booking', title: 'Renata Lima', subtitle: 'Follow-up de alinhamento',
    leadPhone: '(41) 9 5330-1188', meetUrl: 'https://meet.google.com/mnp-qrst-uvw', gcalUrl: 'https://calendar.google.com',
  },
  {
    id: 'ev-9', dayId: 5, start: '11:00', end: '11:50', startHour: 11, startMin: 0, durationMin: 50,
    kind: 'slot', title: 'Horário livre', subtitle: 'Disponível para oferta da IA',
  },
  {
    id: 'ev-10', dayId: 5, start: '15:00', end: '15:50', startHour: 15, startMin: 0, durationMin: 50,
    kind: 'slot', title: 'Horário livre', subtitle: 'Disponível para oferta da IA',
  },
];

function WhatsAyaAgenda() {
  const [selectedEvent, setSelectedEvent] = useWhatsAyaState(null);
  const [showSettings, setShowSettings] = useWhatsAyaState(false);
  const [mode, setMode] = useWhatsAyaState('explicit_slots');
  const [slotDuration, setSlotDuration] = useWhatsAyaState('50');

  const HOURS = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18];
  const HOUR_HEIGHT = 56;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <WhatsAyaPageHeader
        eyebrow="Agenda & Horários"
        title="Agenda de Atendimento"
        subtitle="Integração bidirecional com Google Calendar. Vagas de consulta e sessões agendadas automaticamente pela AYA."
        actions={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Button variant="outline" icon="settings" onClick={() => setShowSettings(!showSettings)}>
              {showSettings ? 'Ocultar regras' : 'Regras da agenda'}
            </Button>
            <Button variant="primary" icon="refresh">Sincronizar Google</Button>
          </div>
        }
      />

      {/* Barra de Conexão com o Google */}
      <section style={{
        ..._surface, padding: '14px 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        flexWrap: 'wrap', gap: 12, background: 'var(--card)', borderColor: 'var(--border-solid)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{
            width: 34, height: 34, borderRadius: 8, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            background: 'var(--success-fade)', color: 'var(--success)',
          }}>
            <i className="fi fi-rr-calendar-check" style={{ fontSize: 16 }} />
          </span>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 700 }}>Google Agenda Conectado</span>
              <WhatsAyaStatus tone="success">Ativo</WhatsAyaStatus>
            </div>
            <div style={{ fontSize: 12, color: 'var(--muted-foreground)', marginTop: 2 }}>
              Sincronizando com <strong>primary</strong> (agenda@clinica-exemplo.com.br) · Fuso: America/Sao_Paulo
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: 'var(--muted-foreground)' }}>Modo: <strong>{mode === 'explicit_slots' ? 'Vagas explícitas ("Livre")' : 'Intervalos livres'}</strong></span>
        </div>
      </section>

      {/* Painel expansível de Regras */}
      {showSettings && (
        <section style={{ ..._surface, padding: 18, background: 'var(--card-subtle, var(--card))' }}>
          <WhatsAyaSectionHeader
            title="Regras de Disponibilidade e Agendamento"
            subtitle="Configuração atômica compartilhada entre o painel e o robô sem necessidade de reiniciar contêineres."
          />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16, marginTop: 12 }}>
            <div>
              <label style={{ fontSize: 11, fontWeight: 700, display: 'block', marginBottom: 6 }}>Modo de Disponibilidade</label>
              <Select full value={mode} onChange={(e) => setMode(e.target.value)} options={[
                { value: 'explicit_slots', label: 'Vagas explícitas (Palavra "Livre")' },
                { value: 'freebusy_gaps', label: 'Intervalos livres do expediente (FreeBusy)' },
              ]} />
              <span style={{ fontSize: 11, color: 'var(--muted-foreground)', display: 'block', marginTop: 4 }}>
                {mode === 'explicit_slots' ? 'Apenas horários marcados com "Livre" na agenda do profissional são oferecidos aos leads.' : 'Qualquer buraco na agenda durante o expediente pode ser oferecido.'}
              </span>
            </div>
            <div>
              <label style={{ fontSize: 11, fontWeight: 700, display: 'block', marginBottom: 6 }}>Duração da Sessão</label>
              <Select full value={slotDuration} onChange={(e) => setSlotDuration(e.target.value)} options={[
                { value: '30', label: '30 minutos' },
                { value: '50', label: '50 minutos (padrão clínica)' },
                { value: '60', label: '60 minutos (1 hora)' },
              ]} />
              <span style={{ fontSize: 11, color: 'var(--muted-foreground)', display: 'block', marginTop: 4 }}>
                Tempo reservado em cada agendamento no Google Calendar.
              </span>
            </div>
            <div>
              <label style={{ fontSize: 11, fontWeight: 700, display: 'block', marginBottom: 6 }}>Antecedência Mínima</label>
              <Select full value="120" options={[
                { value: '60', label: '1 hora de antecedência' },
                { value: '120', label: '2 horas de antecedência' },
                { value: '360', label: '6 horas de antecedência' },
                { value: '1440', label: '24 horas de antecedência' },
              ]} />
              <span style={{ fontSize: 11, color: 'var(--muted-foreground)', display: 'block', marginTop: 4 }}>
                Evita que a IA marque reuniões em cima da hora sem tempo hábil.
              </span>
            </div>
          </div>
        </section>
      )}

      {/* Navegação Semanal e Legenda */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ display: 'inline-flex', borderRadius: 6, border: '1px solid var(--border-solid)', overflow: 'hidden' }}>
            <Button variant="ghost" icon="angle-left" />
            <Button variant="ghost" icon="angle-right" />
          </div>
          <span style={{ fontSize: 14, fontWeight: 700 }}>08 de Setembro – 14 de Setembro de 2026</span>
          <Button variant="outline">Hoje</Button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 600, color: 'var(--muted-foreground)' }}>
            <span style={{ width: 10, height: 10, borderRadius: 3, background: 'var(--primary)', display: 'inline-block' }} />
            <span>Agendado pela AYA</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 600, color: 'var(--muted-foreground)' }}>
            <span style={{ width: 10, height: 10, borderRadius: 3, background: 'rgba(76, 222, 89, 0.2)', border: '1px dashed var(--success)', display: 'inline-block' }} />
            <span>Vaga livre</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 600, color: 'var(--muted-foreground)' }}>
            <span style={{ width: 10, height: 10, borderRadius: 3, background: 'var(--muted-solid)', display: 'inline-block' }} />
            <span>Compromisso / Bloqueio</span>
          </div>
        </div>
      </div>

      {/* Grade Semanal */}
      <div style={{ ..._surface, overflow: 'hidden' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '60px repeat(7, minmax(120px, 1fr))', borderBottom: '1px solid var(--border-solid)' }}>
          <div style={{ padding: 10, borderRight: '1px solid var(--border-solid)' }} />
          {AGENDA_DAYS.map((d) => (
            <div key={d.id} style={{
              padding: '10px 8px', textAlign: 'center', borderRight: '1px solid var(--border-solid)',
              background: d.isToday ? 'var(--muted-solid)' : d.dim ? 'rgba(0,0,0,0.02)' : 'transparent',
            }}>
              <div style={{ fontSize: 10, textTransform: 'uppercase', fontWeight: 700, color: 'var(--muted-foreground)' }}>{d.name}</div>
              <div style={{
                fontSize: 14, fontWeight: 800, marginTop: 2, display: 'inline-flex', width: 26, height: 26,
                alignItems: 'center', justifyContent: 'center', borderRadius: '50%',
                background: d.isToday ? 'var(--primary)' : 'transparent',
                color: d.isToday ? '#fff' : 'inherit',
              }}>{d.date.split(' ')[0]}</div>
            </div>
          ))}
        </div>

        {/* Linhas de Horário e Eventos */}
        <div style={{ display: 'grid', gridTemplateColumns: '60px repeat(7, minmax(120px, 1fr))', position: 'relative', minHeight: HOURS.length * HOUR_HEIGHT }}>
          {/* Coluna de Horas */}
          <div style={{ borderRight: '1px solid var(--border-solid)' }}>
            {HOURS.map((h) => (
              <div key={h} style={{
                height: HOUR_HEIGHT, boxSizing: 'border-box', borderTop: '1px solid var(--border-solid)',
                fontSize: 10, fontWeight: 600, color: 'var(--muted-foreground)', paddingRight: 6, paddingTop: 2, textAlign: 'right',
              }}>
                {String(h).padStart(2, '0')}:00
              </div>
            ))}
          </div>

          {/* Colunas dos 7 Dias */}
          {AGENDA_DAYS.map((day) => {
            const dayEvents = AGENDA_EVENTS.filter((ev) => ev.dayId === day.id);
            return (
              <div key={day.id} style={{
                position: 'relative', borderRight: '1px solid var(--border-solid)',
                background: day.isToday ? 'rgba(242, 110, 34, 0.03)' : day.dim ? 'rgba(0,0,0,0.015)' : 'transparent',
              }}>
                {HOURS.map((h) => (
                  <div key={h} style={{ height: HOUR_HEIGHT, boxSizing: 'border-box', borderTop: '1px solid var(--border-solid)' }} />
                ))}

                {/* Eventos do dia */}
                {dayEvents.map((ev) => {
                  const top = (ev.startHour - HOURS[0] + ev.startMin / 60) * HOUR_HEIGHT;
                  const height = (ev.durationMin / 60) * HOUR_HEIGHT - 3;
                  const isBooking = ev.kind === 'booking';
                  const isSlot = ev.kind === 'slot';

                  return (
                    <div
                      key={ev.id}
                      onClick={() => setSelectedEvent(ev)}
                      style={{
                        position: 'absolute', top: `${top}px`, left: '4px', right: '4px', height: `${height}px`,
                        borderRadius: 6, padding: '4px 6px', boxSizing: 'border-box', cursor: 'pointer',
                        background: isBooking
                          ? 'var(--warning-fade)'
                          : isSlot
                            ? 'rgba(76, 222, 89, 0.09)'
                            : 'var(--muted-solid)',
                        border: isBooking
                          ? '1px solid var(--primary)'
                          : isSlot
                            ? '1.5px dashed var(--success)'
                            : '1px solid var(--border-solid)',
                        color: isBooking
                          ? 'var(--foreground)'
                          : isSlot
                            ? 'var(--success)'
                            : 'var(--muted-foreground)',
                        fontSize: 11, display: 'flex', flexDirection: 'column', gap: 1, overflow: 'hidden',
                        boxShadow: isBooking ? '0 2px 6px rgba(242, 110, 34, 0.15)' : 'none',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <span style={{ font: '700 10px/1 var(--font-numeric)' }}>{ev.start} – {ev.end}</span>
                        {isBooking && (
                          <span style={{ background: 'var(--primary)', color: '#fff', fontSize: 8, fontWeight: 800, padding: '1px 4px', borderRadius: 4 }}>AYA</span>
                        )}
                      </div>
                      <div style={{ fontWeight: 700, textOverflow: 'ellipsis', whiteSpace: 'nowrap', overflow: 'hidden' }}>
                        {ev.title}
                      </div>
                      <div style={{ fontSize: 9.5, opacity: 0.85, textOverflow: 'ellipsis', whiteSpace: 'nowrap', overflow: 'hidden' }}>
                        {ev.subtitle}
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>

      {/* Modal / Drawer de Detalhes do Evento */}
      {selectedEvent && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(0,0,0,0.4)',
          display: 'flex', justifyContent: 'flex-end',
        }}>
          <div style={{
            width: 380, maxWidth: '92vw', height: '100%', background: 'var(--card)',
            boxShadow: '-10px 0 30px rgba(0,0,0,0.15)', padding: 24, display: 'flex', flexDirection: 'column', gap: 16,
            overflowY: 'auto',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--muted-foreground)' }}>Detalhes do horário</span>
                {selectedEvent.kind === 'booking' && <WhatsAyaStatus tone="warning">Agendado pela AYA</WhatsAyaStatus>}
                {selectedEvent.kind === 'slot' && <WhatsAyaStatus tone="success">Vaga Livre</WhatsAyaStatus>}
              </div>
              <Button variant="ghost" icon="cross" onClick={() => setSelectedEvent(null)} />
            </div>

            <h2 style={{ margin: 0, font: '600 20px/1.2 var(--font-sans)' }}>{selectedEvent.title}</h2>
            <div style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>{selectedEvent.subtitle}</div>

            <div style={{ ..._surface, padding: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                <span style={{ color: 'var(--muted-foreground)' }}>Horário:</span>
                <span style={{ fontWeight: 700 }}>{selectedEvent.start} às {selectedEvent.end}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                <span style={{ color: 'var(--muted-foreground)' }}>Duração:</span>
                <span style={{ fontWeight: 700 }}>{selectedEvent.durationMin} minutos</span>
              </div>
              {selectedEvent.leadPhone && (
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                  <span style={{ color: 'var(--muted-foreground)' }}>WhatsApp do Lead:</span>
                  <span style={{ fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{selectedEvent.leadPhone}</span>
                </div>
              )}
            </div>

            {selectedEvent.meetUrl && (
              <a href={selectedEvent.meetUrl} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
                <Button variant="primary" full icon="video-camera">Entrar na Sessão (Google Meet)</Button>
              </a>
            )}

            {selectedEvent.gcalUrl && (
              <a href={selectedEvent.gcalUrl} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
                <Button variant="outline" full icon="calendar">Ver no Google Agenda</Button>
              </a>
            )}

            <div style={{ marginTop: 'auto', paddingTop: 16, borderTop: '1px solid var(--border-solid)' }}>
              <Button variant="ghost" full icon="trash" onClick={() => setSelectedEvent(null)}>Fechar detalhes</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function WhatsAyaLogin() {
  const [username, setUsername] = useWhatsAyaState('admin');
  const [password, setPassword] = useWhatsAyaState('');
  const [showPassword, setShowPassword] = useWhatsAyaState(false);
  const [loading, setLoading] = useWhatsAyaState(false);
  const [feedback, setFeedback] = useWhatsAyaState(null);

  const handleLogin = (e) => {
    e.preventDefault();
    setLoading(true);
    setFeedback(null);
    setTimeout(() => {
      setLoading(false);
      if (password === 'correta' || password.length > 5) {
        setFeedback({ type: 'success', text: 'Autenticado com sucesso! Redirecionando para o painel…' });
      } else {
        setFeedback({ type: 'error', text: 'Usuário ou senha incorretos. Verifique suas credenciais.' });
      }
    }, 800);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <WhatsAyaPageHeader
        eyebrow="Segurança & Acesso"
        title="Tela de Autenticação (Login)"
        subtitle="Apresentação da interface de login mobile-first com cookie seguro HMAC-SHA256 e identidade visual customizável por cliente."
        actions={
          <Button variant="outline" icon="shield-check">Sessão Segura (30 dias)</Button>
        }
      />

      <div style={{
        minHeight: 520, borderRadius: 12, padding: '40px 20px',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'radial-gradient(at 50% 0%, rgba(242, 110, 34, 0.08) 0px, transparent 65%), radial-gradient(at 90% 100%, rgba(76, 222, 89, 0.06) 0px, transparent 55%), var(--muted-solid)',
        border: '1px solid var(--border-solid)',
      }}>
        <div style={{ width: '100%', maxWidth: 360, display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Status pill animada */}
          <div style={{
            alignSelf: 'center', display: 'inline-flex', alignItems: 'center', gap: 8, padding: '6px 14px',
            borderRadius: 999, background: 'rgba(255, 255, 255, 0.85)', backdropFilter: 'blur(10px)',
            border: '1px solid var(--border-solid)', fontSize: 11.5, fontWeight: 700, color: 'var(--foreground)',
            boxShadow: '0 2px 8px rgba(0, 0, 0, 0.04)',
          }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--success)' }} />
            <span>Acesso seguro com criptografia</span>
          </div>

          {/* Card de Login */}
          <div style={{
            background: 'var(--card)', border: '1px solid var(--border-solid)', borderRadius: 12, padding: '28px 24px',
            boxShadow: '0 10px 30px rgba(0,0,0,0.06)', display: 'flex', flexDirection: 'column', gap: 18,
          }}>
            <div style={{ textAlign: 'center' }}>
              <div style={{
                width: 44, height: 44, borderRadius: 10, background: 'var(--primary)', color: '#fff',
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontWeight: 900, fontSize: 18,
                marginBottom: 10,
              }}>
                A
              </div>
              <h2 style={{ margin: 0, font: '700 20px/1.2 var(--font-sans)', letterSpacing: '-0.02em' }}>WhatsAYA</h2>
              <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--muted-foreground)' }}>Entre para gerenciar leads, conversas e agenda</p>
            </div>

            {feedback && (
              <div style={{
                padding: '10px 12px', borderRadius: 6, fontSize: 12, fontWeight: 600,
                background: feedback.type === 'success' ? 'var(--success-fade)' : 'var(--warning-fade)',
                border: `1px solid ${feedback.type === 'success' ? 'var(--success)' : 'var(--warning)'}`,
                color: feedback.type === 'success' ? 'var(--success)' : 'var(--primary)',
              }}>
                {feedback.text}
              </div>
            )}

            <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label style={{ fontSize: 11.5, fontWeight: 700, display: 'block', marginBottom: 5 }}>Usuário</label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  style={{
                    width: '100%', height: 38, borderRadius: 6, border: '1px solid var(--border-solid)',
                    padding: '0 12px', fontSize: 13, background: 'var(--input-bg, #fff)', boxSizing: 'border-box',
                  }}
                />
              </div>

              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
                  <label style={{ fontSize: 11.5, fontWeight: 700 }}>Senha</label>
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    style={{ background: 'transparent', border: 0, fontSize: 11, color: 'var(--primary)', cursor: 'pointer', padding: 0 }}
                  >
                    {showPassword ? 'Ocultar' : 'Mostrar'}
                  </button>
                </div>
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  placeholder="••••••••"
                  onChange={(e) => setPassword(e.target.value)}
                  style={{
                    width: '100%', height: 38, borderRadius: 6, border: '1px solid var(--border-solid)',
                    padding: '0 12px', fontSize: 13, background: 'var(--input-bg, #fff)', boxSizing: 'border-box',
                  }}
                />
              </div>

              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 11.5 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                  <input type="checkbox" defaultChecked />
                  <span>Lembrar neste dispositivo</span>
                </label>
                <span style={{ color: 'var(--muted-foreground)' }}>30 dias</span>
              </div>

              <Button variant="primary" full icon={loading ? 'spinner' : 'arrow-right'}>
                {loading ? 'Autenticando…' : 'Acessar painel'}
              </Button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, {
  WhatsAyaOverview,
  WhatsAyaConversations,
  WhatsAyaPipeline,
  WhatsAyaAgenda,
  WhatsAyaReactivation,
  WhatsAyaOperations,
  WhatsAyaLogin,
});

