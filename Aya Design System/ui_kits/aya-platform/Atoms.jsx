// Atoms.jsx — Button, Input, Select, Badge, Spinner
// Os átomos usam classes injetadas uma vez (KIT_CSS) em vez de style inline:
// hover, active, focus-visible e disabled são pseudo-classes reais e as receitas
// são as mesmas dos previews (buttons.html, inputs.html, select.html).

const KIT_CSS = `
.aya-btn{
  --btn-bg:var(--card);--btn-fg:var(--foreground);--btn-shadow:var(--shadow-xs);--btn-ring:0 0 #0000;
  display:inline-flex;align-items:center;justify-content:center;gap:6px;
  height:32px;padding:0 12px;font:600 14px/20px var(--font-sans);
  border:0;border-radius:var(--radius);background:var(--btn-bg);color:var(--btn-fg);
  box-shadow:var(--btn-ring),var(--btn-shadow);cursor:pointer;user-select:none;white-space:nowrap;text-decoration:none;
  transition:background-color var(--duration-base) var(--ease-hover),box-shadow var(--duration-base) var(--ease-hover),
    color var(--duration-base) var(--ease-hover),opacity var(--duration-base) var(--ease-hover),transform var(--duration-instant) var(--ease-hover);
}
.aya-btn i{font-size:14px;line-height:1;display:inline-flex;}
.aya-btn[data-size="lg"]{height:40px;padding:0 16px;}
.aya-btn[data-size="sm"]{height:24px;padding:0 8px;font-size:12px;line-height:16px;gap:4px;}
.aya-btn[data-size="sm"] i{font-size:12px;}
.aya-btn[data-full]{width:100%;}
.aya-btn[data-icon-only]{width:32px;padding:0;}
.aya-btn[data-icon-only][data-size="lg"]{width:40px;}
.aya-btn[data-icon-only][data-size="sm"]{width:24px;}
.aya-btn:active{transform:translateY(1px);}
.aya-btn:focus-visible{outline:none;--btn-ring:var(--focus-ring);}
.aya-btn:disabled{opacity:.5;cursor:not-allowed;transform:none;--btn-shadow:var(--shadow-hairline);}
.aya-btn[data-loading]{pointer-events:none;opacity:.85;}

.aya-btn[data-variant="primary"]{--btn-bg:var(--primary);--btn-fg:var(--primary-foreground);
  --btn-shadow:var(--inset-highlight),inset 0 -1px 0 var(--primary-edge),0 1px 2px var(--primary-30),0 1px 1px hsl(var(--shadow-tint) / .08);}
.aya-btn[data-variant="primary"]:hover{--btn-bg:var(--primary-hover);
  --btn-shadow:var(--inset-highlight),inset 0 -1px 0 var(--primary-edge),0 2px 6px -1px var(--primary-30),0 1px 2px hsl(var(--shadow-tint) / .08);}
.aya-btn[data-variant="primary"]:active{--btn-bg:var(--primary-active);--btn-shadow:inset 0 -1px 0 var(--primary-edge),0 0 0 1px var(--primary-20);}

.aya-btn[data-variant="secondary"]{--btn-bg:var(--card);--btn-shadow:var(--shadow-xs);}
.aya-btn[data-variant="secondary"]:hover{--btn-shadow:var(--shadow-sm);}
.aya-btn[data-variant="secondary"]:active{--btn-bg:var(--secondary);--btn-shadow:var(--shadow-inset);}

.aya-btn[data-variant="outline"]{--btn-bg:transparent;--btn-shadow:0 0 0 1px var(--border-solid);}
.aya-btn[data-variant="outline"]:hover{--btn-bg:var(--accent-transparent);--btn-shadow:0 0 0 1px var(--muted-foreground);}
.aya-btn[data-variant="outline"]:active{--btn-shadow:0 0 0 1px var(--muted-foreground),var(--shadow-inset);}

.aya-btn[data-variant="ghost"]{--btn-bg:transparent;--btn-shadow:none;}
.aya-btn[data-variant="ghost"]:hover{--btn-bg:var(--accent-transparent);}
.aya-btn[data-variant="ghost"]:active{--btn-bg:var(--muted-transparent);--btn-shadow:var(--shadow-inset);}

.aya-btn[data-variant="link"]{--btn-bg:transparent;--btn-fg:var(--link);--btn-shadow:none;padding:0 4px;}
.aya-btn[data-variant="link"]:hover{text-decoration:underline;text-underline-offset:3px;}
.aya-btn[data-variant="link"]:active{transform:none;--btn-fg:var(--foreground);}
.aya-btn[data-variant="link"]:disabled{--btn-shadow:none;}

.aya-btn[data-variant="destructive"]{--btn-bg:var(--destructive);--btn-fg:var(--destructive-foreground);
  --btn-shadow:inset 0 1px 0 #FFFFFF24,inset 0 -1px 0 var(--deep-edge),0 1px 2px hsl(var(--shadow-tint) / .16),0 1px 1px hsl(var(--shadow-tint) / .08);}
.aya-btn[data-variant="destructive"]:hover{--btn-bg:var(--deep-hover);
  --btn-shadow:inset 0 1px 0 #FFFFFF24,inset 0 -1px 0 var(--deep-edge),0 2px 6px -1px hsl(var(--shadow-tint) / .22);}
.aya-btn[data-variant="destructive"]:active{--btn-bg:var(--deep-edge);--btn-shadow:inset 0 -1px 0 var(--deep-edge),0 0 0 1px hsl(var(--shadow-tint) / .16);}

.aya-btn[data-variant="whatsapp"]{--btn-bg:var(--success);--btn-fg:#070B0D;
  --btn-shadow:var(--inset-highlight),inset 0 -1px 0 var(--green-edge),0 1px 2px #4CDE5940,0 1px 1px hsl(var(--shadow-tint) / .08);}
.aya-btn[data-variant="whatsapp"]:hover{--btn-bg:var(--green-hover);
  --btn-shadow:var(--inset-highlight),inset 0 -1px 0 var(--green-edge),0 2px 6px -1px #4CDE5959,0 1px 2px hsl(var(--shadow-tint) / .08);}
.aya-btn[data-variant="whatsapp"]:active{--btn-bg:var(--green-active);--btn-shadow:inset 0 -1px 0 var(--green-edge),0 0 0 1px #4CDE5933;}

.aya-spinner{width:14px;height:14px;flex:none;border-radius:var(--radius-pill);border:2px solid currentColor;border-right-color:transparent;animation:aya-spin .8s linear infinite;}
@keyframes aya-spin{to{transform:rotate(360deg);}}

.aya-field{display:flex;flex-direction:column;gap:6px;}
.aya-field[data-full]{width:100%;}
.aya-field>span.aya-label{font:600 13px/18px var(--font-sans);color:var(--label);}
.aya-field>span.aya-hint{font:400 12px/16px var(--font-sans);color:var(--muted-foreground);}
.aya-field>span.aya-error{display:flex;align-items:center;gap:4px;font:400 12px/16px var(--font-sans);color:var(--destructive);}
.aya-input{
  --b:var(--hairline-strong);--ring:0 0 #0000;
  height:32px;display:flex;align-items:center;gap:8px;box-sizing:border-box;
  background:var(--input-bg);color:var(--foreground);border:1px solid var(--b);border-radius:var(--radius);box-shadow:var(--ring);
  padding:0 10px;cursor:text;
  transition:border-color var(--duration-base) var(--ease-hover),box-shadow var(--duration-base) var(--ease-hover),background-color var(--duration-base) var(--ease-hover);
}
.aya-input input{flex:1;min-width:0;border:0;outline:0;background:transparent;font:400 14px/24px var(--font-sans);color:inherit;padding:0;}
.aya-input input::placeholder{color:var(--muted-foreground);}
.aya-input i{font-size:14px;line-height:1;display:inline-flex;color:var(--muted-foreground);flex:none;transition:color var(--duration-base) var(--ease-hover);}
.aya-input:hover{--b:var(--muted-foreground);}
.aya-input:focus-within{--b:var(--ring);--ring:0 0 0 3px var(--primary-20);}
.aya-input:focus-within i{color:var(--foreground);}
.aya-input[data-error]{--b:var(--destructive);}
.aya-input[data-error]:focus-within{--ring:0 0 0 3px var(--primary-10);}
.aya-input:has(input:disabled){opacity:.5;background:var(--muted-solid);cursor:not-allowed;--b:var(--border-solid);}

.aya-select{position:relative;}
.aya-select select{
  --b:var(--hairline-strong);--ring:0 0 #0000;
  width:100%;height:32px;appearance:none;-webkit-appearance:none;box-sizing:border-box;
  padding:0 32px 0 10px;font:600 14px/20px var(--font-sans);color:var(--foreground);
  background:var(--input-bg);border:1px solid var(--b);border-radius:var(--radius);box-shadow:var(--ring);cursor:pointer;
  transition:border-color var(--duration-base) var(--ease-hover),box-shadow var(--duration-base) var(--ease-hover);
}
.aya-select select:hover{--b:var(--muted-foreground);}
.aya-select select:focus-visible{outline:none;--b:var(--ring);--ring:0 0 0 3px var(--primary-20);}
.aya-select select:disabled{opacity:.5;cursor:not-allowed;background:var(--muted-solid);--b:var(--border-solid);}
.aya-select i{position:absolute;right:10px;top:50%;transform:translateY(-50%);font-size:14px;line-height:1;display:inline-flex;color:var(--muted-foreground);pointer-events:none;}

.aya-badge{display:inline-flex;align-items:center;gap:6px;padding:2px 8px;border-radius:var(--radius-sm);font:600 12px/16px var(--font-sans);white-space:nowrap;}
.aya-badge i{font-size:11px;line-height:1;display:inline-flex;}
.aya-badge .aya-dot{width:6px;height:6px;border-radius:var(--radius-pill);}

@keyframes aya-fade{from{opacity:0;}}
@keyframes aya-slide-up{from{opacity:0;transform:translateY(8px) scale(.98);}}
@media (prefers-reduced-motion: reduce){.aya-btn:active{transform:none;}}
`;

