// Screens.jsx — CheckIns, Members, Settings, Modal
const { useState: useSc, useMemo: useMemoSc } = React;

function Modal({ open, title, subtitle, children, onClose, actions }) {
  if (!open) return null;
  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'rgba(7,11,13,0.55)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50,
      animation: 'fade .15s ease-out',
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width: 480, background: '#fff', borderRadius: 6,
        boxShadow: '0 9px 15.4px rgba(7,11,13,0.10)', overflow: 'hidden',
        animation: 'slideUp .18s ease-out',
      }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border-solid)',
          display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 600 }}>{title}</div>
            {subtitle && <div style={{ fontSize: 12, color: 'var(--muted-foreground)', marginTop: 2 }}>{subtitle}</div>}
          </div>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--muted-foreground)' }}>
            <i className="fi fi-rr-cross-small" style={{ fontSize: 16 }} />
          </button>
        </div>
        <div style={{ padding: 20 }}>{children}</div>
        <div style={{ padding: '12px 20px', borderTop: '1px solid var(--border-solid)',
          display: 'flex', justifyContent: 'flex-end', gap: 8, background: '#FFFFFF' }}>
          {actions}
        </div>
      </div>
    </div>
  );
}

function CheckInsScreen() {
  const [modalOpen, setModalOpen] = useSc(false);
  const [validated, setValidated] = useSc(false);
  const [code, setCode] = useSc('');
  const [loading, setLoading] = useSc(false);

  const handleValidate = () => {
    setLoading(true);
    setTimeout(() => { setLoading(false); setValidated(true); }, 800);
  };

  const closeModal = () => { setModalOpen(false); setValidated(false); setCode(''); };

  return (
    <div>
      <PageHeader title="Check-in"
        subtitle="Manage and validate your customers' check-ins."
        actions={[
          <Button key="1" variant="outline" icon="download">Export</Button>,
          <Button key="2" variant="primary" icon="barcode-scan" onClick={() => setModalOpen(true)}>Validate Check-in</Button>,
        ]} />

      <DataTable rows={[
        { name: 'Lucas Almeida',  plan: 'Annual',  at: '10:42', status: 'success', reason: 'Validated' },
        { name: 'Beatriz Nunes',  plan: 'Monthly', at: '10:39', status: 'success', reason: 'Validated' },
        { name: 'Paulo Ferreira', plan: 'Daily',   at: '10:36', status: 'warning', reason: 'Pending' },
        { name: 'Julia Santos',   plan: 'Annual',  at: '10:31', status: 'success', reason: 'Validated' },
        { name: 'Rafael Dias',    plan: 'Monthly', at: '10:28', status: 'danger',  reason: 'No subscription' },
        { name: 'Carla Moraes',   plan: 'Student', at: '10:24', status: 'success', reason: 'Validated' },
        { name: 'Diego Lopes',    plan: 'Monthly', at: '10:19', status: 'success', reason: 'Validated' },
        { name: 'Helena Braga',   plan: 'Annual',  at: '10:14', status: 'success', reason: 'Validated' },
        { name: 'Igor Tavares',   plan: 'Monthly', at: '10:09', status: 'danger',  reason: 'Expired' },
      ]} />

      <Modal open={modalOpen} onClose={closeModal}
        title={validated ? 'Check-in validated' : 'Validate Check-in'}
        subtitle={validated ? 'The member has been granted entry.' : 'Scan the barcode or enter the member ID.'}
        actions={validated
          ? [<Button key="ok" variant="primary" onClick={closeModal}>Done</Button>]
          : [
            <Button key="cn" variant="ghost" onClick={closeModal}>Cancel</Button>,
            <Button key="ok" variant="primary" icon={loading ? null : 'check'} disabled={loading || !code}
              onClick={handleValidate}>{loading ? 'Validating…' : 'Validate'}</Button>
          ]}>
        {validated ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, padding: '10px 0' }}>
            <img src="../../assets/images/happy.svg" style={{ height: 80 }} />
            <div style={{ fontFamily: 'Geist, ui-sans-serif', fontSize: 24, fontWeight: 600 }}>Welcome Back!</div>
            <div style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>Lucas Almeida · Annual plan</div>
            <Badge variant="success" icon="check">Validated at 10:42</Badge>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <Input icon="barcode-scan" label="Member ID / Barcode"
              value={code} onChange={e => setCode(e.target.value)}
              placeholder="Scan or type…" full />
            <Select label="Access Type" full
              options={[
                { value: 'single', label: 'Single entry' },
                { value: 'class', label: 'Class · Yoga 18:00' },
                { value: 'day', label: 'Day pass' },
              ]} value="single" onChange={() => {}} />
          </div>
        )}
      </Modal>
    </div>
  );
}

const MEMBERS = [
  { name: 'Lucas Almeida',  plan: 'Annual',  since: '2021', status: 'success', reason: 'Active',    tag: 'VIP' },
  { name: 'Beatriz Nunes',  plan: 'Monthly', since: '2024', status: 'success', reason: 'Active' },
  { name: 'Paulo Ferreira', plan: 'Daily',   since: '2025', status: 'warning', reason: 'Trial' },
  { name: 'Julia Santos',   plan: 'Annual',  since: '2019', status: 'success', reason: 'Active',    tag: 'VIP' },
  { name: 'Rafael Dias',    plan: 'Monthly', since: '2023', status: 'danger',  reason: 'Past due' },
  { name: 'Carla Moraes',   plan: 'Student', since: '2024', status: 'success', reason: 'Active' },
  { name: 'Diego Lopes',    plan: 'Monthly', since: '2022', status: 'success', reason: 'Active' },
];

