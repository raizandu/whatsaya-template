// Shell.jsx — Navbar (top header) + Sidebar (secondary menu) + Shortcuts rail
// Based on libs/shared/components/navbar/shell and ui/sidebar

function Navbar({ breadcrumbs = [], onToggleSidebar }) {
  return (
    <header style={{
      position: 'relative', height: 48, background: 'var(--header)',
      borderBottom: '1px solid rgba(255,255,255,0.06)',
      display: 'flex', alignItems: 'center', padding: '4px 32px',
      color: 'var(--header-foreground)', fontFamily: 'var(--font-sans)',
      flexShrink: 0, zIndex: 99,
    }}>
      {/* left: sidebar toggle + logo + breadcrumbs */}
      <div style={{ display: 'flex', alignItems: 'center', height: '100%' }}>
        <button onClick={onToggleSidebar} style={{
          background: 'transparent', border: 'none', color: '#fff', cursor: 'pointer',
          width: 32, height: 32, display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 18,
        }}>
          <i className="fi fi-rr-menu-burger" style={{ lineHeight: 0 }} />
        </button>
        <a href="#" style={{ display: 'flex', alignItems: 'center', gap: 6, marginRight: 16, marginLeft: 6, textDecoration: 'none' }}>
          <img src="../../assets/logos/logo-aya-icon.svg" alt="Aya" style={{ height: 22, filter: 'brightness(0) invert(1)' }}/>
          <img src="../../assets/logos/logo-aya-text.svg" alt="" style={{ height: 14, filter: 'brightness(0) invert(1)' }}/>
        </a>
        <section style={{ display: 'flex', alignItems: 'center', gap: 8, marginRight: 16 }}>
          {breadcrumbs.map((b, i) => {
            const last = i === breadcrumbs.length - 1;
            return (
              <React.Fragment key={i}>
                <div style={{ display: 'flex', alignItems: 'center', height: 48, paddingTop: 2,
                  borderBottom: last ? '2px solid #fff' : '2px solid transparent' }}>
                  <button style={{
                    background: 'transparent', border: 'none', cursor: 'pointer',
                    color: last ? '#fff' : 'rgba(255,255,255,0.75)',
                    fontWeight: last ? 700 : 500, fontFamily: 'inherit',
                    fontSize: 13, padding: '0 10px', height: 32, borderRadius: 6,
                    marginBottom: last ? -2 : 0,
                  }}>{b}</button>
                </div>
                {!last && <i className="fi fi-rr-angle-small-right" style={{ fontSize: 14, color: 'var(--muted-foreground)', lineHeight: 0 }} />}
              </React.Fragment>
            );
          })}
        </section>
      </div>

      {/* center: elastic search */}
      <div style={{ marginRight: 'auto', flex: 1, height: 48, display: 'flex', justifyContent: 'center', alignItems: 'center', paddingRight: 8 }}>
        <div style={{
          width: '100%', maxWidth: 560, height: 32, borderRadius: 6,
          background: 'rgba(255,255,255,0.08)',
          border: '1px solid rgba(255,255,255,0.08)',
          display: 'flex', alignItems: 'center', gap: 8, padding: '0 12px',
          color: 'rgba(255,255,255,0.7)', fontSize: 13,
        }}>
          <i className="fi fi-rr-search" style={{ fontSize: 13, lineHeight: 0 }}/>
          <span>Buscar pessoas, contratos, faturas…</span>
          <kbd style={{ marginLeft: 'auto', fontSize: 10, padding: '2px 6px',
            background: 'rgba(255,255,255,0.08)', borderRadius: 4,
            fontFamily: 'Geist, ui-sans-serif' }}>Ctrl K</kbd>
        </div>
      </div>

      {/* right: icons + profile */}
      <div style={{ display: 'flex', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <IconBtn icon="marker" title="Access points"/>
          <IconBtn icon="messages" title="Chat" dot/>
          <IconBtn icon="bell" title="Notifications"/>
          <IconBtn icon="settings" title="Settings"/>
        </div>
        <div style={{ marginLeft: 16 }}>
          <div style={{
            width: 32, height: 32, borderRadius: 999, background: 'var(--primary)',
            color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontWeight: 700, fontSize: 12, cursor: 'pointer',
          }}>LA</div>
        </div>
      </div>
    </header>
  );
}

function IconBtn({ icon, dot }) {
  return (
    <button style={{
      position: 'relative', width: 32, height: 32, borderRadius: 6,
      background: 'transparent', border: 'none', cursor: 'pointer',
      color: 'rgba(255,255,255,0.95)', display: 'flex',
      alignItems: 'center', justifyContent: 'center', fontSize: 18,
    }}>
      <i className={`fi fi-rr-${icon}`} style={{ lineHeight: 0 }}/>
      {dot && <span style={{
        position: 'absolute', right: 4, top: 4, width: 10, height: 10,
        borderRadius: 999, background: 'var(--success)', border: '2px solid var(--header)',
      }}/>}
    </button>
  );
}

// lib-sidebar — faithful port of libs/shared/components/ui/sidebar.
// Rows are 36px with py-[6px]; active state: 4px primary left border + bg-accent-solid.
// Header row ("Menu") is 40px, transparent 4px left border, label-semibold + muted fg.
function SecondarySidebar({ items, active, onNavigate, title = 'Menu', hideMenu = false, border = true }) {
  return (
    <aside style={{
      width: 240, background: 'var(--background)',
      borderRight: '1px solid var(--border-solid)',
      display: 'flex', flexDirection: 'column',
      fontFamily: 'var(--font-sans)', flexShrink: 0,
    }}>
      <ul style={{
        listStyle: 'none', padding: 0, margin: 0,
        width: '100%', height: '100%',
        overflowY: 'auto', overflowX: 'hidden',
        display: hideMenu ? 'none' : 'flex', flexDirection: 'column',
        alignItems: 'flex-start', justifyContent: 'flex-start',
      }}>
        {/* "Menu" header — matches the first <div> in sidebar.component.html */}
        <div style={{
          boxSizing: 'border-box',
          borderLeft: '4px solid transparent',
          padding: '8px 6px', height: 40, lineHeight: '24px',
          display: 'flex', alignItems: 'center', justifyContent: 'flex-start',
          font: '600 14px/1.4 var(--font-sans)',
          color: 'var(--muted-foreground)',
        }}>
          <span style={{ padding: '0 7px' }}>{title}</span>
        </div>

        {/* items — faithful port of sidebar-link.component.html */}
        {items.map(it => {
          const on = it.key === active;
          const activeBordered = border && on;
          return (
            <SidebarLink
              key={it.key}
              icon={it.icon}
              text={it.label}
              tag={it.tag}
              isActive={on}
              activeBordered={activeBordered}
              onClick={() => onNavigate(it.key)}
            />
          );
        })}
      </ul>
    </aside>
  );
}

function SidebarLink({ icon, text, tag, isActive, activeBordered, onClick }) {
  const [hover, setHover] = React.useState(false);
  return (
    <div
      role="option"
      aria-selected={isActive}
      tabIndex={0}
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        // group flex items-center w-full cursor-pointer hover:bg-accent-solid py-[6px] h-[36px]
        display: 'flex', alignItems: 'center', width: '100%',
        height: 36, padding: '6px 0',
        cursor: 'pointer',
        background: (isActive || hover) ? 'var(--accent-solid)' : 'transparent',
        // activeBordered ? 'border-l-[4px] border-solid border-primary pl-[6px]' : 'pl-[10px]'
        boxSizing: 'border-box',
        borderLeft: activeBordered ? '4px solid var(--primary)' : '4px solid transparent',
        paddingLeft: activeBordered ? 6 : 10,
      }}
    >
      <div style={{
        // flex flex-1 shrink justify-center items-center self-stretch my-auto text-sm font-semibold leading-6
        display: 'flex', flex: '1 1 0', minWidth: 0,
        justifyContent: 'flex-start', alignItems: 'center', alignSelf: 'stretch',
        font: '600 14px/24px var(--font-sans)',
        paddingRight: 10,
      }}>
        {icon && (
          <div style={{
            display: 'flex', alignItems: 'center',
            color: isActive ? 'var(--primary)' : 'inherit',
          }}>
            <i className={`fi fi-rr-${icon}`} style={{ lineHeight: 0, fontSize: 16 }} />
          </div>
        )}
        <span style={{
          // flex-1 shrink self-stretch my-auto basis-0 whitespace-nowrap label-semibold px-[7px] group-hover:text-foreground
          flex: '1 1 0', alignSelf: 'stretch',
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          padding: '0 7px',
          font: '600 14px/1.4 var(--font-sans)',
          color: (isActive || hover) ? 'var(--foreground)' : 'var(--foreground-75)',
          display: 'flex', alignItems: 'center',
        }}>
          {text}
        </span>
        {tag && (
          <span style={{
            marginLeft: 'auto', fontSize: 10, fontWeight: 700,
            padding: '2px 6px', borderRadius: 8,
            background: 'var(--primary-20)',
            color: 'var(--primary)',
            border: '1px solid var(--primary-30)',
          }}>{tag}</span>
        )}
      </div>
    </div>
  );
}