(function injectKitStyles() {
  if (typeof document === 'undefined' || document.getElementById('aya-kit-styles')) return;
  const style = document.createElement('style');
  style.id = 'aya-kit-styles';
  style.textContent = KIT_CSS;
  document.head.appendChild(style);
})();

// Aliases do contrato antigo, para as telas existentes não quebrarem.
const BUTTON_VARIANT_ALIAS = { neutral: 'secondary', danger: 'destructive' };

function Spinner({ size = 14 }) {
  return <span className="aya-spinner" style={size !== 14 ? { width: size, height: size } : undefined} aria-hidden="true" />;
}

function Button({ variant = 'primary', size = 'md', icon, children, onClick, disabled, full, type = 'button', loading, title }) {
  const v = BUTTON_VARIANT_ALIAS[variant] || variant;
  const iconOnly = icon && !children;
  return (
    <button type={type} className="aya-btn" data-variant={v} data-size={size}
      data-full={full ? '' : undefined} data-icon-only={iconOnly ? '' : undefined} data-loading={loading ? '' : undefined}
      disabled={disabled} onClick={onClick} title={title} aria-busy={loading || undefined}>
      {loading ? <Spinner /> : icon && <i className={`fi fi-rr-${icon}`} aria-hidden="true" />}
      {children}
    </button>
  );
}

