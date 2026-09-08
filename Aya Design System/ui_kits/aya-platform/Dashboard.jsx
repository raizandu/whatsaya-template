// Dashboard.jsx — KPI tiles + recent check-ins (faithful to Figma account-card spec)
//
// Card system (from /account-card in Figma):
//   border-radius: 8 · border: 1px solid var(--border-solid) (dark: var(--muted-foreground)) · padding: 16 · gap: 16
//   header  : row, justify-between, align-center
//             — title:  Open Sans 700  14/24
//             — accent: Open Sans 700  12/20  (success-green / danger-red)
//   eyebrow-label (mini stat):
//             — label:  Open Sans 700  8/100%  letter-spacing 0.16em  uppercase  var(--muted-foreground)
//             — value:  Open Sans 400  12/20   #070B0D
//   primary number body (KPI):
//             — Geist 700  ~36/100%   #070B0D

const { useMemo } = React;

/* ── primitives ─────────────────────────────────────────────── */

const cardChrome = {
  background: '#FFFFFF',
  border: '1px solid var(--border-solid)',
  borderRadius: 8,
  padding: 16,
  display: 'flex',
  flexDirection: 'column',
  gap: 16,
  minWidth: 0,
};

const cardHeader = {
  display: 'flex',
  flexDirection: 'row',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 10,
};

const cardTitle = {
  fontFamily: "'Open Sans', sans-serif",
  fontWeight: 700,
  fontSize: 14,
  lineHeight: '24px',
  color: 'var(--foreground)',
};

const cardAccent = (kind = 'success') => ({
  fontFamily: "'Open Sans', sans-serif",
  fontWeight: 700,
  fontSize: 12,
  lineHeight: '20px',
  color: kind === 'success' ? 'var(--success)'
       : kind === 'danger'  ? 'var(--primary)'
       : kind === 'warning' ? 'var(--warning)'
       :                       'var(--muted-foreground)',
});

const eyebrow = {
  fontFamily: "'Open Sans', sans-serif",
  fontWeight: 700,
  fontSize: 8,
  lineHeight: '100%',
  letterSpacing: '0.16em',
  textTransform: 'uppercase',
  color: 'var(--muted-foreground)',
};

const eyebrowValue = {
  fontFamily: "'Open Sans', sans-serif",
  fontWeight: 400,
  fontSize: 12,
  lineHeight: '20px',
  color: 'var(--foreground)',
  marginTop: 4,
};

function Label({ label, value }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      <span style={eyebrow}>{label}</span>
      <span style={eyebrowValue}>{value}</span>
    </div>
  );
}

/* ── KPI tile ───────────────────────────────────────────────── */

function KpiTile({ title, value, unit, delta, deltaKind = 'success', labels = [] }) {
  return (
    <div style={cardChrome}>
      <div style={cardHeader}>
        <span style={cardTitle}>{title}</span>
        {delta && (
          <span style={cardAccent(deltaKind)}>
            {deltaKind === 'success' ? '▲' : deltaKind === 'danger' ? '▼' : '•'} {delta}
          </span>
        )}
      </div>

      <div style={{
        fontFamily: 'Geist, ui-sans-serif',
        fontWeight: 700,
        fontSize: 36,
        lineHeight: 1,
        letterSpacing: '-.02em',
        color: 'var(--foreground)',
        display: 'flex',
        alignItems: 'baseline',
        gap: 6,
      }}>
        {unit && (
          <span style={{ fontSize: 14, fontWeight: 400, color: 'var(--muted-foreground)' }}>{unit}</span>
        )}
        {value}
      </div>

      {labels.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'row', gap: 24, marginTop: 'auto' }}>
          {labels.map((l, i) => <Label key={i} {...l} />)}
        </div>
      )}
    </div>
  );
}

/* ── recent check-ins data ──────────────────────────────────── */