function MembersScreen() {
  const [selected, setSelected] = useSc(new Set());
  const [search, setSearch]     = useSc('');
  const [activeFilter, setActiveFilter] = useSc('plan');
  const [page, setPage] = useSc(1);
  const [size, setSize] = useSc(10);
  const [sortKey, setSortKey] = useSc('name');
  const [sortDir, setSortDir] = useSc('asc');

  const tones = ['purple', 'blue', 'pink', 'emerald', 'orange', 'lime'];

  const columns = [
    { key: 'name', label: 'Member', sortable: true,
      render: m => (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
          <DxAvatar name={m.name} tone={tones[m.name.length % tones.length]} />
          <span style={{ display: 'flex', flexDirection: 'column' }}>
            <span style={{ fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              {m.name}
              {m.tag && <Badge variant="purple" icon="star" dot={false}>{m.tag}</Badge>}
            </span>
            <span style={{ fontSize: 11, color: 'var(--muted-foreground)' }}>
              {m.name.toLowerCase().replace(' ', '.')}@gmail.com
            </span>
          </span>
        </span>
      ) },
    { key: 'plan', label: 'Plan', sortable: true },
    { key: 'since', label: 'Since', sortable: true,
      render: m => <span style={{ fontFamily: 'Geist, ui-sans-serif', color: 'var(--muted-foreground)' }}>{m.since}</span> },
    { key: 'status', label: 'Status',
      render: m => <Badge variant={m.status}>{m.reason}</Badge> },
  ];

  return (
    <div>
      <PageHeader title="Members"
        subtitle="Your full roster — active, trial, and past due."
        actions={[
          <Button key="1" variant="outline" icon="upload">Import CSV</Button>,
          <Button key="2" variant="primary" icon="plus">Add Member</Button>,
        ]} />

      <DxDataGrid
        columns={columns} rows={MEMBERS}
        filters={[
          { key: 'plan',   label: 'Plan', count: activeFilter === 'plan' ? 1 : null },
          { key: 'status', label: 'Status' },
          { key: 'since',  label: 'Tenure' },
          { key: 'tag',    label: 'VIP' },
        ]}
        activeFilter={activeFilter}
        onFilterClick={k => setActiveFilter(activeFilter === k ? null : k)}
        search={search} onSearchChange={e => setSearch(e.target.value)}
        selected={selected} onSelectChange={setSelected}
        sortKey={sortKey} sortDir={sortDir}
        onSort={k => { if (k === sortKey) setSortDir(sortDir === 'asc' ? 'desc' : 'asc'); else { setSortKey(k); setSortDir('asc'); } }}
        page={page} size={size} total={MEMBERS.length}
        onPage={setPage} onSize={s => { setSize(s); setPage(1); }}
        selectedCountLabel={selected.size > 0 ? `${selected.size} selected` : `Showing ${MEMBERS.length} members`}
      />
    </div>
  );
}

const tabStyle = (active) => ({
  border: 'none', borderRadius: 4, padding: '6px 10px', cursor: 'pointer',
  background: active ? 'var(--primary)' : 'transparent',
  color: active ? '#fff' : 'var(--muted-foreground)',
});

function SettingsScreen() {
  return (
    <div>
      <PageHeader title="Settings"
        subtitle="Manage your location, billing details, and team access." />
      <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: 24 }}>
        <nav style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {['Location', 'Business hours', 'Plans', 'Billing', 'Team', 'Integrations', 'Notifications'].map((t, i) => (
            <a key={t} style={{
              padding: '8px 12px', borderRadius: 6, fontSize: 13, fontWeight: 600,
              color: i === 0 ? 'var(--primary)' : 'var(--muted-foreground)', background: i === 0 ? 'rgba(242,110,34,0.08)' : 'transparent',
              cursor: 'pointer', textDecoration: 'none',
            }}>{t}</a>
          ))}
        </nav>
        <div style={{ background: '#FFFFFF', border: '1px solid var(--border-solid)', borderRadius: 6, padding: 22 }}>
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Location details</div>
          <div style={{ fontSize: 12, color: 'var(--muted-foreground)', marginBottom: 18 }}>
            Shown on receipts, invoices and member welcome emails.
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            <Input label="Business name" full value="Academia Centro" onChange={()=>{}} />
            <Input label="Tax ID (CNPJ)" full value="12.345.678/0001-90" onChange={()=>{}} />
            <Input label="Street address" full value="Av. Paulista, 1000" onChange={()=>{}} />
            <Input label="City" full value="São Paulo" onChange={()=>{}} />
            <Input label="Phone" full icon="phone-call" value="+55 11 91234-5678" onChange={()=>{}} />
            <Input label="Support email" full icon="envelope" value="help@academiacentro.com.br" onChange={()=>{}} />
          </div>
          <hr style={{ border: 'none', borderTop: '1px solid var(--border-solid)', margin: '22px 0' }} />
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Button variant="ghost">Cancel</Button>
            <Button variant="primary">Save</Button>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { Modal, CheckInsScreen, MembersScreen, SettingsScreen });