function Input({ icon, value, onChange, placeholder, type = 'text', error, full, label, hint, disabled }) {
  return (
    <label className="aya-field" data-full={full ? '' : undefined}>
      {label && <span className="aya-label">{label}</span>}
      <div className="aya-input" data-error={error ? '' : undefined}>
        {icon && <i className={`fi fi-rr-${icon}`} aria-hidden="true" />}
        <input type={type} value={value} onChange={onChange} placeholder={placeholder} disabled={disabled} aria-invalid={error ? true : undefined} />
        {error && <i className="fi fi-rr-exclamation" style={{ color: 'var(--destructive)' }} aria-hidden="true" />}
      </div>
      {error ? <span className="aya-error"><i className="fi fi-rr-exclamation" aria-hidden="true" />{error}</span>
             : hint && <span className="aya-hint">{hint}</span>}
    </label>
  );
}

function Select({ label, value, onChange, options, full, hint, disabled }) {
  return (
    <label className="aya-field" data-full={full ? '' : undefined}>
      {label && <span className="aya-label">{label}</span>}
      <div className="aya-select">
        <select value={value} onChange={onChange} disabled={disabled}>
          {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <i className="fi fi-rr-angle-small-down" aria-hidden="true" />
      </div>
      {hint && <span className="aya-hint">{hint}</span>}
    </label>
  );
}

// Badges seguem o par *-fade + *-foreground; 'info' e 'purple' são aliases do contrato antigo.
const STATUS = {
  neutral:  { bg: 'var(--muted-transparent)', fg: 'var(--foreground)', dot: 'var(--muted-foreground)' },
  success:  { bg: 'var(--success-fade)', fg: 'var(--success-foreground)', dot: 'var(--success)' },
  warning:  { bg: 'var(--warning-fade)', fg: 'var(--warning-foreground)', dot: 'var(--warning)' },
  danger:   { bg: 'var(--danger-fade)', fg: 'var(--danger-foreground)', dot: 'var(--destructive)' },
  whatsapp: { bg: 'var(--success-fade)', fg: 'var(--success-foreground)', dot: 'var(--success)' },
};
STATUS.info = STATUS.success;
STATUS.purple = STATUS.neutral;

function Badge({ variant = 'neutral', icon, dot = true, children }) {
  const c = STATUS[variant] || STATUS.neutral;
  return (
    <span className="aya-badge" style={{ background: c.bg, color: c.fg }}>
      {icon ? <i className={`fi fi-rr-${icon}`} aria-hidden="true" /> :
       dot && <span className="aya-dot" style={{ background: c.dot }} />}
      {children}
    </span>
  );
}

Object.assign(window, { Button, Input, Select, Badge, Spinner, STATUS });
