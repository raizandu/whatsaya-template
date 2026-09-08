/* @ds-bundle: {"format":3,"namespace":"AyaDesignSystem_9a36d7","components":[],"sourceHashes":{"ui_kits/aya-platform/Atoms.jsx":"08ef4c4eff8b","ui_kits/aya-platform/Dashboard.jsx":"b3f18614f255","ui_kits/aya-platform/DataTable.jsx":"2f603006f898","ui_kits/aya-platform/Screens.jsx":"d1eeddde84cd","ui_kits/aya-platform/Shell.jsx":"d2ab60076e24"},"inlinedExternals":[],"unexposedExports":[]} */
window.AyaDesignSystem_9a36d7 = window.AyaDesignSystem_9a36d7 || {};
(() => {
  // ui_kits/aya-platform/Atoms.jsx
  var { useState: useAtomState } = React;
  function Button2({ variant = "primary", size = "md", icon, children, onClick, disabled, full, type = "button" }) {
    const base = {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      gap: 6,
      fontFamily: "inherit",
      fontWeight: 600,
      borderRadius: 6,
      cursor: disabled ? "not-allowed" : "pointer",
      border: "1px solid transparent",
      transition: "opacity .15s, background .15s",
      opacity: disabled ? 0.5 : 1,
      width: full ? "100%" : void 0,
      whiteSpace: "nowrap"
    };
    const sizes = {
      md: { height: 32, padding: "0 12px", fontSize: 13 },
      sm: { height: 24, padding: "0 9px", fontSize: 12 },
      lg: { height: 40, padding: "0 16px", fontSize: 14 }
    };
    const variants = {
      primary: { background: "var(--primary)", color: "var(--primary-foreground)", borderColor: "var(--primary)" },
      outline: { background: "transparent", color: "var(--primary)", borderColor: "var(--primary)" },
      ghost: { background: "transparent", color: "var(--foreground)" },
      danger: { background: "var(--danger)", color: "var(--primary-foreground)", borderColor: "var(--danger)" },
      neutral: { background: "var(--muted-solid)", color: "var(--foreground)", borderColor: "var(--border-solid)" }
    };
    const style = { ...base, ...sizes[size], ...variants[variant] };
    return /* @__PURE__ */ React.createElement(
      "button",
      {
        type,
        style,
        disabled,
        onClick,
        onMouseOver: (e) => !disabled && (e.currentTarget.style.opacity = "0.9"),
        onMouseOut: (e) => !disabled && (e.currentTarget.style.opacity = "1")
      },
      icon && /* @__PURE__ */ React.createElement("i", { className: `fi fi-rr-${icon}`, style: { fontSize: 13, lineHeight: 0 } }),
      children
    );
  }
  function Input2({ icon, value, onChange, placeholder, type = "text", error, full, label, hint }) {
    const [focus, setFocus] = useAtomState(false);
    const wrap = {
      display: "flex",
      alignItems: "center",
      gap: 8,
      height: 36,
      padding: "0 12px",
      border: `1px solid ${error ? "var(--danger)" : focus ? "var(--ring)" : "var(--border-solid)"}`,
      boxShadow: focus ? "0 0 0 3px var(--primary-20)" : "none",
      borderRadius: 4,
      background: "var(--card)",
      fontSize: 13,
      width: full ? "100%" : void 0
    };
    return /* @__PURE__ */ React.createElement("label", { style: { display: "flex", flexDirection: "column", gap: 6, width: full ? "100%" : void 0 } }, label && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 600, color: "rgba(7,11,13,.75)" } }, label), /* @__PURE__ */ React.createElement("div", { style: wrap }, icon && /* @__PURE__ */ React.createElement("i", { className: `fi fi-rr-${icon}`, style: { color: "var(--muted-foreground)", fontSize: 14 } }), /* @__PURE__ */ React.createElement(
      "input",
      {
        type,
        value,
        onChange,
        placeholder,
        onFocus: () => setFocus(true),
        onBlur: () => setFocus(false),
        style: { flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 13, fontFamily: "inherit", color: "var(--foreground)" }
      }
    )), error ? /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--danger)" } }, error) : hint && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--muted-foreground)" } }, hint));
  }
  function Select2({ label, value, onChange, options, full }) {
    return /* @__PURE__ */ React.createElement("label", { style: { display: "flex", flexDirection: "column", gap: 6, width: full ? "100%" : void 0 } }, label && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 600, color: "rgba(7,11,13,.75)" } }, label), /* @__PURE__ */ React.createElement("div", { style: { position: "relative" } }, /* @__PURE__ */ React.createElement(
      "select",
      {
        value,
        onChange,
        style: {
          width: "100%",
          appearance: "none",
          WebkitAppearance: "none",
          height: 36,
          padding: "0 32px 0 12px",
          border: "1px solid var(--border-solid)",
          borderRadius: 4,
          background: "var(--card)",
          fontSize: 13,
          fontFamily: "inherit",
          color: "var(--foreground)"
        }
      },
      options.map((o) => /* @__PURE__ */ React.createElement("option", { key: o.value, value: o.value }, o.label))
    ), /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-angle-small-down", style: { position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", color: "var(--muted-foreground)", pointerEvents: "none" } })));
  }
  var STATUS = {
    success: { bg: "var(--success-fade)", fg: "var(--success-foreground)", dot: "var(--success)", bd: "var(--success)" },
    warning: { bg: "var(--warning-fade)", fg: "var(--warning-foreground)", dot: "var(--warning)", bd: "var(--warning)" },
    danger: { bg: "var(--danger-fade)", fg: "var(--danger-foreground)", dot: "var(--danger)", bd: "var(--danger)" },
    info: { bg: "var(--success-fade)", fg: "var(--success-foreground)", dot: "var(--success)", bd: "var(--success)" },
    neutral: { bg: "var(--muted-solid)", fg: "var(--foreground)", dot: "var(--muted-foreground)", bd: "var(--border-solid)" },
    purple: { bg: "var(--muted-solid)", fg: "var(--foreground)", dot: "var(--foreground)", bd: "var(--border-solid)" }
  };
  function Badge2({ variant = "neutral", icon, dot = true, children }) {
    const c = STATUS[variant];
    return /* @__PURE__ */ React.createElement("span", { style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 6,
      padding: "2px 9px",
      borderRadius: 8,
      background: c.bg,
      color: c.fg,
      border: `1px solid ${c.bd}`,
      fontSize: 11,
      fontWeight: 700,
      whiteSpace: "nowrap"
    } }, icon ? /* @__PURE__ */ React.createElement("i", { className: `fi fi-rr-${icon}`, style: { fontSize: 10 } }) : dot && /* @__PURE__ */ React.createElement("span", { style: { width: 6, height: 6, borderRadius: 999, background: c.dot } }), children);
  }
  function Spinner({ size = 16, color = "#fff" }) {
    return /* @__PURE__ */ React.createElement("span", { style: {
      display: "inline-block",
      width: size,
      height: size,
      border: `2px solid ${color}33`,
      borderTopColor: color,
      borderRadius: "50%",
      animation: "spin .7s linear infinite"
    } });
  }
  Object.assign(window, { Button: Button2, Input: Input2, Select: Select2, Badge: Badge2, Spinner, STATUS });

  // ui_kits/aya-platform/DataTable.jsx
  var { useState: useDx } = React;
  function FilterChip({ label, count, active, onClick }) {
    return /* @__PURE__ */ React.createElement("button", { onClick, style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 6,
      height: 32,
      padding: "0 12px",
      border: `1px solid ${active ? "var(--primary)" : "var(--border-solid)"}`,
      background: active ? "rgba(242,110,34,0.10)" : "#fff",
      color: active ? "var(--primary)" : "var(--foreground)",
      borderRadius: 6,
      font: "600 12px/1 Open Sans, sans-serif",
      cursor: "pointer",
      transition: "background .15s, border-color .15s"
    } }, label, count != null && /* @__PURE__ */ React.createElement("span", { style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      minWidth: 16,
      height: 16,
      padding: "0 5px",
      borderRadius: 999,
      background: "var(--primary)",
      color: "#fff",
      font: "700 10px/1 Open Sans, sans-serif"
    } }, count), /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-angle-small-down", style: { fontSize: 12, lineHeight: 0 } }));
  }
  function DxSearch({ value, onChange, placeholder = "Search\u2026" }) {
    const [focus, setFocus] = useDx(false);
    return /* @__PURE__ */ React.createElement("div", { style: { position: "relative", height: 32, width: 300 } }, /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-search", style: {
      position: "absolute",
      left: 12,
      top: "50%",
      transform: "translateY(-50%)",
      color: "var(--muted-foreground)",
      fontSize: 14,
      lineHeight: 0
    } }), /* @__PURE__ */ React.createElement(
      "input",
      {
        value: value || "",
        onChange,
        onFocus: () => setFocus(true),
        onBlur: () => setFocus(false),
        placeholder,
        style: {
          width: "100%",
          height: "100%",
          border: `1px solid ${focus ? "var(--primary)" : "var(--border-solid)"}`,
          boxShadow: focus ? "0 0 0 3px var(--primary-20)" : "none",
          borderRadius: 6,
          padding: "0 12px 0 34px",
          background: "#fff",
          color: "var(--foreground)",
          font: "400 14px/1 Open Sans, sans-serif",
          outline: "none",
          transition: "border-color .15s, box-shadow .15s"
        }
      }
    ));
  }
  function IconBtn({ icon, title, onClick }) {
    return /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick,
        title,
        style: {
          width: 32,
          height: 32,
          borderRadius: 6,
          border: "none",
          background: "transparent",
          color: "#070B0DBE",
          cursor: "pointer",
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center"
        },
        onMouseEnter: (e) => e.currentTarget.style.background = "var(--muted-solid)",
        onMouseLeave: (e) => e.currentTarget.style.background = "transparent"
      },
      /* @__PURE__ */ React.createElement("i", { className: `fi fi-rr-${icon}`, style: { fontSize: 16, lineHeight: 0 } })
    );
  }
  function DxCheck({ checked, onChange }) {
    return /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: !!checked, onChange, style: {
      appearance: "none",
      width: 16,
      height: 16,
      border: `1.5px solid ${checked ? "var(--primary)" : "var(--border-solid)"}`,
      borderRadius: 4,
      cursor: "pointer",
      position: "relative",
      background: checked ? "var(--primary)" : "#fff",
      verticalAlign: "middle"
    } });
  }
  function DxPager({ sizes = [5, 10, 20], size = 10, onSize, page = 1, totalPages = 1, total = 0, onPage }) {
    return /* @__PURE__ */ React.createElement("div", { style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      padding: "10px 14px",
      borderTop: "1px solid var(--muted-solid)",
      background: "#FFFFFF"
    } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 4 } }, sizes.map((s) => /* @__PURE__ */ React.createElement("button", { key: s, onClick: () => onSize && onSize(s), style: {
      minWidth: 32,
      height: 32,
      padding: "0 10px",
      border: "none",
      background: s === size ? "rgba(242,110,34,0.10)" : "transparent",
      color: s === size ? "var(--primary)" : "#070B0DBE",
      borderRadius: 6,
      cursor: "pointer",
      font: "600 13px/1 Open Sans, sans-serif"
    } }, s))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8 } }, /* @__PURE__ */ React.createElement("span", { style: { font: "400 12px/20px Open Sans, sans-serif", color: "var(--muted-foreground)" } }, "Page ", page, " of ", totalPages, " \xB7 ", total, " items"), /* @__PURE__ */ React.createElement(IconBtn, { icon: "angle-small-left", title: "Prev", onClick: () => onPage && onPage(Math.max(1, page - 1)) }), /* @__PURE__ */ React.createElement("input", { value: page, onChange: (e) => onPage && onPage(Number(e.target.value) || 1), style: {
      width: 44,
      height: 32,
      textAlign: "center",
      border: "1px solid var(--border-solid)",
      borderRadius: 6,
      font: "600 13px/1 Open Sans, sans-serif",
      color: "var(--foreground)",
      background: "#fff",
      outline: "none"
    } }), /* @__PURE__ */ React.createElement(IconBtn, { icon: "angle-small-right", title: "Next", onClick: () => onPage && onPage(Math.min(totalPages, page + 1)) })));
  }
  function DxDataGrid2({
    columns,
    rows,
    filters = [],
    activeFilter,
    onFilterClick,
    search,
    onSearchChange,
    actions = ["columns", "refresh", "download", "plus"],
    selectable = true,
    sortKey,
    sortDir = "asc",
    onSort,
    selected,
    onSelectChange,
    page = 1,
    size = 10,
    totalPages,
    total,
    onPage,
    onSize,
    clearLabel = "Clear",
    selectedCountLabel,
    onClearFilters
  }) {
    const selSet = selected || /* @__PURE__ */ new Set();
    const toggleRow = (i) => {
      const next = new Set(selSet);
      next.has(i) ? next.delete(i) : next.add(i);
      onSelectChange && onSelectChange(next);
    };
    const toggleAll = () => {
      if (selSet.size === rows.length) onSelectChange && onSelectChange(/* @__PURE__ */ new Set());
      else onSelectChange && onSelectChange(new Set(rows.map((_, i) => i)));
    };
    const tp = totalPages != null ? totalPages : Math.max(1, Math.ceil((total || rows.length) / size));
    return /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 12, marginBottom: 12 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 12, alignItems: "center", justifyContent: "space-between" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" } }, filters.map((f) => /* @__PURE__ */ React.createElement(
      FilterChip,
      {
        key: f.key,
        label: f.label,
        count: f.count,
        active: activeFilter === f.key,
        onClick: () => onFilterClick && onFilterClick(f.key)
      }
    ))), /* @__PURE__ */ React.createElement(DxSearch, { value: search, onChange: onSearchChange })), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center" } }, /* @__PURE__ */ React.createElement("div", { style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      font: "400 14px/20px Open Sans, sans-serif",
      color: "var(--foreground)"
    } }, selectedCountLabel || `${selSet.size} selected`, selSet.size > 0 && /* @__PURE__ */ React.createElement("button", { onClick: () => onSelectChange && onSelectChange(/* @__PURE__ */ new Set()), style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 4,
      border: "none",
      background: "transparent",
      color: "#070B0DBE",
      font: "600 12px/1 Open Sans, sans-serif",
      cursor: "pointer",
      padding: "4px 6px",
      borderRadius: 6
    } }, clearLabel, " ", /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-cross-small", style: { fontSize: 10, lineHeight: 0 } }))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 4 } }, actions.map(
      (a, i) => typeof a === "string" ? /* @__PURE__ */ React.createElement(
        IconBtn,
        {
          key: i,
          icon: a === "columns" ? "apps" : a === "refresh" ? "refresh" : a === "download" ? "download" : a === "plus" ? "plus" : a,
          title: a
        }
      ) : /* @__PURE__ */ React.createElement(React.Fragment, { key: i }, a)
    )))), /* @__PURE__ */ React.createElement("div", { style: {
      border: "1px solid var(--border-solid)",
      borderRadius: 8,
      overflow: "hidden",
      background: "#fff"
    } }, /* @__PURE__ */ React.createElement("table", { style: { width: "100%", borderCollapse: "collapse" } }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", null, selectable && /* @__PURE__ */ React.createElement("th", { style: dxTh(40, "center") }, /* @__PURE__ */ React.createElement(
      DxCheck,
      {
        checked: rows.length > 0 && selSet.size === rows.length,
        onChange: toggleAll
      }
    )), columns.map((c) => {
      const sorted = sortKey === c.key;
      return /* @__PURE__ */ React.createElement(
        "th",
        {
          key: c.key,
          onClick: () => c.sortable && onSort && onSort(c.key),
          style: { ...dxTh(c.width, c.align), cursor: c.sortable ? "pointer" : "default" }
        },
        /* @__PURE__ */ React.createElement("span", { style: {
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          justifyContent: c.align === "right" ? "flex-end" : "flex-start"
        } }, c.label, sorted && /* @__PURE__ */ React.createElement(
          "i",
          {
            className: `fi fi-rr-arrow-${sortDir === "asc" ? "down" : "up"}`,
            style: { fontSize: 10, lineHeight: 0, color: "var(--primary)" }
          }
        ))
      );
    }), /* @__PURE__ */ React.createElement("th", { style: dxTh(40, "center") }))), /* @__PURE__ */ React.createElement("tbody", null, rows.map((row, i) => {
      const isSel = selSet.has(i);
      return /* @__PURE__ */ React.createElement(
        "tr",
        {
          key: i,
          style: {
            background: isSel ? "rgba(242,110,34,0.08)" : "#fff",
            boxShadow: isSel ? "inset 2px 0 0 0 #F26E22" : "none",
            borderTop: i === 0 ? "none" : "1px solid var(--border-solid)",
            transition: "background .12s"
          },
          onMouseEnter: (e) => !isSel && (e.currentTarget.style.background = "var(--muted-solid)"),
          onMouseLeave: (e) => !isSel && (e.currentTarget.style.background = "#fff")
        },
        selectable && /* @__PURE__ */ React.createElement("td", { style: dxTd("center") }, /* @__PURE__ */ React.createElement(DxCheck, { checked: isSel, onChange: () => toggleRow(i) })),
        columns.map((c) => /* @__PURE__ */ React.createElement("td", { key: c.key, style: dxTd(c.align) }, c.render ? c.render(row) : row[c.key])),
        /* @__PURE__ */ React.createElement("td", { style: dxTd("center") }, /* @__PURE__ */ React.createElement("button", { style: {
          color: "var(--muted-foreground)",
          background: "transparent",
          border: "none",
          cursor: "pointer",
          width: 28,
          height: 28,
          borderRadius: 6,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center"
        } }, /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-menu-dots" })))
      );
    }))), /* @__PURE__ */ React.createElement(
      DxPager,
      {
        size,
        onSize,
        page,
        totalPages: tp,
        total: total != null ? total : rows.length,
        onPage
      }
    )));
  }
  function dxTh(width, align) {
    return {
      background: "var(--muted-solid)",
      color: "#070B0DBE",
      font: "600 12px/1.4 Open Sans, sans-serif",
      textAlign: align === "right" ? "right" : align === "center" ? "center" : "left",
      padding: "10px 16px",
      borderBottom: "1px solid var(--border-solid)",
      whiteSpace: "nowrap",
      userSelect: "none",
      width
    };
  }
  function dxTd(align) {
    return {
      padding: "10px 16px",
      font: "400 14px/1.45 Open Sans, sans-serif",
      color: "var(--foreground)",
      verticalAlign: "middle",
      textAlign: align === "right" ? "right" : align === "center" ? "center" : "left"
    };
  }
  function DxAvatar2({ name, tone = "purple" }) {
    const tones = {
      purple: { bg: "var(--muted-solid)", fg: "var(--foreground)" },
      blue: { bg: "var(--success-fade)", fg: "var(--success-foreground)" },
      pink: { bg: "var(--danger-fade)", fg: "var(--danger-foreground)" },
      emerald: { bg: "var(--success-fade)", fg: "var(--success-foreground)" },
      orange: { bg: "var(--danger-fade)", fg: "var(--danger-foreground)" },
      lime: { bg: "var(--success-fade)", fg: "var(--success-foreground)" }
    };
    const t = tones[tone] || tones.purple;
    return /* @__PURE__ */ React.createElement("span", { style: {
      width: 28,
      height: 28,
      borderRadius: 999,
      background: t.bg,
      color: t.fg,
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      font: "700 11px/1 Open Sans, sans-serif"
    } }, name.split(" ").map((w) => w[0]).slice(0, 2).join(""));
  }
  function DataTable2({ rows }) {
    const [selected, setSelected] = useDx(/* @__PURE__ */ new Set());
    const [search, setSearch] = useDx("");
    const [activeFilter, setActiveFilter] = useDx(null);
    const [page, setPage] = useDx(1);
    const [size, setSize] = useDx(10);
    const columns = [
      {
        key: "name",
        label: "Member",
        sortable: true,
        render: (r) => /* @__PURE__ */ React.createElement("span", { style: { display: "inline-flex", alignItems: "center", gap: 10 } }, /* @__PURE__ */ React.createElement(DxAvatar2, { name: r.name, tone: "purple" }), /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 600 } }, r.name))
      },
      { key: "plan", label: "Plan", sortable: true },
      {
        key: "at",
        label: "Time",
        sortable: true,
        render: (r) => /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "Geist, ui-sans-serif", color: "var(--muted-foreground)" } }, r.at)
      },
      {
        key: "status",
        label: "Status",
        render: (r) => /* @__PURE__ */ React.createElement(Badge, { variant: r.status }, r.reason)
      }
    ];
    return /* @__PURE__ */ React.createElement(
      DxDataGrid2,
      {
        columns,
        rows,
        filters: [
          { key: "status", label: "Status", count: activeFilter === "status" ? 1 : null },
          { key: "plan", label: "Plan" },
          { key: "period", label: "Period" }
        ],
        activeFilter,
        onFilterClick: (k) => setActiveFilter(activeFilter === k ? null : k),
        search,
        onSearchChange: (e) => setSearch(e.target.value),
        selected,
        onSelectChange: setSelected,
        page,
        size,
        total: 1284,
        onPage: setPage,
        onSize: (s) => {
          setSize(s);
          setPage(1);
        },
        selectedCountLabel: selected.size > 0 ? `${selected.size} selected` : `Showing ${rows.length} of 1,284`
      }
    );
  }
  Object.assign(window, { DataTable: DataTable2, DxDataGrid: DxDataGrid2, DxAvatar: DxAvatar2, FilterChip, DxSearch, DxPager, DxCheck });

  // ui_kits/aya-platform/Shell.jsx
  function Navbar({ breadcrumbs = [], onToggleSidebar }) {
    return /* @__PURE__ */ React.createElement("header", { style: {
      position: "relative",
      height: 48,
      background: "var(--header)",
      borderBottom: "1px solid rgba(255,255,255,0.06)",
      display: "flex",
      alignItems: "center",
      padding: "4px 32px",
      color: "var(--header-foreground)",
      fontFamily: "var(--font-sans)",
      flexShrink: 0,
      zIndex: 99
    } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", height: "100%" } }, /* @__PURE__ */ React.createElement("button", { onClick: onToggleSidebar, style: {
      background: "transparent",
      border: "none",
      color: "#fff",
      cursor: "pointer",
      width: 32,
      height: 32,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontSize: 18
    } }, /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-menu-burger", style: { lineHeight: 0 } })), /* @__PURE__ */ React.createElement("a", { href: "#", style: { display: "flex", alignItems: "center", gap: 6, marginRight: 16, marginLeft: 6, textDecoration: "none" } }, /* @__PURE__ */ React.createElement("img", { src: "../../assets/logos/logo-aya-icon.svg", alt: "Aya", style: { height: 22, filter: "brightness(0) invert(1)" } }), /* @__PURE__ */ React.createElement("img", { src: "../../assets/logos/logo-aya-text.svg", alt: "", style: { height: 14, filter: "brightness(0) invert(1)" } })), /* @__PURE__ */ React.createElement("section", { style: { display: "flex", alignItems: "center", gap: 8, marginRight: 16 } }, breadcrumbs.map((b, i) => {
      const last = i === breadcrumbs.length - 1;
      return /* @__PURE__ */ React.createElement(React.Fragment, { key: i }, /* @__PURE__ */ React.createElement("div", { style: {
        display: "flex",
        alignItems: "center",
        height: 48,
        paddingTop: 2,
        borderBottom: last ? "2px solid #fff" : "2px solid transparent"
      } }, /* @__PURE__ */ React.createElement("button", { style: {
        background: "transparent",
        border: "none",
        cursor: "pointer",
        color: last ? "#fff" : "rgba(255,255,255,0.75)",
        fontWeight: last ? 700 : 500,
        fontFamily: "inherit",
        fontSize: 13,
        padding: "0 10px",
        height: 32,
        borderRadius: 6,
        marginBottom: last ? -2 : 0
      } }, b)), !last && /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-angle-small-right", style: { fontSize: 14, color: "var(--muted-foreground)", lineHeight: 0 } }));
    }))), /* @__PURE__ */ React.createElement("div", { style: { marginRight: "auto", flex: 1, height: 48, display: "flex", justifyContent: "center", alignItems: "center", paddingRight: 8 } }, /* @__PURE__ */ React.createElement("div", { style: {
      width: "100%",
      maxWidth: 560,
      height: 32,
      borderRadius: 6,
      background: "rgba(255,255,255,0.08)",
      border: "1px solid rgba(255,255,255,0.08)",
      display: "flex",
      alignItems: "center",
      gap: 8,
      padding: "0 12px",
      color: "rgba(255,255,255,0.7)",
      fontSize: 13
    } }, /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-search", style: { fontSize: 13, lineHeight: 0 } }), /* @__PURE__ */ React.createElement("span", null, "Buscar pessoas, contratos, faturas\u2026"), /* @__PURE__ */ React.createElement("kbd", { style: {
      marginLeft: "auto",
      fontSize: 10,
      padding: "2px 6px",
      background: "rgba(255,255,255,0.08)",
      borderRadius: 4,
      fontFamily: "Geist, ui-sans-serif"
    } }, "Ctrl K"))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8 } }, /* @__PURE__ */ React.createElement(IconBtn2, { icon: "marker", title: "Access points" }), /* @__PURE__ */ React.createElement(IconBtn2, { icon: "messages", title: "Chat", dot: true }), /* @__PURE__ */ React.createElement(IconBtn2, { icon: "bell", title: "Notifications" }), /* @__PURE__ */ React.createElement(IconBtn2, { icon: "settings", title: "Settings" })), /* @__PURE__ */ React.createElement("div", { style: { marginLeft: 16 } }, /* @__PURE__ */ React.createElement("div", { style: {
      width: 32,
      height: 32,
      borderRadius: 999,
      background: "var(--primary)",
      color: "#fff",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontWeight: 700,
      fontSize: 12,
      cursor: "pointer"
    } }, "LA"))));
  }
  function IconBtn2({ icon, dot }) {
    return /* @__PURE__ */ React.createElement("button", { style: {
      position: "relative",
      width: 32,
      height: 32,
      borderRadius: 6,
      background: "transparent",
      border: "none",
      cursor: "pointer",
      color: "rgba(255,255,255,0.95)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontSize: 18
    } }, /* @__PURE__ */ React.createElement("i", { className: `fi fi-rr-${icon}`, style: { lineHeight: 0 } }), dot && /* @__PURE__ */ React.createElement("span", { style: {
      position: "absolute",
      right: 4,
      top: 4,
      width: 10,
      height: 10,
      borderRadius: 999,
      background: "var(--success)",
      border: "2px solid var(--header)"
    } }));
  }
  function SecondarySidebar({ items, active, onNavigate, title = "Menu", hideMenu = false, border = true }) {
    return /* @__PURE__ */ React.createElement("aside", { style: {
      width: 240,
      background: "var(--background)",
      borderRight: "1px solid var(--border-solid)",
      display: "flex",
      flexDirection: "column",
      fontFamily: "var(--font-sans)",
      flexShrink: 0
    } }, /* @__PURE__ */ React.createElement("ul", { style: {
      listStyle: "none",
      padding: 0,
      margin: 0,
      width: "100%",
      height: "100%",
      overflowY: "auto",
      overflowX: "hidden",
      display: hideMenu ? "none" : "flex",
      flexDirection: "column",
      alignItems: "flex-start",
      justifyContent: "flex-start"
    } }, /* @__PURE__ */ React.createElement("div", { style: {
      boxSizing: "border-box",
      borderLeft: "4px solid transparent",
      padding: "8px 6px",
      height: 40,
      lineHeight: "24px",
      display: "flex",
      alignItems: "center",
      justifyContent: "flex-start",
      font: "600 14px/1.4 var(--font-sans)",
      color: "var(--muted-foreground)"
    } }, /* @__PURE__ */ React.createElement("span", { style: { padding: "0 7px" } }, title)), items.map((it) => {
      const on = it.key === active;
      const activeBordered = border && on;
      return /* @__PURE__ */ React.createElement(
        SidebarLink,
        {
          key: it.key,
          icon: it.icon,
          text: it.label,
          tag: it.tag,
          isActive: on,
          activeBordered,
          onClick: () => onNavigate(it.key)
        }
      );
    })));
  }
  function SidebarLink({ icon, text, tag, isActive, activeBordered, onClick }) {
    const [hover, setHover] = React.useState(false);
    return /* @__PURE__ */ React.createElement(
      "div",
      {
        role: "option",
        "aria-selected": isActive,
        tabIndex: 0,
        onClick,
        onMouseEnter: () => setHover(true),
        onMouseLeave: () => setHover(false),
        style: {
          // group flex items-center w-full cursor-pointer hover:bg-accent-solid py-[6px] h-[36px]
          display: "flex",
          alignItems: "center",
          width: "100%",
          height: 36,
          padding: "6px 0",
          cursor: "pointer",
          background: isActive || hover ? "var(--accent-solid)" : "transparent",
          // activeBordered ? 'border-l-[4px] border-solid border-primary pl-[6px]' : 'pl-[10px]'
          boxSizing: "border-box",
          borderLeft: activeBordered ? "4px solid var(--primary)" : "4px solid transparent",
          paddingLeft: activeBordered ? 6 : 10
        }
      },
      /* @__PURE__ */ React.createElement("div", { style: {
        // flex flex-1 shrink justify-center items-center self-stretch my-auto text-sm font-semibold leading-6
        display: "flex",
        flex: "1 1 0",
        minWidth: 0,
        justifyContent: "flex-start",
        alignItems: "center",
        alignSelf: "stretch",
        font: "600 14px/24px var(--font-sans)",
        paddingRight: 10
      } }, icon && /* @__PURE__ */ React.createElement("div", { style: {
        display: "flex",
        alignItems: "center",
        color: isActive ? "var(--primary)" : "inherit"
      } }, /* @__PURE__ */ React.createElement("i", { className: `fi fi-rr-${icon}`, style: { lineHeight: 0, fontSize: 16 } })), /* @__PURE__ */ React.createElement("span", { style: {
        // flex-1 shrink self-stretch my-auto basis-0 whitespace-nowrap label-semibold px-[7px] group-hover:text-foreground
        flex: "1 1 0",
        alignSelf: "stretch",
        whiteSpace: "nowrap",
        overflow: "hidden",
        textOverflow: "ellipsis",
        padding: "0 7px",
        font: "600 14px/1.4 var(--font-sans)",
        color: isActive || hover ? "var(--foreground)" : "var(--foreground-75)",
        display: "flex",
        alignItems: "center"
      } }, text), tag && /* @__PURE__ */ React.createElement("span", { style: {
        marginLeft: "auto",
        fontSize: 10,
        fontWeight: 700,
        padding: "2px 6px",
        borderRadius: 8,
        background: "var(--primary-20)",
        color: "var(--primary)",
        border: "1px solid var(--primary-30)"
      } }, tag))
    );
  }
  function ShortcutsRail() {
    const items = [
      { icon: "user-add", label: "New person" },
      { icon: "file-invoice-dollar", label: "New sale" },
      { icon: "barcode-scan", label: "Check-in" },
      { icon: "calendar-plus", label: "Book class" }
    ];
    return /* @__PURE__ */ React.createElement("aside", { style: {
      position: "sticky",
      top: 32,
      height: "fit-content",
      display: "flex",
      flexDirection: "column",
      gap: 8,
      padding: 6,
      background: "var(--background)",
      borderRadius: 8,
      border: "1px solid var(--border-solid)",
      boxShadow: "var(--shadow-xs)"
    } }, items.map((it) => /* @__PURE__ */ React.createElement("button", { key: it.icon, title: it.label, style: {
      width: 32,
      height: 32,
      borderRadius: 6,
      background: "transparent",
      border: "none",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      color: "var(--muted-foreground)",
      cursor: "pointer",
      fontSize: 16
    } }, /* @__PURE__ */ React.createElement("i", { className: `fi fi-rr-${it.icon}`, style: { lineHeight: 0 } }))));
  }
  function PageHeader2({ title, subtitle, actions }) {
    return /* @__PURE__ */ React.createElement("div", { style: {
      display: "flex",
      alignItems: "flex-end",
      justifyContent: "space-between",
      gap: 16,
      marginBottom: 24
    } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("h1", { style: { margin: 0, font: "600 24px/1.3 var(--font-sans)", color: "var(--foreground)", letterSpacing: "-.01em" } }, title), subtitle && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 4, font: "400 14px/1.4 var(--font-sans)", color: "var(--foreground-75)" } }, subtitle)), actions && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8 } }, actions));
  }
  Object.assign(window, { Navbar, SecondarySidebar, ShortcutsRail, PageHeader: PageHeader2 });

  // ui_kits/aya-platform/Dashboard.jsx
  var { useMemo } = React;
  var cardChrome = {
    background: "#FFFFFF",
    border: "1px solid var(--border-solid)",
    borderRadius: 8,
    padding: 16,
    display: "flex",
    flexDirection: "column",
    gap: 16,
    minWidth: 0
  };
  var cardHeader = {
    display: "flex",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10
  };
  var cardTitle = {
    fontFamily: "'Open Sans', sans-serif",
    fontWeight: 700,
    fontSize: 14,
    lineHeight: "24px",
    color: "var(--foreground)"
  };
  var cardAccent = (kind = "success") => ({
    fontFamily: "'Open Sans', sans-serif",
    fontWeight: 700,
    fontSize: 12,
    lineHeight: "20px",
    color: kind === "success" ? "var(--success)" : kind === "danger" ? "var(--primary)" : kind === "warning" ? "var(--warning)" : "var(--muted-foreground)"
  });
  var eyebrow = {
    fontFamily: "'Open Sans', sans-serif",
    fontWeight: 700,
    fontSize: 8,
    lineHeight: "100%",
    letterSpacing: "0.16em",
    textTransform: "uppercase",
    color: "var(--muted-foreground)"
  };
  var eyebrowValue = {
    fontFamily: "'Open Sans', sans-serif",
    fontWeight: 400,
    fontSize: 12,
    lineHeight: "20px",
    color: "var(--foreground)",
    marginTop: 4
  };
  function Label({ label, value }) {
    return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column" } }, /* @__PURE__ */ React.createElement("span", { style: eyebrow }, label), /* @__PURE__ */ React.createElement("span", { style: eyebrowValue }, value));
  }
  function KpiTile({ title, value, unit, delta, deltaKind = "success", labels = [] }) {
    return /* @__PURE__ */ React.createElement("div", { style: cardChrome }, /* @__PURE__ */ React.createElement("div", { style: cardHeader }, /* @__PURE__ */ React.createElement("span", { style: cardTitle }, title), delta && /* @__PURE__ */ React.createElement("span", { style: cardAccent(deltaKind) }, deltaKind === "success" ? "\u25B2" : deltaKind === "danger" ? "\u25BC" : "\u2022", " ", delta)), /* @__PURE__ */ React.createElement("div", { style: {
      fontFamily: "Geist, ui-sans-serif",
      fontWeight: 700,
      fontSize: 36,
      lineHeight: 1,
      letterSpacing: "-.02em",
      color: "var(--foreground)",
      display: "flex",
      alignItems: "baseline",
      gap: 6
    } }, unit && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 14, fontWeight: 400, color: "var(--muted-foreground)" } }, unit), value), labels.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "row", gap: 24, marginTop: "auto" } }, labels.map((l, i) => /* @__PURE__ */ React.createElement(Label, { key: i, ...l }))));
  }
  var RECENT = [
    { name: "Lucas Almeida", plan: "Annual", at: "10:42", status: "success", reason: "Validated" },
    { name: "Beatriz Nunes", plan: "Monthly", at: "10:39", status: "success", reason: "Validated" },
    { name: "Paulo Ferreira", plan: "Daily", at: "10:36", status: "warning", reason: "Pending" },
    { name: "Julia Santos", plan: "Annual", at: "10:31", status: "success", reason: "Validated" },
    { name: "Rafael Dias", plan: "Monthly", at: "10:28", status: "danger", reason: "No subscription" },
    { name: "Carla Moraes", plan: "Student", at: "10:24", status: "success", reason: "Validated" },
    { name: "Diego Lopes", plan: "Monthly", at: "10:19", status: "success", reason: "Validated" }
  ];
  function Dashboard() {
    return /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(
      PageHeader,
      {
        title: "Dashboard",
        subtitle: "Overview of today's activity across your locations.",
        actions: [
          /* @__PURE__ */ React.createElement(Button, { key: "1", variant: "outline", icon: "calendar" }, "Last 7 days"),
          /* @__PURE__ */ React.createElement(Button, { key: "2", variant: "primary", icon: "plus" }, "New check-in")
        ]
      }
    ), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 20 } }, /* @__PURE__ */ React.createElement(
      KpiTile,
      {
        title: "Check-ins today",
        value: "1,284",
        delta: "12%",
        deltaKind: "success",
        labels: [
          { label: "Yesterday", value: "1,147" },
          { label: "7-d avg", value: "1,165" },
          { label: "Peak hour", value: "18:00" }
        ]
      }
    ), /* @__PURE__ */ React.createElement(
      KpiTile,
      {
        title: "Active members",
        value: "842",
        delta: "3%",
        deltaKind: "danger",
        labels: [
          { label: "New / wk", value: "+38" },
          { label: "Churned", value: "\u221212" },
          { label: "Trial", value: "64" }
        ]
      }
    ), /* @__PURE__ */ React.createElement(
      KpiTile,
      {
        title: "Revenue MTD",
        value: "48.920",
        unit: "R$",
        delta: "6.2%",
        deltaKind: "success",
        labels: [
          { label: "Paid", value: "R$ 41.220" },
          { label: "Pending", value: "R$ 6.180" },
          { label: "Overdue", value: "R$ 1.520" }
        ]
      }
    ), /* @__PURE__ */ React.createElement(
      KpiTile,
      {
        title: "Expiring soon",
        value: "37",
        delta: "9 vs last wk",
        deltaKind: "warning",
        labels: [
          { label: "This week", value: "14" },
          { label: "Next 30d", value: "37" },
          { label: "Auto-ren.", value: "21" }
        ]
      }
    )), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1.6fr 1fr", gap: 14 } }, /* @__PURE__ */ React.createElement("div", { style: { ...cardChrome, padding: 0, gap: 0, overflow: "hidden" } }, /* @__PURE__ */ React.createElement("div", { style: { ...cardHeader, padding: 16 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 2 } }, /* @__PURE__ */ React.createElement("span", { style: cardTitle }, "Recent check-ins"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12, lineHeight: "20px", color: "var(--muted-foreground)", fontWeight: 400 } }, "Last 60 minutes \xB7 Academia Centro")), /* @__PURE__ */ React.createElement(Button, { variant: "ghost", size: "sm", icon: "refresh" }, "Refresh")), /* @__PURE__ */ React.createElement(DataTable, { rows: RECENT })), /* @__PURE__ */ React.createElement("div", { style: cardChrome }, /* @__PURE__ */ React.createElement("div", { style: cardHeader }, /* @__PURE__ */ React.createElement("span", { style: cardTitle }, "Capacity"), /* @__PURE__ */ React.createElement("span", { style: cardAccent("success") }, "60% full")), /* @__PURE__ */ React.createElement("div", { style: {
      display: "flex",
      alignItems: "baseline",
      gap: 8,
      fontFamily: "Geist, ui-sans-serif"
    } }, /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700, fontSize: 48, lineHeight: 1, letterSpacing: "-.02em", color: "var(--foreground)" } }, "72"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 13, color: "var(--muted-foreground)" } }, "/ 120 inside")), /* @__PURE__ */ React.createElement("div", { style: { height: 8, borderRadius: 999, background: "var(--muted-solid)", overflow: "hidden" } }, /* @__PURE__ */ React.createElement("div", { style: { width: "60%", height: "100%", background: "var(--primary)" } })), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "row", gap: 24 } }, /* @__PURE__ */ React.createElement(Label, { label: "Updated", value: "12s ago" }), /* @__PURE__ */ React.createElement(Label, { label: "Peak hour", value: "18:00 \u2013 19:00" }), /* @__PURE__ */ React.createElement(Label, { label: "Trend", value: "Above avg" })))));
  }
  Object.assign(window, { Dashboard, KpiTile });

  // ui_kits/aya-platform/Screens.jsx
  var { useState: useSc, useMemo: useMemoSc } = React;
  function Modal({ open, title, subtitle, children, onClose, actions }) {
    if (!open) return null;
    return /* @__PURE__ */ React.createElement("div", { onClick: onClose, style: {
      position: "fixed",
      inset: 0,
      background: "rgba(7,11,13,0.55)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      zIndex: 50,
      animation: "fade .15s ease-out"
    } }, /* @__PURE__ */ React.createElement("div", { onClick: (e) => e.stopPropagation(), style: {
      width: 480,
      background: "#fff",
      borderRadius: 6,
      boxShadow: "0 9px 15.4px rgba(7,11,13,0.10)",
      overflow: "hidden",
      animation: "slideUp .18s ease-out"
    } }, /* @__PURE__ */ React.createElement("div", { style: {
      padding: "16px 20px",
      borderBottom: "1px solid var(--border-solid)",
      display: "flex",
      alignItems: "flex-start",
      justifyContent: "space-between",
      gap: 10
    } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 16, fontWeight: 600 } }, title), subtitle && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--muted-foreground)", marginTop: 2 } }, subtitle)), /* @__PURE__ */ React.createElement("button", { onClick: onClose, style: { background: "transparent", border: "none", cursor: "pointer", color: "var(--muted-foreground)" } }, /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-cross-small", style: { fontSize: 16 } }))), /* @__PURE__ */ React.createElement("div", { style: { padding: 20 } }, children), /* @__PURE__ */ React.createElement("div", { style: {
      padding: "12px 20px",
      borderTop: "1px solid var(--border-solid)",
      display: "flex",
      justifyContent: "flex-end",
      gap: 8,
      background: "#FFFFFF"
    } }, actions)));
  }
  function CheckInsScreen() {
    const [modalOpen, setModalOpen] = useSc(false);
    const [validated, setValidated] = useSc(false);
    const [code, setCode] = useSc("");
    const [loading, setLoading] = useSc(false);
    const handleValidate = () => {
      setLoading(true);
      setTimeout(() => {
        setLoading(false);
        setValidated(true);
      }, 800);
    };
    const closeModal = () => {
      setModalOpen(false);
      setValidated(false);
      setCode("");
    };
    return /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(
      PageHeader,
      {
        title: "Check-in",
        subtitle: "Manage and validate your customers' check-ins.",
        actions: [
          /* @__PURE__ */ React.createElement(Button, { key: "1", variant: "outline", icon: "download" }, "Export"),
          /* @__PURE__ */ React.createElement(Button, { key: "2", variant: "primary", icon: "barcode-scan", onClick: () => setModalOpen(true) }, "Validate Check-in")
        ]
      }
    ), /* @__PURE__ */ React.createElement(DataTable, { rows: [
      { name: "Lucas Almeida", plan: "Annual", at: "10:42", status: "success", reason: "Validated" },
      { name: "Beatriz Nunes", plan: "Monthly", at: "10:39", status: "success", reason: "Validated" },
      { name: "Paulo Ferreira", plan: "Daily", at: "10:36", status: "warning", reason: "Pending" },
      { name: "Julia Santos", plan: "Annual", at: "10:31", status: "success", reason: "Validated" },
      { name: "Rafael Dias", plan: "Monthly", at: "10:28", status: "danger", reason: "No subscription" },
      { name: "Carla Moraes", plan: "Student", at: "10:24", status: "success", reason: "Validated" },
      { name: "Diego Lopes", plan: "Monthly", at: "10:19", status: "success", reason: "Validated" },
      { name: "Helena Braga", plan: "Annual", at: "10:14", status: "success", reason: "Validated" },
      { name: "Igor Tavares", plan: "Monthly", at: "10:09", status: "danger", reason: "Expired" }
    ] }), /* @__PURE__ */ React.createElement(
      Modal,
      {
        open: modalOpen,
        onClose: closeModal,
        title: validated ? "Check-in validated" : "Validate Check-in",
        subtitle: validated ? "The member has been granted entry." : "Scan the barcode or enter the member ID.",
        actions: validated ? [/* @__PURE__ */ React.createElement(Button, { key: "ok", variant: "primary", onClick: closeModal }, "Done")] : [
          /* @__PURE__ */ React.createElement(Button, { key: "cn", variant: "ghost", onClick: closeModal }, "Cancel"),
          /* @__PURE__ */ React.createElement(
            Button,
            {
              key: "ok",
              variant: "primary",
              icon: loading ? null : "check",
              disabled: loading || !code,
              onClick: handleValidate
            },
            loading ? "Validating\u2026" : "Validate"
          )
        ]
      },
      validated ? /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", alignItems: "center", gap: 12, padding: "10px 0" } }, /* @__PURE__ */ React.createElement("img", { src: "../../assets/images/happy.svg", style: { height: 80 } }), /* @__PURE__ */ React.createElement("div", { style: { fontFamily: "Geist, ui-sans-serif", fontSize: 24, fontWeight: 600 } }, "Welcome Back!"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, color: "var(--muted-foreground)" } }, "Lucas Almeida \xB7 Annual plan"), /* @__PURE__ */ React.createElement(Badge, { variant: "success", icon: "check" }, "Validated at 10:42")) : /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 14 } }, /* @__PURE__ */ React.createElement(
        Input,
        {
          icon: "barcode-scan",
          label: "Member ID / Barcode",
          value: code,
          onChange: (e) => setCode(e.target.value),
          placeholder: "Scan or type\u2026",
          full: true
        }
      ), /* @__PURE__ */ React.createElement(
        Select,
        {
          label: "Access Type",
          full: true,
          options: [
            { value: "single", label: "Single entry" },
            { value: "class", label: "Class \xB7 Yoga 18:00" },
            { value: "day", label: "Day pass" }
          ],
          value: "single",
          onChange: () => {
          }
        }
      ))
    ));
  }
  var MEMBERS = [
    { name: "Lucas Almeida", plan: "Annual", since: "2021", status: "success", reason: "Active", tag: "VIP" },
    { name: "Beatriz Nunes", plan: "Monthly", since: "2024", status: "success", reason: "Active" },
    { name: "Paulo Ferreira", plan: "Daily", since: "2025", status: "warning", reason: "Trial" },
    { name: "Julia Santos", plan: "Annual", since: "2019", status: "success", reason: "Active", tag: "VIP" },
    { name: "Rafael Dias", plan: "Monthly", since: "2023", status: "danger", reason: "Past due" },
    { name: "Carla Moraes", plan: "Student", since: "2024", status: "success", reason: "Active" },
    { name: "Diego Lopes", plan: "Monthly", since: "2022", status: "success", reason: "Active" }
  ];
  function MembersScreen() {
    const [selected, setSelected] = useSc(/* @__PURE__ */ new Set());
    const [search, setSearch] = useSc("");
    const [activeFilter, setActiveFilter] = useSc("plan");
    const [page, setPage] = useSc(1);
    const [size, setSize] = useSc(10);
    const [sortKey, setSortKey] = useSc("name");
    const [sortDir, setSortDir] = useSc("asc");
    const tones = ["purple", "blue", "pink", "emerald", "orange", "lime"];
    const columns = [
      {
        key: "name",
        label: "Member",
        sortable: true,
        render: (m) => /* @__PURE__ */ React.createElement("span", { style: { display: "inline-flex", alignItems: "center", gap: 10 } }, /* @__PURE__ */ React.createElement(DxAvatar, { name: m.name, tone: tones[m.name.length % tones.length] }), /* @__PURE__ */ React.createElement("span", { style: { display: "flex", flexDirection: "column" } }, /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 6 } }, m.name, m.tag && /* @__PURE__ */ React.createElement(Badge, { variant: "purple", icon: "star", dot: false }, m.tag)), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--muted-foreground)" } }, m.name.toLowerCase().replace(" ", "."), "@gmail.com")))
      },
      { key: "plan", label: "Plan", sortable: true },
      {
        key: "since",
        label: "Since",
        sortable: true,
        render: (m) => /* @__PURE__ */ React.createElement("span", { style: { fontFamily: "Geist, ui-sans-serif", color: "var(--muted-foreground)" } }, m.since)
      },
      {
        key: "status",
        label: "Status",
        render: (m) => /* @__PURE__ */ React.createElement(Badge, { variant: m.status }, m.reason)
      }
    ];
    return /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(
      PageHeader,
      {
        title: "Members",
        subtitle: "Your full roster \u2014 active, trial, and past due.",
        actions: [
          /* @__PURE__ */ React.createElement(Button, { key: "1", variant: "outline", icon: "upload" }, "Import CSV"),
          /* @__PURE__ */ React.createElement(Button, { key: "2", variant: "primary", icon: "plus" }, "Add Member")
        ]
      }
    ), /* @__PURE__ */ React.createElement(
      DxDataGrid,
      {
        columns,
        rows: MEMBERS,
        filters: [
          { key: "plan", label: "Plan", count: activeFilter === "plan" ? 1 : null },
          { key: "status", label: "Status" },
          { key: "since", label: "Tenure" },
          { key: "tag", label: "VIP" }
        ],
        activeFilter,
        onFilterClick: (k) => setActiveFilter(activeFilter === k ? null : k),
        search,
        onSearchChange: (e) => setSearch(e.target.value),
        selected,
        onSelectChange: setSelected,
        sortKey,
        sortDir,
        onSort: (k) => {
          if (k === sortKey) setSortDir(sortDir === "asc" ? "desc" : "asc");
          else {
            setSortKey(k);
            setSortDir("asc");
          }
        },
        page,
        size,
        total: MEMBERS.length,
        onPage: setPage,
        onSize: (s) => {
          setSize(s);
          setPage(1);
        },
        selectedCountLabel: selected.size > 0 ? `${selected.size} selected` : `Showing ${MEMBERS.length} members`
      }
    ));
  }
  function SettingsScreen() {
    return /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(
      PageHeader,
      {
        title: "Settings",
        subtitle: "Manage your location, billing details, and team access."
      }
    ), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "220px 1fr", gap: 24 } }, /* @__PURE__ */ React.createElement("nav", { style: { display: "flex", flexDirection: "column", gap: 2 } }, ["Location", "Business hours", "Plans", "Billing", "Team", "Integrations", "Notifications"].map((t, i) => /* @__PURE__ */ React.createElement("a", { key: t, style: {
      padding: "8px 12px",
      borderRadius: 6,
      fontSize: 13,
      fontWeight: 600,
      color: i === 0 ? "var(--primary)" : "var(--muted-foreground)",
      background: i === 0 ? "rgba(242,110,34,0.08)" : "transparent",
      cursor: "pointer",
      textDecoration: "none"
    } }, t))), /* @__PURE__ */ React.createElement("div", { style: { background: "#FFFFFF", border: "1px solid var(--border-solid)", borderRadius: 6, padding: 22 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 15, fontWeight: 600, marginBottom: 4 } }, "Location details"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--muted-foreground)", marginBottom: 18 } }, "Shown on receipts, invoices and member welcome emails."), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 } }, /* @__PURE__ */ React.createElement(Input, { label: "Business name", full: true, value: "Academia Centro", onChange: () => {
    } }), /* @__PURE__ */ React.createElement(Input, { label: "Tax ID (CNPJ)", full: true, value: "12.345.678/0001-90", onChange: () => {
    } }), /* @__PURE__ */ React.createElement(Input, { label: "Street address", full: true, value: "Av. Paulista, 1000", onChange: () => {
    } }), /* @__PURE__ */ React.createElement(Input, { label: "City", full: true, value: "S\xE3o Paulo", onChange: () => {
    } }), /* @__PURE__ */ React.createElement(Input, { label: "Phone", full: true, icon: "phone-call", value: "+55 11 91234-5678", onChange: () => {
    } }), /* @__PURE__ */ React.createElement(Input, { label: "Support email", full: true, icon: "envelope", value: "help@academiacentro.com.br", onChange: () => {
    } })), /* @__PURE__ */ React.createElement("hr", { style: { border: "none", borderTop: "1px solid var(--border-solid)", margin: "22px 0" } }), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "flex-end", gap: 8 } }, /* @__PURE__ */ React.createElement(Button, { variant: "ghost" }, "Cancel"), /* @__PURE__ */ React.createElement(Button, { variant: "primary" }, "Save")))));
  }
  Object.assign(window, { Modal, CheckInsScreen, MembersScreen, SettingsScreen });
})();
