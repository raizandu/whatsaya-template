// DataTable.jsx — DxDataGrid-styled (Aya)
const { useState: useDx } = React;

// ---- Header chip with dropdown arrow ----
function FilterChip({ label, count, active, onClick }) {
  return (
    <button onClick={onClick} style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, height: 32, padding: '0 12px',
      border: 0, boxShadow: active ? '0 0 0 1px var(--primary-deep)' : 'var(--shadow-xs)',
      background: active ? 'var(--primary-10)' : 'var(--card)',
      color: active ? 'var(--primary-deep)' : 'var(--foreground)',
      borderRadius: 6, font: '600 12px/1 Open Sans, sans-serif', cursor: 'pointer',
      transition: 'background-color var(--duration-base) var(--ease-hover), box-shadow var(--duration-base) var(--ease-hover)',
    }}>
      {label}
      {count != null && (
        <span style={{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          minWidth: 16, height: 16, padding: '0 5px', borderRadius: 999,
          background: 'var(--primary)', color: 'var(--primary-foreground)', font: '700 10px/1 var(--font-numeric)',
        }}>{count}</span>
      )}
      <i className="fi fi-rr-angle-small-down" style={{ fontSize: 12, lineHeight: 0 }} />
    </button>
  );
}

// ---- Search input ----
function DxSearch({ value, onChange, placeholder = 'Search…' }) {
  const [focus, setFocus] = useDx(false);
  return (
    <div style={{ position: 'relative', height: 32, width: 300 }}>
      <i className="fi fi-rr-search" style={{
        position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)',
        color: 'var(--muted-foreground)', fontSize: 14, lineHeight: 0,
      }} />
      <input value={value || ''} onChange={onChange}
        onFocus={() => setFocus(true)} onBlur={() => setFocus(false)}
        placeholder={placeholder} style={{
        width: '100%', height: '100%',
        border: `1px solid ${focus ? 'var(--ring)' : 'var(--hairline-strong)'}`,
        boxShadow: focus ? '0 0 0 3px var(--primary-20)' : 'none',
        borderRadius: 6, padding: '0 12px 0 34px', background: 'var(--input-bg)',
        color: 'var(--foreground)', font: '400 14px/1 Open Sans, sans-serif', outline: 'none',
        transition: 'border-color var(--duration-base) var(--ease-hover), box-shadow var(--duration-base) var(--ease-hover)',
      }} />
    </div>
  );
}

// ---- Ghost icon button ----
function IconBtn({ icon, title, onClick }) {
  return (
    <button onClick={onClick} title={title} style={{
      width: 32, height: 32, borderRadius: 6, border: 'none', background: 'transparent',
      color: 'var(--foreground-75)', cursor: 'pointer', display: 'inline-flex',
      alignItems: 'center', justifyContent: 'center',
    }}
    onMouseEnter={e => e.currentTarget.style.background = 'var(--muted-solid)'}
    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
      <i className={`fi fi-rr-${icon}`} style={{ fontSize: 16, lineHeight: 0 }} />
    </button>
  );
}

// ---- Selection checkbox ----
function DxCheck({ checked, onChange }) {
  return (
    <input type="checkbox" checked={!!checked} onChange={onChange} style={{
      appearance: 'none', width: 16, height: 16, margin: 0,
      border: `1px solid ${checked ? 'var(--primary-edge)' : 'var(--hairline-strong)'}`,
      borderRadius: 4, cursor: 'pointer', position: 'relative',
      background: checked ? 'var(--primary)' : 'var(--input-bg)', verticalAlign: 'middle',
      backgroundImage: checked ? "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' fill='none'%3E%3Cpath d='M1.5 5.2L3.8 7.5L8.5 2.5' stroke='%23070B0D' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E\")" : 'none',
      backgroundSize: '10px', backgroundPosition: 'center', backgroundRepeat: 'no-repeat',
      transition: 'background-color var(--duration-base) var(--ease-hover), border-color var(--duration-base) var(--ease-hover)',
    }} />
  );
}

// ---- Pager ----
function DxPager({ sizes = [5, 10, 20], size = 10, onSize, page = 1, totalPages = 1, total = 0, onPage }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px',
      borderTop: '1px solid var(--hairline)', background: 'var(--card)' }}>
      <div style={{ display: 'flex', gap: 4 }}>
        {sizes.map(s => (
          <button key={s} onClick={() => onSize && onSize(s)} style={{
            minWidth: 32, height: 32, padding: '0 10px', border: 'none',
            background: s === size ? 'var(--primary-10)' : 'transparent',
            color: s === size ? 'var(--primary-deep)' : 'var(--foreground-75)',
            borderRadius: 6, cursor: 'pointer', font: '600 13px/1 Open Sans, sans-serif',
          }}>{s}</button>
        ))}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ font: '400 12px/20px Open Sans, sans-serif', color: 'var(--muted-foreground)' }}>
          Page {page} of {totalPages} · {total} items
        </span>
        <IconBtn icon="angle-small-left" title="Prev" onClick={() => onPage && onPage(Math.max(1, page - 1))} />
        <input value={page} onChange={e => onPage && onPage(Number(e.target.value) || 1)} style={{
          width: 44, height: 32, textAlign: 'center',
          border: '1px solid var(--hairline-strong)', borderRadius: 6,
          font: '600 13px/1 var(--font-numeric)', color: 'var(--foreground)', background: 'var(--input-bg)', outline: 'none',
        }} />
        <IconBtn icon="angle-small-right" title="Next" onClick={() => onPage && onPage(Math.min(totalPages, page + 1))} />
      </div>
    </div>
  );
}