const RECENT = [
  { name: 'Lucas Almeida',  plan: 'Annual',  at: '10:42', status: 'success', reason: 'Validated' },
  { name: 'Beatriz Nunes',  plan: 'Monthly', at: '10:39', status: 'success', reason: 'Validated' },
  { name: 'Paulo Ferreira', plan: 'Daily',   at: '10:36', status: 'warning', reason: 'Pending' },
  { name: 'Julia Santos',   plan: 'Annual',  at: '10:31', status: 'success', reason: 'Validated' },
  { name: 'Rafael Dias',    plan: 'Monthly', at: '10:28', status: 'danger',  reason: 'No subscription' },
  { name: 'Carla Moraes',   plan: 'Student', at: '10:24', status: 'success', reason: 'Validated' },
  { name: 'Diego Lopes',    plan: 'Monthly', at: '10:19', status: 'success', reason: 'Validated' },
];

/* ── Dashboard ──────────────────────────────────────────────── */

function Dashboard() {
  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle="Overview of today's activity across your locations."
        actions={[
          <Button key="1" variant="outline" icon="calendar">Last 7 days</Button>,
          <Button key="2" variant="primary" icon="plus">New check-in</Button>,
        ]}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 20 }}>
        <KpiTile
          title="Check-ins today"
          value="1,284"
          delta="12%"
          deltaKind="success"
          labels={[
            { label: 'Yesterday', value: '1,147' },
            { label: '7-d avg',   value: '1,165' },
            { label: 'Peak hour', value: '18:00' },
          ]}
        />
        <KpiTile
          title="Active members"
          value="842"
          delta="3%"
          deltaKind="danger"
          labels={[
            { label: 'New / wk', value: '+38' },
            { label: 'Churned',  value: '−12' },
            { label: 'Trial',    value: '64' },
          ]}
        />
        <KpiTile
          title="Revenue MTD"
          value="48.920"
          unit="R$"
          delta="6.2%"
          deltaKind="success"
          labels={[
            { label: 'Paid',    value: 'R$ 41.220' },
            { label: 'Pending', value: 'R$ 6.180' },
            { label: 'Overdue', value: 'R$ 1.520' },
          ]}
        />
        <KpiTile
          title="Expiring soon"
          value="37"
          delta="9 vs last wk"
          deltaKind="warning"
          labels={[
            { label: 'This week', value: '14' },
            { label: 'Next 30d',  value: '37' },
            { label: 'Auto-ren.', value: '21' },
          ]}
        />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 14 }}>
        {/* Recent check-ins — chrome matches Figma card spec */}
        <div style={{ ...cardChrome, padding: 0, gap: 0, overflow: 'hidden' }}>
          <div style={{ ...cardHeader, padding: 16 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span style={cardTitle}>Recent check-ins</span>
              <span style={{ fontSize: 12, lineHeight: '20px', color: 'var(--muted-foreground)', fontWeight: 400 }}>
                Last 60 minutes · Academia Centro
              </span>
            </div>
            <Button variant="ghost" size="sm" icon="refresh">Refresh</Button>
          </div>
          <DataTable rows={RECENT} />
        </div>

        {/* Capacity — full account-card translation */}
        <div style={cardChrome}>
          <div style={cardHeader}>
            <span style={cardTitle}>Capacity</span>
            <span style={cardAccent('success')}>60% full</span>
          </div>

          <div style={{
            display: 'flex',
            alignItems: 'baseline',
            gap: 8,
            fontFamily: 'Geist, ui-sans-serif',
          }}>
            <span style={{ fontWeight: 700, fontSize: 48, lineHeight: 1, letterSpacing: '-.02em', color: 'var(--foreground)' }}>72</span>
            <span style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>/ 120 inside</span>
          </div>

          <div style={{ height: 8, borderRadius: 999, background: 'var(--muted-solid)', overflow: 'hidden' }}>
            <div style={{ width: '60%', height: '100%', background: 'var(--primary)' }} />
          </div>

          <div style={{ display: 'flex', flexDirection: 'row', gap: 24 }}>
            <Label label="Updated"   value="12s ago" />
            <Label label="Peak hour" value="18:00 – 19:00" />
            <Label label="Trend"     value="Above avg" />
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { Dashboard, KpiTile });
