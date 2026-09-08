// Atoms.jsx — Button, Input, Select, Badge, Spinner
const { useState: useAtomState } = React;

function Button({ variant = 'primary', size = 'md', icon, children, onClick, disabled, full, type = 'button' }) {
  const base = {
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6,
    fontFamily: 'inherit', fontWeight: 600, borderRadius: 6, cursor: disabled ? 'not-allowed' : 'pointer',
    border: '1px solid transparent', transition: 'opacity .15s, background .15s',
    opacity: disabled ? 0.5 : 1, width: full ? '100%' : undefined, whiteSpace: 'nowrap',
  };
  const sizes = {
    md: { height: 32, padding: '0 12px', fontSize: 13 },
    sm: { height: 24, padding: '0 9px', fontSize: 12 },
    lg: { height: 40, padding: '0 16px', fontSize: 14 },
  };
  const variants = {
    primary: { background: 'var(--primary)', color: 'var(--primary-foreground)', borderColor: 'var(--primary)' },
    outline: { background: 'transparent', color: 'var(--primary)', borderColor: 'var(--primary)' },
    ghost:   { background: 'transparent', color: 'var(--foreground)' },
    danger:  { background: 'var(--danger)', color: 'var(--primary-foreground)', borderColor: 'var(--danger)' },
    neutral: { background: 'var(--muted-solid)', color: 'var(--foreground)', borderColor: 'var(--border-solid)' },
  };
  const style = { ...base, ...sizes[size], ...variants[variant] };
  return (
    <button type={type} style={style} disabled={disabled} onClick={onClick}
      onMouseOver={e => !disabled && (e.currentTarget.style.opacity = '0.9')}
      onMouseOut={e => !disabled && (e.currentTarget.style.opacity = '1')}>
      {icon && <i className={`fi fi-rr-${icon}`} style={{ fontSize: 13, lineHeight: 0 }} />}
      {children}
    </button>
  );
}

function Input({ icon, value, onChange, placeholder, type = 'text', error, full, label, hint }) {
  const [focus, setFocus] = useAtomState(false);
  const wrap = {
    display: 'flex', alignItems: 'center', gap: 8,
    height: 36, padding: '0 12px',
    border: `1px solid ${error ? 'var(--danger)' : focus ? 'var(--ring)' : 'var(--border-solid)'}`,
    boxShadow: focus ? '0 0 0 3px var(--primary-20)' : 'none',
    borderRadius: 4, background: 'var(--card)', fontSize: 13, width: full ? '100%' : undefined,
  };
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 6, width: full ? '100%' : undefined }}>
      {label && <span style={{ fontSize: 11, fontWeight: 600, color: 'rgba(7,11,13,.75)' }}>{label}</span>}
      <div style={wrap}>
        {icon && <i className={`fi fi-rr-${icon}`} style={{ color: 'var(--muted-foreground)', fontSize: 14 }} />}
        <input type={type} value={value} onChange={onChange} placeholder={placeholder}
          onFocus={() => setFocus(true)} onBlur={() => setFocus(false)}
          style={{ flex: 1, border: 'none', outline: 'none', background: 'transparent', fontSize: 13, fontFamily: 'inherit', color: 'var(--foreground)' }} />
      </div>
      {error ? <span style={{ fontSize: 10, color: 'var(--danger)' }}>{error}</span>
             : hint && <span style={{ fontSize: 10, color: 'var(--muted-foreground)' }}>{hint}</span>}
    </label>
  );
}

function Select({ label, value, onChange, options, full }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 6, width: full ? '100%' : undefined }}>
      {label && <span style={{ fontSize: 11, fontWeight: 600, color: 'rgba(7,11,13,.75)' }}>{label}</span>}
      <div style={{ position: 'relative' }}>
        <select value={value} onChange={onChange}
          style={{ width: '100%', appearance: 'none', WebkitAppearance: 'none',
            height: 36, padding: '0 32px 0 12px', border: '1px solid var(--border-solid)',
            borderRadius: 4, background: 'var(--card)', fontSize: 13, fontFamily: 'inherit', color: 'var(--foreground)' }}>
          {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <i className="fi fi-rr-angle-small-down" style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--muted-foreground)', pointerEvents: 'none' }} />
      </div>
    </label>
  );
}

const STATUS = {
  success: { bg: 'var(--success-fade)', fg: 'var(--success-foreground)', dot: 'var(--success)', bd: 'var(--success)' },
  warning: { bg: 'var(--warning-fade)', fg: 'var(--warning-foreground)', dot: 'var(--warning)', bd: 'var(--warning)' },
  danger:  { bg: 'var(--danger-fade)', fg: 'var(--danger-foreground)', dot: 'var(--danger)', bd: 'var(--danger)' },
  info:    { bg: 'var(--success-fade)', fg: 'var(--success-foreground)', dot: 'var(--success)', bd: 'var(--success)' },
  neutral: { bg: 'var(--muted-solid)', fg: 'var(--foreground)', dot: 'var(--muted-foreground)', bd: 'var(--border-solid)' },
  purple:  { bg: 'var(--muted-solid)', fg: 'var(--foreground)', dot: 'var(--foreground)', bd: 'var(--border-solid)' },
};

function Badge({ variant = 'neutral', icon, dot = true, children }) {
  const c = STATUS[variant];
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '2px 9px', borderRadius: 8, background: c.bg, color: c.fg,
      border: `1px solid ${c.bd}`,
      fontSize: 11, fontWeight: 700, whiteSpace: 'nowrap' }}>
      {icon ? <i className={`fi fi-rr-${icon}`} style={{ fontSize: 10 }} /> :
       dot && <span style={{ width: 6, height: 6, borderRadius: 999, background: c.dot }} />}
      {children}
    </span>
  );
}

function Spinner({ size = 16, color = '#fff' }) {
  return (
    <span style={{ display: 'inline-block', width: size, height: size,
      border: `2px solid ${color}33`, borderTopColor: color,
      borderRadius: '50%', animation: 'spin .7s linear infinite' }} />
  );
}

Object.assign(window, { Button, Input, Select, Badge, Spinner, STATUS });