// ---- DxDataGrid ----
// Props:
//  - columns: [{ key, label, align?, width?, sortable?, render?(row) }]
//  - rows: []
//  - filters: [{ key, label, count? }]
//  - search, onSearchChange
//  - actions: ['columns','refresh','download','plus'] or custom nodes
//  - selectable: bool
//  - page, size, totalPages, total, onPage, onSize
//  - sortKey, sortDir, onSort
//  - selected: Set of row indices; onSelectChange(set)
function DxDataGrid({
  searchPlaceholder = 'Search…',
  columns, rows,
  filters = [], activeFilter, onFilterClick,
  search, onSearchChange,
  actions = ['columns', 'refresh', 'download', 'plus'],
  selectable = true,
  sortKey, sortDir = 'asc', onSort,
  selected, onSelectChange,
  page = 1, size = 10, totalPages, total, onPage, onSize,
  clearLabel = 'Clear', selectedCountLabel,
  onClearFilters,
}) {
  const selSet = selected || new Set();
  const toggleRow = (i) => {
    const next = new Set(selSet);
    next.has(i) ? next.delete(i) : next.add(i);
    onSelectChange && onSelectChange(next);
  };
  const toggleAll = () => {
    if (selSet.size === rows.length) onSelectChange && onSelectChange(new Set());
    else onSelectChange && onSelectChange(new Set(rows.map((_, i) => i)));
  };
  const tp = totalPages != null ? totalPages : Math.max(1, Math.ceil((total || rows.length) / size));

  return (
    <div>
      {/* Toolbar */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 12 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            {filters.map(f => (
              <FilterChip key={f.key} label={f.label} count={f.count}
                active={activeFilter === f.key}
                onClick={() => onFilterClick && onFilterClick(f.key)} />
            ))}
          </div>
          <DxSearch value={search} onChange={onSearchChange} placeholder={searchPlaceholder} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8,
            font: '400 14px/20px Open Sans, sans-serif', color: 'var(--foreground)' }}>
            {selectedCountLabel || `${selSet.size} selected`}
            {selSet.size > 0 && (
              <button onClick={() => onSelectChange && onSelectChange(new Set())} style={{
                display: 'inline-flex', alignItems: 'center', gap: 4, border: 'none', background: 'transparent',
                color: 'var(--foreground-75)', font: '600 12px/1 Open Sans, sans-serif',
                cursor: 'pointer', padding: '4px 6px', borderRadius: 6,
              }}>
                {clearLabel} <i className="fi fi-rr-cross-small" style={{ fontSize: 10, lineHeight: 0 }} />
              </button>
            )}
          </div>
          <div style={{ display: 'flex', gap: 4 }}>
            {actions.map((a, i) =>
              typeof a === 'string'
                ? <IconBtn key={i} icon={a === 'columns' ? 'apps'
                    : a === 'refresh' ? 'refresh'
                    : a === 'download' ? 'download'
                    : a === 'plus' ? 'plus' : a}
                    title={a} />
                : <React.Fragment key={i}>{a}</React.Fragment>
            )}
          </div>
        </div>
      </div>

      {/* Grid */}
      <div style={{
        boxShadow: 'var(--shadow-xs)', borderRadius: 8, overflow: 'hidden', background: 'var(--card)',
      }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              {selectable && (
                <th style={dxTh(40, 'center')}>
                  <DxCheck checked={rows.length > 0 && selSet.size === rows.length}
                    onChange={toggleAll} />
                </th>
              )}
              {columns.map(c => {
                const sorted = sortKey === c.key;
                return (
                  <th key={c.key} onClick={() => c.sortable && onSort && onSort(c.key)}
                    style={{ ...dxTh(c.width, c.align), cursor: c.sortable ? 'pointer' : 'default' }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6,
                      justifyContent: c.align === 'right' ? 'flex-end' : 'flex-start' }}>
                      {c.label}
                      {sorted && (
                        <i className={`fi fi-rr-arrow-${sortDir === 'asc' ? 'down' : 'up'}`}
                          style={{ fontSize: 10, lineHeight: 0, color: 'var(--primary-deep)' }} />
                      )}
                    </span>
                  </th>
                );
              })}
              <th style={dxTh(40, 'center')}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => {
              const isSel = selSet.has(i);
              return (
                <tr key={i} style={{
                  background: isSel ? 'var(--primary-10)' : 'var(--card)',
                  boxShadow: isSel ? 'inset 2px 0 0 0 var(--primary)' : 'none',
                  borderTop: i === 0 ? 'none' : '1px solid var(--border-solid-50)',
                  transition: 'background-color var(--duration-instant) linear',
                }}
                onMouseEnter={e => !isSel && (e.currentTarget.style.background = 'var(--muted-solid)')}
                onMouseLeave={e => !isSel && (e.currentTarget.style.background = 'var(--card)')}>
                  {selectable && (
                    <td style={dxTd('center')}>
                      <DxCheck checked={isSel} onChange={() => toggleRow(i)} />
                    </td>
                  )}
                  {columns.map(c => (
                    <td key={c.key} style={dxTd(c.align)}>
                      {c.render ? c.render(row) : row[c.key]}
                    </td>
                  ))}
                  <td style={dxTd('center')}>
                    <button style={{
                      color: 'var(--muted-foreground)', background: 'transparent', border: 'none', cursor: 'pointer',
                      width: 28, height: 28, borderRadius: 6,
                      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      <i className="fi fi-rr-menu-dots" />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        <DxPager size={size} onSize={onSize} page={page} totalPages={tp}
          total={total != null ? total : rows.length} onPage={onPage} />
      </div>
    </div>
  );
}

function dxTh(width, align) {
  return {
    background: 'var(--muted-solid)', color: 'var(--foreground-75)',
    font: '600 12px/1.4 Open Sans, sans-serif',
    textAlign: align === 'right' ? 'right' : align === 'center' ? 'center' : 'left',
    padding: '10px 16px', borderBottom: '1px solid var(--border-solid)',
    whiteSpace: 'nowrap', userSelect: 'none', width,
  };
}
function dxTd(align) {
  return {
    padding: '10px 16px', font: '400 14px/1.45 Open Sans, sans-serif',
    color: 'var(--foreground)', verticalAlign: 'middle',
    textAlign: align === 'right' ? 'right' : align === 'center' ? 'center' : 'left',
  };
}

// ---- Avatar helper (for column renderers) ----
function DxAvatar({ name, tone = 'purple' }) {
  const tones = {
    purple:  { bg: 'var(--muted-solid)', fg: 'var(--foreground)' },
    blue:    { bg: 'var(--success-fade)', fg: 'var(--success-foreground)' },
    pink:    { bg: 'var(--danger-fade)', fg: 'var(--danger-foreground)' },
    emerald: { bg: 'var(--success-fade)', fg: 'var(--success-foreground)' },
    orange:  { bg: 'var(--danger-fade)', fg: 'var(--danger-foreground)' },
    lime:    { bg: 'var(--success-fade)', fg: 'var(--success-foreground)' },
  };
  const t = tones[tone] || tones.purple;
  return (
    <span style={{ width: 28, height: 28, borderRadius: 999, background: t.bg, color: t.fg,
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      font: '700 11px/1 Open Sans, sans-serif' }}>
      {name.split(' ').map(w => w[0]).slice(0, 2).join('')}
    </span>
  );
}

// Legacy DataTable — kept for back-compat, wraps DxDataGrid
function DataTable({ rows }) {
  const [selected, setSelected] = useDx(new Set());
  const [search, setSearch] = useDx('');
  const [activeFilter, setActiveFilter] = useDx(null);
  const [page, setPage] = useDx(1);
  const [size, setSize] = useDx(10);

  const columns = [
    { key: 'name', label: 'Member', sortable: true,
      render: r => (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
          <DxAvatar name={r.name} tone="purple" />
          <span style={{ fontWeight: 600 }}>{r.name}</span>
        </span>
      ) },
    { key: 'plan', label: 'Plan', sortable: true },
    { key: 'at',   label: 'Time', sortable: true,
      render: r => <span style={{ fontFamily: 'Geist, ui-sans-serif', color: 'var(--muted-foreground)' }}>{r.at}</span> },
    { key: 'status', label: 'Status',
      render: r => <Badge variant={r.status}>{r.reason}</Badge> },
  ];

  return (
    <DxDataGrid
      columns={columns} rows={rows}
      filters={[
        { key: 'status', label: 'Status', count: activeFilter === 'status' ? 1 : null },
        { key: 'plan',   label: 'Plan' },
        { key: 'period', label: 'Period' },
      ]}
      activeFilter={activeFilter}
      onFilterClick={k => setActiveFilter(activeFilter === k ? null : k)}
      search={search} onSearchChange={e => setSearch(e.target.value)}
      selected={selected} onSelectChange={setSelected}
      page={page} size={size} total={1284}
      onPage={setPage} onSize={s => { setSize(s); setPage(1); }}
      selectedCountLabel={selected.size > 0 ? `${selected.size} selected` : `Showing ${rows.length} of 1,284`}
    />
  );
}

Object.assign(window, { DataTable, DxDataGrid, DxAvatar, FilterChip, DxSearch, DxPager, DxCheck });