function ShortcutsRail() {
  const items = [
    { icon: 'user-add', label: 'New person' },
    { icon: 'file-invoice-dollar', label: 'New sale' },
    { icon: 'barcode-scan', label: 'Check-in' },
    { icon: 'calendar-plus', label: 'Book class' },
  ];
  return (
    <aside style={{
      position: 'sticky', top: 32, height: 'fit-content',
      display: 'flex', flexDirection: 'column', gap: 8, padding: 6,
      background: 'var(--background)', borderRadius: 8,
      border: '1px solid var(--border-solid)',
      boxShadow: 'var(--shadow-xs)',
    }}>
      {items.map(it => (
        <button key={it.icon} title={it.label} style={{
          width: 32, height: 32, borderRadius: 6,
          background: 'transparent', border: 'none',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: 'var(--muted-foreground)', cursor: 'pointer', fontSize: 16,
        }}>
          <i className={`fi fi-rr-${it.icon}`} style={{ lineHeight: 0 }}/>
        </button>
      ))}
    </aside>
  );
}

// PageHeader is used inside the routed content area
function PageHeader({ title, subtitle, actions }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between',
      gap: 16, marginBottom: 24 }}>
      <div>
        <h1 style={{ margin: 0, font: '600 24px/1.3 var(--font-sans)', color: 'var(--foreground)', letterSpacing: '-.01em' }}>{title}</h1>
        {subtitle && <div style={{ marginTop: 4, font: '400 14px/1.4 var(--font-sans)', color: 'var(--foreground-75)' }}>{subtitle}</div>}
      </div>
      {actions && <div style={{ display: 'flex', gap: 8 }}>{actions}</div>}
    </div>
  );
}

Object.assign(window, { Navbar, SecondarySidebar, ShortcutsRail, PageHeader });
