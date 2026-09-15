/* @ds-bundle: {"format":3,"namespace":"AyaDesignSystem_47c427","components":[],"sourceHashes":{"ui_kits/aya-platform/Atendimento.jsx":"d2c1f75d3970","ui_kits/aya-platform/Atoms.jsx":"6d55c93c8b95","ui_kits/aya-platform/Dashboard.jsx":"32d95b19f842","ui_kits/aya-platform/DataTable.jsx":"55327f67c5cf","ui_kits/aya-platform/Screens.jsx":"a31807e69677","ui_kits/aya-platform/Shell.jsx":"e9746b67b25b","ui_kits/aya-platform/WhatsAya.jsx":"e4f98c267486"},"inlinedExternals":[],"unexposedExports":[]} */
window.AyaDesignSystem_47c427 = window.AyaDesignSystem_47c427 || {};
(() => {
  // ui_kits/aya-platform/Atoms.jsx
  var KIT_CSS = `
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
    if (typeof document === "undefined" || document.getElementById("aya-kit-styles")) return;
    const style = document.createElement("style");
    style.id = "aya-kit-styles";
    style.textContent = KIT_CSS;
    document.head.appendChild(style);
  })();
  var BUTTON_VARIANT_ALIAS = { neutral: "secondary", danger: "destructive" };
  function Spinner({ size = 14 }) {
    return /* @__PURE__ */ React.createElement("span", { className: "aya-spinner", style: size !== 14 ? { width: size, height: size } : void 0, "aria-hidden": "true" });
  }
  function Button2({ variant = "primary", size = "md", icon, children, onClick, disabled, full, type = "button", loading, title }) {
    const v = BUTTON_VARIANT_ALIAS[variant] || variant;
    const iconOnly = icon && !children;
    return /* @__PURE__ */ React.createElement(
      "button",
      {
        type,
        className: "aya-btn",
        "data-variant": v,
        "data-size": size,
        "data-full": full ? "" : void 0,
        "data-icon-only": iconOnly ? "" : void 0,
        "data-loading": loading ? "" : void 0,
        disabled,
        onClick,
        title,
        "aria-busy": loading || void 0
      },
      loading ? /* @__PURE__ */ React.createElement(Spinner, null) : icon && /* @__PURE__ */ React.createElement("i", { className: `fi fi-rr-${icon}`, "aria-hidden": "true" }),
      children
    );
  }
  function Input2({ icon, value, onChange, placeholder, type = "text", error, full, label, hint, disabled }) {
    return /* @__PURE__ */ React.createElement("label", { className: "aya-field", "data-full": full ? "" : void 0 }, label && /* @__PURE__ */ React.createElement("span", { className: "aya-label" }, label), /* @__PURE__ */ React.createElement("div", { className: "aya-input", "data-error": error ? "" : void 0 }, icon && /* @__PURE__ */ React.createElement("i", { className: `fi fi-rr-${icon}`, "aria-hidden": "true" }), /* @__PURE__ */ React.createElement("input", { type, value, onChange, placeholder, disabled, "aria-invalid": error ? true : void 0 }), error && /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-exclamation", style: { color: "var(--destructive)" }, "aria-hidden": "true" })), error ? /* @__PURE__ */ React.createElement("span", { className: "aya-error" }, /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-exclamation", "aria-hidden": "true" }), error) : hint && /* @__PURE__ */ React.createElement("span", { className: "aya-hint" }, hint));
  }
  function Select2({ label, value, onChange, options, full, hint, disabled }) {
    return /* @__PURE__ */ React.createElement("label", { className: "aya-field", "data-full": full ? "" : void 0 }, label && /* @__PURE__ */ React.createElement("span", { className: "aya-label" }, label), /* @__PURE__ */ React.createElement("div", { className: "aya-select" }, /* @__PURE__ */ React.createElement("select", { value, onChange, disabled }, options.map((o) => /* @__PURE__ */ React.createElement("option", { key: o.value, value: o.value }, o.label))), /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-angle-small-down", "aria-hidden": "true" })), hint && /* @__PURE__ */ React.createElement("span", { className: "aya-hint" }, hint));
  }
  var STATUS = {
    neutral: { bg: "var(--muted-transparent)", fg: "var(--foreground)", dot: "var(--muted-foreground)" },
    success: { bg: "var(--success-fade)", fg: "var(--success-foreground)", dot: "var(--success)" },
    warning: { bg: "var(--warning-fade)", fg: "var(--warning-foreground)", dot: "var(--warning)" },
    danger: { bg: "var(--danger-fade)", fg: "var(--danger-foreground)", dot: "var(--destructive)" },
    whatsapp: { bg: "var(--success-fade)", fg: "var(--success-foreground)", dot: "var(--success)" }
  };
  STATUS.info = STATUS.success;
  STATUS.purple = STATUS.neutral;
  function Badge2({ variant = "neutral", icon, dot = true, children }) {
    const c = STATUS[variant] || STATUS.neutral;
    return /* @__PURE__ */ React.createElement("span", { className: "aya-badge", style: { background: c.bg, color: c.fg } }, icon ? /* @__PURE__ */ React.createElement("i", { className: `fi fi-rr-${icon}`, "aria-hidden": "true" }) : dot && /* @__PURE__ */ React.createElement("span", { className: "aya-dot", style: { background: c.dot } }), children);
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
      border: 0,
      boxShadow: active ? "0 0 0 1px var(--primary-deep)" : "var(--shadow-xs)",
      background: active ? "var(--primary-10)" : "var(--card)",
      color: active ? "var(--primary-deep)" : "var(--foreground)",
      borderRadius: 6,
      font: "600 12px/1 Open Sans, sans-serif",
      cursor: "pointer",
      transition: "background-color var(--duration-base) var(--ease-hover), box-shadow var(--duration-base) var(--ease-hover)"
    } }, label, count != null && /* @__PURE__ */ React.createElement("span", { style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      minWidth: 16,
      height: 16,
      padding: "0 5px",
      borderRadius: 999,
      background: "var(--primary)",
      color: "var(--primary-foreground)",
      font: "700 10px/1 var(--font-numeric)"
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
          border: `1px solid ${focus ? "var(--ring)" : "var(--hairline-strong)"}`,
          boxShadow: focus ? "0 0 0 3px var(--primary-20)" : "none",
          borderRadius: 6,
          padding: "0 12px 0 34px",
          background: "var(--input-bg)",
          color: "var(--foreground)",
          font: "400 14px/1 Open Sans, sans-serif",
          outline: "none",
          transition: "border-color var(--duration-base) var(--ease-hover), box-shadow var(--duration-base) var(--ease-hover)"
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
          color: "var(--foreground-75)",
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
      margin: 0,
      border: `1px solid ${checked ? "var(--primary-edge)" : "var(--hairline-strong)"}`,
      borderRadius: 4,
      cursor: "pointer",
      position: "relative",
      background: checked ? "var(--primary)" : "var(--input-bg)",
      verticalAlign: "middle",
      backgroundImage: checked ? `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' fill='none'%3E%3Cpath d='M1.5 5.2L3.8 7.5L8.5 2.5' stroke='%23070B0D' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E")` : "none",
      backgroundSize: "10px",
      backgroundPosition: "center",
      backgroundRepeat: "no-repeat",
      transition: "background-color var(--duration-base) var(--ease-hover), border-color var(--duration-base) var(--ease-hover)"
    } });
  }
  function DxPager({ sizes = [5, 10, 20], size = 10, onSize, page = 1, totalPages = 1, total = 0, onPage }) {
    return /* @__PURE__ */ React.createElement("div", { style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      padding: "10px 14px",
      borderTop: "1px solid var(--hairline)",
      background: "var(--card)"
    } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 4 } }, sizes.map((s) => /* @__PURE__ */ React.createElement("button", { key: s, onClick: () => onSize && onSize(s), style: {
      minWidth: 32,
      height: 32,
      padding: "0 10px",
      border: "none",
      background: s === size ? "var(--primary-10)" : "transparent",
      color: s === size ? "var(--primary-deep)" : "var(--foreground-75)",
      borderRadius: 6,
      cursor: "pointer",
      font: "600 13px/1 Open Sans, sans-serif"
    } }, s))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8 } }, /* @__PURE__ */ React.createElement("span", { style: { font: "400 12px/20px Open Sans, sans-serif", color: "var(--muted-foreground)" } }, "Page ", page, " of ", totalPages, " \xB7 ", total, " items"), /* @__PURE__ */ React.createElement(IconBtn, { icon: "angle-small-left", title: "Prev", onClick: () => onPage && onPage(Math.max(1, page - 1)) }), /* @__PURE__ */ React.createElement("input", { value: page, onChange: (e) => onPage && onPage(Number(e.target.value) || 1), style: {
      width: 44,
      height: 32,
      textAlign: "center",
      border: "1px solid var(--hairline-strong)",
      borderRadius: 6,
      font: "600 13px/1 var(--font-numeric)",
      color: "var(--foreground)",
      background: "var(--input-bg)",
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
      color: "var(--foreground-75)",
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
      boxShadow: "var(--shadow-xs)",
      borderRadius: 8,
      overflow: "hidden",
      background: "var(--card)"
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
            style: { fontSize: 10, lineHeight: 0, color: "var(--primary-deep)" }
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
            background: isSel ? "var(--primary-10)" : "var(--card)",
            boxShadow: isSel ? "inset 2px 0 0 0 var(--primary)" : "none",
            borderTop: i === 0 ? "none" : "1px solid var(--border-solid-50)",
            transition: "background-color var(--duration-instant) linear"
          },
          onMouseEnter: (e) => !isSel && (e.currentTarget.style.background = "var(--muted-solid)"),
          onMouseLeave: (e) => !isSel && (e.currentTarget.style.background = "var(--card)")
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
      color: "var(--foreground-75)",
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
    return /* @__PURE__ */ React.createElement("header", { className: "aya-navbar", style: {
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
    } }, /* @__PURE__ */ React.createElement("div", { className: "aya-navbar-start", style: { display: "flex", alignItems: "center", height: "100%" } }, /* @__PURE__ */ React.createElement("button", { onClick: onToggleSidebar, style: {
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
    }))), /* @__PURE__ */ React.createElement("div", { className: "aya-global-search", style: { marginRight: "auto", flex: 1, height: 48, display: "flex", justifyContent: "center", alignItems: "center", paddingRight: 8 } }, /* @__PURE__ */ React.createElement("div", { style: {
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
    } }, /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-search", style: { fontSize: 13, lineHeight: 0 } }), /* @__PURE__ */ React.createElement("span", null, "Buscar lead, conversa ou telefone\u2026"), /* @__PURE__ */ React.createElement("kbd", { style: {
      marginLeft: "auto",
      fontSize: 10,
      padding: "2px 6px",
      background: "rgba(255,255,255,0.08)",
      borderRadius: 4,
      fontFamily: "Geist, ui-sans-serif"
    } }, "Ctrl K"))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8 } }, /* @__PURE__ */ React.createElement(IconBtn2, { icon: "comment-alt", title: "Conversas", dot: true }), /* @__PURE__ */ React.createElement(IconBtn2, { icon: "bell", title: "Notifica\xE7\xF5es" }), /* @__PURE__ */ React.createElement(IconBtn2, { icon: "settings", title: "Configura\xE7\xF5es" })), /* @__PURE__ */ React.createElement("div", { style: { marginLeft: 16 } }, /* @__PURE__ */ React.createElement("div", { style: {
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
    } }, "RO"))));
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
    return /* @__PURE__ */ React.createElement("aside", { className: "aya-sidebar", style: {
      width: 240,
      background: "var(--background)",
      borderRight: "1px solid var(--border-solid)",
      display: "flex",
      flexDirection: "column",
      fontFamily: "var(--font-sans)",
      flexShrink: 0
    } }, /* @__PURE__ */ React.createElement("ul", { className: "aya-sidebar-list", style: {
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
    background: "var(--card)",
    boxShadow: "var(--shadow-xs)",
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
      background: "var(--backdrop)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      zIndex: "var(--z-modal)",
      animation: "aya-fade var(--duration-fast) var(--ease-out)"
    } }, /* @__PURE__ */ React.createElement("div", { onClick: (e) => e.stopPropagation(), style: {
      width: 480,
      background: "var(--dialog)",
      borderRadius: "var(--radius-lg)",
      boxShadow: "var(--shadow-lg)",
      overflow: "hidden",
      animation: "aya-slide-up var(--duration-moderate) var(--ease-out)"
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
      background: "var(--dialog)"
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
      color: i === 0 ? "var(--primary-deep)" : "var(--muted-foreground)",
      background: i === 0 ? "var(--primary-10)" : "transparent",
      cursor: "pointer",
      textDecoration: "none"
    } }, t))), /* @__PURE__ */ React.createElement("div", { style: { background: "var(--card)", boxShadow: "var(--shadow-xs)", borderRadius: "var(--radius-lg)", padding: 22 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 15, fontWeight: 600, marginBottom: 4 } }, "Location details"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--muted-foreground)", marginBottom: 18 } }, "Shown on receipts, invoices and member welcome emails."), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 } }, /* @__PURE__ */ React.createElement(Input, { label: "Business name", full: true, value: "Academia Centro", onChange: () => {
    } }), /* @__PURE__ */ React.createElement(Input, { label: "Tax ID (CNPJ)", full: true, value: "12.345.678/0001-90", onChange: () => {
    } }), /* @__PURE__ */ React.createElement(Input, { label: "Street address", full: true, value: "Av. Paulista, 1000", onChange: () => {
    } }), /* @__PURE__ */ React.createElement(Input, { label: "City", full: true, value: "S\xE3o Paulo", onChange: () => {
    } }), /* @__PURE__ */ React.createElement(Input, { label: "Phone", full: true, icon: "phone-call", value: "+55 11 91234-5678", onChange: () => {
    } }), /* @__PURE__ */ React.createElement(Input, { label: "Support email", full: true, icon: "envelope", value: "help@academiacentro.com.br", onChange: () => {
    } })), /* @__PURE__ */ React.createElement("hr", { style: { border: "none", borderTop: "1px solid var(--border-solid)", margin: "22px 0" } }), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "flex-end", gap: 8 } }, /* @__PURE__ */ React.createElement(Button, { variant: "ghost" }, "Cancel"), /* @__PURE__ */ React.createElement(Button, { variant: "primary" }, "Save")))));
  }
  Object.assign(window, { Modal, CheckInsScreen, MembersScreen, SettingsScreen });

  // ui_kits/aya-platform/WhatsAya.jsx
  var { useMemo: useWhatsAyaMemo, useState: useWhatsAyaState } = React;
  var WHATSAYA_CONTACTS = [
    {
      id: "marina",
      name: "Marina Costa",
      initials: "MC",
      phone: "(11) 9 8123-4401",
      stage: "Qualifica\xE7\xE3o",
      last: "Quero entender como funciona a sess\xE3o.",
      time: "10:42",
      unread: 2,
      status: "handoff",
      automation: false,
      messages: [
        { side: "lead", body: "Oi, vi o conte\xFAdo de voc\xEAs e queria entender melhor.", time: "10:31" },
        { side: "aya", body: "Oi, Marina. Sou a AYA, assistente da Cl\xEDnica Horizonte. Posso te explicar e tamb\xE9m entender o que voc\xEA busca hoje.", time: "10:32" },
        { side: "lead", body: "Quero entender como funciona a sess\xE3o.", time: "10:42" }
      ]
    },
    {
      id: "paula",
      name: "Paula Mendes",
      initials: "PM",
      phone: "(21) 9 7402-1830",
      stage: "Agendamento",
      last: "Ter\xE7a \xE0s 15h funciona para mim.",
      time: "09:18",
      unread: 0,
      status: "scheduled",
      automation: true,
      messages: [
        { side: "lead", body: "Tem algum hor\xE1rio livre nesta semana?", time: "09:12" },
        { side: "aya", body: "Tenho ter\xE7a \xE0s 15h e quinta \xE0s 18h dispon\xEDveis. Qual combina melhor com voc\xEA?", time: "09:14" },
        { side: "lead", body: "Ter\xE7a \xE0s 15h funciona para mim.", time: "09:18" },
        { side: "aya", body: "Perfeito. Vou reservar e j\xE1 te confirmo os pr\xF3ximos passos.", time: "09:19" }
      ]
    },
    {
      id: "luciana",
      name: "Luciana Alves",
      initials: "LA",
      phone: "(31) 9 6501-9274",
      stage: "Novo lead",
      last: "\xC1udio recebido \xB7 0:38",
      time: "Ontem",
      unread: 0,
      status: "audio",
      automation: true,
      messages: [
        { side: "lead", body: "\xC1udio recebido \xB7 0:38", time: "Ontem, 18:06", audio: true },
        { side: "system", body: "\xC1udio transcrito e anexado ao contexto da conversa.", time: "18:07" },
        { side: "aya", body: "Entendi o que voc\xEA relatou. Posso te fazer duas perguntas r\xE1pidas para direcionar melhor?", time: "18:08" }
      ]
    },
    {
      id: "renata",
      name: "Renata Lima",
      initials: "RL",
      phone: "(41) 9 5330-1188",
      stage: "Reativa\xE7\xE3o D+2",
      last: "Vou pensar e te chamo amanh\xE3.",
      time: "Seg",
      unread: 0,
      status: "followup",
      automation: true,
      messages: [
        { side: "lead", body: "Vou pensar e te chamo amanh\xE3.", time: "Seg, 16:22" },
        { side: "system", body: "Follow-up D+2 programado para hoje \xE0s 14:30.", time: "16:23" }
      ]
    }
  ];
  var PIPELINE_COLUMNS = [
    {
      key: "new",
      label: "Novos leads",
      count: 3,
      cards: [
        { name: "Luciana Alves", detail: "Entrou por indica\xE7\xE3o", time: "h\xE1 18 min", badge: "IA ativa" },
        { name: "Camila Rocha", detail: "Primeiro contato recebido", time: "h\xE1 1 h", badge: "IA ativa" },
        { name: "Fernanda Souza", detail: "Aguardando contexto", time: "h\xE1 3 h", badge: "IA ativa" }
      ]
    },
    {
      key: "qualified",
      label: "Qualifica\xE7\xE3o",
      count: 2,
      cards: [
        { name: "Marina Costa", detail: "Pediu atendimento humano", time: "h\xE1 4 min", badge: "Handoff", attention: true },
        { name: "Bianca Freitas", detail: "D\xFAvida sobre a sess\xE3o", time: "h\xE1 42 min", badge: "IA ativa" }
      ]
    },
    {
      key: "scheduled",
      label: "Agendamento",
      count: 2,
      cards: [
        { name: "Paula Mendes", detail: "Ter\xE7a \xB7 15:00", time: "confirmado", badge: "Google Agenda", success: true },
        { name: "Juliana Prado", detail: "Aguardando escolha de hor\xE1rio", time: "h\xE1 2 h", badge: "IA ativa" }
      ]
    },
    {
      key: "converted",
      label: "Convertidos",
      count: 2,
      cards: [
        { name: "Ana Ribeiro", detail: "Sess\xE3o individual", time: "hoje", badge: "Conclu\xEDdo", success: true },
        { name: "Sofia Martins", detail: "M\xE9todo gravado", time: "ontem", badge: "Conclu\xEDdo", success: true }
      ]
    }
  ];
  var _surface = {
    background: "var(--card)",
    boxShadow: "var(--shadow-hairline)",
    borderRadius: 8
  };
  function WhatsAyaPageHeader({ eyebrow: eyebrow2, title, subtitle, actions }) {
    return /* @__PURE__ */ React.createElement("div", { className: "wa-page-header", style: { display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 20, marginBottom: 24 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { color: "var(--primary)", fontSize: 11, lineHeight: 1.2, fontWeight: 700, marginBottom: 7 } }, eyebrow2), /* @__PURE__ */ React.createElement("h1", { style: { margin: 0, font: "600 24px/1.25 var(--font-sans)", letterSpacing: "-.01em" } }, title), /* @__PURE__ */ React.createElement("p", { style: { margin: "6px 0 0", color: "var(--foreground-75)", fontSize: 13, lineHeight: 1.5 } }, subtitle)), actions && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" } }, actions));
  }
  function WhatsAyaStatus({ tone = "neutral", children }) {
    const styles = tone === "success" ? { background: "var(--success-fade)", border: "var(--success)", dot: "var(--success)" } : tone === "warning" ? { background: "var(--warning-fade)", border: "var(--warning)", dot: "var(--warning)" } : { background: "var(--muted-solid)", border: "var(--border-solid)", dot: "var(--muted-foreground)" };
    return /* @__PURE__ */ React.createElement("span", { style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 6,
      minHeight: 24,
      padding: "2px 9px",
      borderRadius: 999,
      background: styles.background,
      border: `1px solid ${styles.border}`,
      fontSize: 11,
      fontWeight: 700,
      whiteSpace: "nowrap"
    } }, /* @__PURE__ */ React.createElement("span", { style: { width: 6, height: 6, borderRadius: 999, background: styles.dot } }), children);
  }
  function WhatsAyaMetric({ icon, label, value, helper, tone = "neutral" }) {
    const iconBackground = tone === "success" ? "var(--success-fade)" : tone === "warning" ? "var(--warning-fade)" : "var(--muted-solid)";
    const iconColor = tone === "success" ? "var(--success)" : tone === "warning" ? "var(--primary)" : "var(--foreground)";
    return /* @__PURE__ */ React.createElement("article", { style: { ..._surface, padding: 16, minHeight: 130, display: "flex", flexDirection: "column", gap: 14 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 600, color: "var(--foreground-75)" } }, label), /* @__PURE__ */ React.createElement("span", { style: { width: 30, height: 30, borderRadius: 6, display: "inline-flex", alignItems: "center", justifyContent: "center", background: iconBackground, color: iconColor } }, /* @__PURE__ */ React.createElement("i", { className: `fi fi-rr-${icon}`, style: { fontSize: 14, lineHeight: 0 } }))), /* @__PURE__ */ React.createElement("div", { style: { font: "700 34px/1 var(--font-numeric)", letterSpacing: "-.03em" } }, value), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "var(--muted-foreground)" } }, helper));
  }
  function WhatsAyaSectionHeader({ title, subtitle, action }) {
    return /* @__PURE__ */ React.createElement("header", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 14 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("h2", { style: { margin: 0, font: "600 16px/1.3 var(--font-sans)" } }, title), subtitle && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 3, fontSize: 11, color: "var(--muted-foreground)" } }, subtitle)), action);
  }
  function WhatsAyaToggle({ checked, onChange, label }) {
    return /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        role: "switch",
        "aria-checked": checked,
        "aria-label": label,
        onClick: onChange,
        style: {
          width: 36,
          height: 20,
          padding: 2,
          borderRadius: 999,
          border: 0,
          flexShrink: 0,
          cursor: "pointer",
          background: checked ? "var(--success)" : "hsl(var(--shadow-tint) / .22)",
          boxShadow: checked ? "inset 0 0 0 1px var(--green-edge)" : "inset 0 0 0 1px hsl(var(--shadow-tint) / .06), inset 0 1px 2px hsl(var(--shadow-tint) / .10)",
          transition: "background-color var(--duration-base) var(--ease-hover), box-shadow var(--duration-base) var(--ease-hover)"
        }
      },
      /* @__PURE__ */ React.createElement("span", { style: {
        display: "block",
        width: 16,
        height: 16,
        borderRadius: 999,
        background: "#FFFFFF",
        transform: checked ? "translateX(16px)" : "translateX(0)",
        transition: "transform var(--duration-fast) var(--ease-out)",
        boxShadow: "0 0 0 1px hsl(var(--shadow-tint) / .08), 0 1px 2px hsl(var(--shadow-tint) / .28), 0 2px 4px -1px hsl(var(--shadow-tint) / .16)"
      } })
    );
  }
  function WhatsAyaOverview({ onNavigate, botPaused, onToggleBot }) {
    const automationLabel = botPaused ? "Automa\xE7\xE3o pausada" : "Automa\xE7\xE3o ativa";
    return /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(
      WhatsAyaPageHeader,
      {
        eyebrow: "Dr. Exemplo \xB7 Cl\xEDnica Horizonte",
        title: "Bom dia, Dr. Exemplo.",
        subtitle: "Acompanhe o atendimento da AYA e veja o que precisa da sua decis\xE3o agora.",
        actions: [
          /* @__PURE__ */ React.createElement(WhatsAyaStatus, { key: "preview", tone: "neutral" }, "Dados demonstrativos"),
          /* @__PURE__ */ React.createElement(Button, { key: "bot", variant: botPaused ? "primary" : "outline", icon: botPaused ? "play" : "pause", onClick: onToggleBot }, botPaused ? "Retomar IA" : "Pausar IA")
        ]
      }
    ), /* @__PURE__ */ React.createElement("section", { style: {
      ..._surface,
      background: "var(--header)",
      color: "var(--header-foreground)",
      padding: 20,
      marginBottom: 16,
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      gap: 18,
      flexWrap: "wrap"
    } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 14 } }, /* @__PURE__ */ React.createElement("span", { style: {
      width: 42,
      height: 42,
      borderRadius: 8,
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      background: "var(--success)",
      color: "var(--aya-black)",
      fontSize: 20
    } }, /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-comment-alt" })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("strong", { style: { fontSize: 15 } }, "WhatsApp conectado"), /* @__PURE__ */ React.createElement(WhatsAyaStatus, { tone: botPaused ? "warning" : "success" }, automationLabel)), /* @__PURE__ */ React.createElement("div", { style: { color: "var(--header-foreground-50)", fontSize: 11, marginTop: 5 } }, "Sess\xE3o est\xE1vel h\xE1 3d 8h \xB7 \xFAltima sincroniza\xE7\xE3o agora"))), /* @__PURE__ */ React.createElement(Button, { variant: "whatsapp", icon: "settings", onClick: () => onNavigate("operations") }, "Ver conex\xE3o")), /* @__PURE__ */ React.createElement("div", { className: "wa-metrics", style: { display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 12, marginBottom: 16 } }, /* @__PURE__ */ React.createElement(WhatsAyaMetric, { icon: "users-alt", label: "Leads migrados", value: "9", helper: "base Cl\xEDnica Horizonte preparada" }), /* @__PURE__ */ React.createElement(WhatsAyaMetric, { icon: "comment-alt", label: "Mensagens hist\xF3ricas", value: "179", helper: "somente leitura no contexto" }), /* @__PURE__ */ React.createElement(WhatsAyaMetric, { icon: "calendar-check", label: "Agendamentos", value: "2", helper: "1 aguardando reconcilia\xE7\xE3o", tone: "success" }), /* @__PURE__ */ React.createElement(WhatsAyaMetric, { icon: "headset", label: "Fila humana", value: "1", helper: "handoff com prioridade", tone: "warning" })), /* @__PURE__ */ React.createElement("div", { className: "wa-two-columns", style: { display: "grid", gridTemplateColumns: "minmax(0, 1.45fr) minmax(300px, .75fr)", gap: 16 } }, /* @__PURE__ */ React.createElement("section", { style: { ..._surface, padding: 18 } }, /* @__PURE__ */ React.createElement(
      WhatsAyaSectionHeader,
      {
        title: "Quem precisa de voc\xEA",
        subtitle: "Handoffs e situa\xE7\xF5es que a IA n\xE3o deve decidir sozinha",
        action: /* @__PURE__ */ React.createElement(Button, { variant: "ghost", size: "sm", onClick: () => onNavigate("conversations") }, "Ver conversas")
      }
    ), /* @__PURE__ */ React.createElement("button", { onClick: () => onNavigate("conversations"), style: {
      width: "100%",
      padding: 14,
      borderRadius: 6,
      border: "1px solid var(--primary)",
      background: "var(--warning-fade)",
      display: "flex",
      alignItems: "center",
      gap: 12,
      textAlign: "left",
      cursor: "pointer"
    } }, /* @__PURE__ */ React.createElement("span", { style: {
      width: 36,
      height: 36,
      borderRadius: 999,
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      background: "var(--card)",
      fontWeight: 700
    } }, "MC"), /* @__PURE__ */ React.createElement("span", { style: { flex: 1, minWidth: 0 } }, /* @__PURE__ */ React.createElement("strong", { style: { display: "block", fontSize: 13 } }, "Marina Costa pediu atendimento humano"), /* @__PURE__ */ React.createElement("span", { style: { display: "block", marginTop: 3, color: "var(--foreground-75)", fontSize: 11 } }, "D\xFAvida sens\xEDvel sobre a sess\xE3o \xB7 esperando h\xE1 4 min")), /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-arrow-right", style: { color: "var(--primary)" } })), /* @__PURE__ */ React.createElement("div", { style: { marginTop: 12, padding: "13px 14px", background: "var(--muted-solid)", borderRadius: 6, display: "flex", gap: 10, alignItems: "center" } }, /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-shield-check", style: { color: "var(--success)", fontSize: 17 } }), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--foreground-75)" } }, "Nenhuma conversa sem resposta e nenhum alerta cr\xEDtico nas \xFAltimas 24 horas."))), /* @__PURE__ */ React.createElement("section", { style: { ..._surface, padding: 18 } }, /* @__PURE__ */ React.createElement(WhatsAyaSectionHeader, { title: "Pr\xF3ximas a\xE7\xF5es", subtitle: "Fila autom\xE1tica aprovada" }), [
      ["14:30", "Follow-up D+2", "Renata Lima"],
      ["16:00", "Retomar qualifica\xE7\xE3o", "Bianca Freitas"],
      ["Amanh\xE3", "Oferta final", "Carolina Dias"]
    ].map((item, index) => /* @__PURE__ */ React.createElement("div", { key: item[2], style: {
      display: "grid",
      gridTemplateColumns: "58px 1fr",
      gap: 10,
      padding: "11px 0",
      borderTop: index ? "1px solid var(--border-solid)" : "none"
    } }, /* @__PURE__ */ React.createElement("span", { style: { font: "600 11px/1.4 var(--font-numeric)", color: "var(--primary)" } }, item[0]), /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("strong", { style: { display: "block", fontSize: 12 } }, item[1]), /* @__PURE__ */ React.createElement("small", { style: { color: "var(--muted-foreground)" } }, item[2])))), /* @__PURE__ */ React.createElement(Button, { variant: "neutral", full: true, onClick: () => onNavigate("reactivation") }, "Abrir reativa\xE7\xE3o"))));
  }
  function WhatsAyaConversations() {
    const [selectedId, setSelectedId] = useWhatsAyaState("marina");
    const [query, setQuery] = useWhatsAyaState("");
    const [pausedIds, setPausedIds] = useWhatsAyaState(/* @__PURE__ */ new Set(["marina"]));
    const selected = WHATSAYA_CONTACTS.find((contact) => contact.id === selectedId) || WHATSAYA_CONTACTS[0];
    const visibleContacts = useWhatsAyaMemo(() => WHATSAYA_CONTACTS.filter((contact) => `${contact.name} ${contact.phone}`.toLowerCase().includes(query.toLowerCase())), [query]);
    const paused = pausedIds.has(selected.id);
    const togglePaused = () => {
      const next = new Set(pausedIds);
      paused ? next.delete(selected.id) : next.add(selected.id);
      setPausedIds(next);
    };
    return /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(
      WhatsAyaPageHeader,
      {
        eyebrow: "Atendimento",
        title: "Conversas",
        subtitle: "Hist\xF3rico do WhatsApp, contexto comercial e takeover humano em um \xFAnico lugar.",
        actions: /* @__PURE__ */ React.createElement(WhatsAyaStatus, { tone: "success" }, "WhatsApp conectado")
      }
    ), /* @__PURE__ */ React.createElement("div", { className: "wa-chat-layout", style: { ..._surface, display: "grid", gridTemplateColumns: "320px minmax(0, 1fr)", minHeight: 620, overflow: "hidden" } }, /* @__PURE__ */ React.createElement("aside", { style: { borderRight: "1px solid var(--border-solid)", minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { padding: 14, borderBottom: "1px solid var(--border-solid)" } }, /* @__PURE__ */ React.createElement(Input, { full: true, icon: "search", value: query, onChange: (event) => setQuery(event.target.value), placeholder: "Buscar conversa", label: "Leads" })), /* @__PURE__ */ React.createElement("div", { className: "wa-chat-list", style: { overflowY: "auto" } }, visibleContacts.map((contact) => {
      const active = contact.id === selected.id;
      return /* @__PURE__ */ React.createElement("button", { key: contact.id, onClick: () => setSelectedId(contact.id), style: {
        width: "100%",
        border: 0,
        borderBottom: "1px solid var(--border-solid)",
        borderLeft: active ? "3px solid var(--primary)" : "3px solid transparent",
        background: active ? "var(--warning-fade)" : "var(--card)",
        padding: "13px 12px",
        display: "flex",
        gap: 10,
        textAlign: "left",
        cursor: "pointer"
      } }, /* @__PURE__ */ React.createElement("span", { style: {
        width: 36,
        height: 36,
        borderRadius: 999,
        background: active ? "var(--primary)" : "var(--muted-solid)",
        color: active ? "var(--primary-foreground)" : "var(--foreground)",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        fontWeight: 700,
        fontSize: 11,
        flexShrink: 0
      } }, contact.initials), /* @__PURE__ */ React.createElement("span", { style: { flex: 1, minWidth: 0 } }, /* @__PURE__ */ React.createElement("span", { style: { display: "flex", justifyContent: "space-between", gap: 8 } }, /* @__PURE__ */ React.createElement("strong", { style: { fontSize: 12 } }, contact.name), /* @__PURE__ */ React.createElement("small", { style: { color: "var(--muted-foreground)" } }, contact.time)), /* @__PURE__ */ React.createElement("span", { style: { display: "block", marginTop: 4, fontSize: 11, color: "var(--foreground-75)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } }, contact.last), /* @__PURE__ */ React.createElement("span", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 7 } }, /* @__PURE__ */ React.createElement("small", { style: { color: "var(--muted-foreground)" } }, contact.stage), contact.unread > 0 && /* @__PURE__ */ React.createElement("span", { style: {
        minWidth: 18,
        height: 18,
        padding: "0 5px",
        borderRadius: 999,
        background: "var(--success)",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 10,
        fontWeight: 700
      } }, contact.unread))));
    }))), /* @__PURE__ */ React.createElement("section", { style: { minWidth: 0, display: "flex", flexDirection: "column", background: "var(--muted-solid)" } }, /* @__PURE__ */ React.createElement("header", { style: {
      padding: "13px 16px",
      background: "var(--card)",
      borderBottom: "1px solid var(--border-solid)",
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      gap: 12,
      flexWrap: "wrap"
    } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("strong", { style: { display: "block", fontSize: 13 } }, selected.name), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "var(--muted-foreground)" } }, selected.phone, " \xB7 ", selected.stage)), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8 } }, /* @__PURE__ */ React.createElement(WhatsAyaStatus, { tone: paused ? "warning" : "success" }, paused ? "Handoff humano" : "IA ativa"), /* @__PURE__ */ React.createElement(Button, { variant: paused ? "primary" : "outline", size: "sm", icon: paused ? "play" : "pause", onClick: togglePaused }, paused ? "Retomar IA" : "Pausar IA"))), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, padding: 20, display: "flex", flexDirection: "column", gap: 8, overflowY: "auto" } }, /* @__PURE__ */ React.createElement("div", { style: { alignSelf: "center", fontSize: 10, color: "var(--muted-foreground)", padding: "4px 9px", background: "var(--card)", borderRadius: 999 } }, "Hoje"), selected.messages.map((message, index) => {
      if (message.side === "system") {
        return /* @__PURE__ */ React.createElement("div", { key: index, style: {
          alignSelf: "center",
          maxWidth: 440,
          textAlign: "center",
          padding: "7px 11px",
          borderRadius: 6,
          background: "var(--success-fade)",
          border: "1px solid var(--success)",
          fontSize: 10
        } }, message.body);
      }
      const outgoing = message.side === "aya";
      return /* @__PURE__ */ React.createElement("div", { key: index, style: {
        alignSelf: outgoing ? "flex-end" : "flex-start",
        maxWidth: "72%",
        padding: "10px 12px",
        background: outgoing ? "var(--success-fade)" : "var(--card)",
        border: `1px solid ${outgoing ? "var(--success)" : "var(--border-solid)"}`,
        borderRadius: outgoing ? "8px 2px 8px 8px" : "2px 8px 8px 8px",
        fontSize: 12,
        lineHeight: 1.5
      } }, message.audio && /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-waveform-path", style: { marginRight: 7, color: "var(--primary)" } }), message.body, /* @__PURE__ */ React.createElement("small", { style: { display: "block", marginTop: 5, textAlign: "right", color: "var(--muted-foreground)", fontSize: 9 } }, message.time));
    })), /* @__PURE__ */ React.createElement("footer", { style: { padding: 14, background: "var(--card)", borderTop: "1px solid var(--border-solid)" } }, /* @__PURE__ */ React.createElement("div", { style: {
      border: "1px solid var(--border-solid)",
      borderRadius: 6,
      padding: "11px 12px",
      display: "flex",
      alignItems: "center",
      gap: 10,
      color: "var(--foreground-75)",
      background: "var(--muted-solid)",
      fontSize: 11
    } }, /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-lock" }), /* @__PURE__ */ React.createElement("span", { style: { flex: 1 } }, "Somente leitura. Responda pelo WhatsApp para manter o fluxo oficial de entrega e silenciar a IA automaticamente."), /* @__PURE__ */ React.createElement(Button, { variant: "neutral", size: "sm", icon: "comment-alt" }, "Abrir WhatsApp"))))));
  }
  function WhatsAyaPipeline({ onOpenConversation }) {
    const [query, setQuery] = useWhatsAyaState("");
    const columns = PIPELINE_COLUMNS.map((column) => ({
      ...column,
      cards: column.cards.filter((card) => card.name.toLowerCase().includes(query.toLowerCase()))
    }));
    return /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(
      WhatsAyaPageHeader,
      {
        eyebrow: "Comercial",
        title: "Pipeline de leads",
        subtitle: "A etapa organiza o pr\xF3ximo passo; mudan\xE7as no funil recalculam o follow-up da AYA.",
        actions: /* @__PURE__ */ React.createElement(Input, { icon: "search", value: query, onChange: (event) => setQuery(event.target.value), placeholder: "Buscar lead" })
      }
    ), /* @__PURE__ */ React.createElement("div", { className: "wa-pipeline", style: { display: "grid", gridTemplateColumns: "repeat(4, minmax(220px, 1fr))", gap: 12, alignItems: "start" } }, columns.map((column) => /* @__PURE__ */ React.createElement("section", { key: column.key, style: { background: "var(--muted-transparent)", border: "1px solid var(--border-solid)", borderRadius: 8, padding: 10 } }, /* @__PURE__ */ React.createElement("header", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "3px 4px 11px" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12, fontWeight: 700 } }, column.label), /* @__PURE__ */ React.createElement("span", { style: {
      minWidth: 22,
      height: 22,
      padding: "0 7px",
      borderRadius: 999,
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      background: "var(--card)",
      border: "1px solid var(--border-solid)",
      font: "600 10px/1 var(--font-numeric)"
    } }, column.cards.length)), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } }, column.cards.map((card) => /* @__PURE__ */ React.createElement("button", { key: card.name, onClick: onOpenConversation, style: { ..._surface, padding: 12, textAlign: "left", cursor: "pointer", width: "100%", boxShadow: card.attention ? "inset 3px 0 0 var(--primary), var(--shadow-hairline)" : "var(--shadow-hairline)" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 } }, /* @__PURE__ */ React.createElement("strong", { style: { fontSize: 12 } }, card.name), /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-menu-dots", style: { color: "var(--muted-foreground)" } })), /* @__PURE__ */ React.createElement("div", { style: { marginTop: 6, color: "var(--foreground-75)", fontSize: 10, lineHeight: 1.45 } }, card.detail), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6, marginTop: 11 } }, /* @__PURE__ */ React.createElement(WhatsAyaStatus, { tone: card.attention ? "warning" : card.success ? "success" : "neutral" }, card.badge), /* @__PURE__ */ React.createElement("small", { style: { color: "var(--muted-foreground)", fontSize: 9 } }, card.time)))), column.cards.length === 0 && /* @__PURE__ */ React.createElement("div", { style: { padding: 22, textAlign: "center", color: "var(--muted-foreground)", fontSize: 11 } }, "Nenhum lead"))))));
  }
  function WhatsAyaReactivation() {
    const [enabled, setEnabled] = useWhatsAyaState(false);
    const [jobs, setJobs] = useWhatsAyaState([
      { id: 1, name: "Renata Lima", step: "D+2", scheduled: "Hoje, 14:30", state: "Pronto", paused: false },
      { id: 2, name: "Carolina Dias", step: "Oferta final", scheduled: "Amanh\xE3, 10:15", state: "Aguardando", paused: false },
      { id: 3, name: "Vanessa Melo", step: "D+1", scheduled: "Amanh\xE3, 16:40", state: "Pausado", paused: true }
    ]);
    const toggleJob = (id) => setJobs(jobs.map((job) => job.id === id ? { ...job, paused: !job.paused, state: job.paused ? "Aguardando" : "Pausado" } : job));
    return /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(
      WhatsAyaPageHeader,
      {
        eyebrow: "Cad\xEAncia comercial",
        title: "Reativa\xE7\xE3o",
        subtitle: "Revise a fila herdada da Cl\xEDnica Horizonte antes de liberar qualquer envio autom\xE1tico.",
        actions: /* @__PURE__ */ React.createElement(WhatsAyaStatus, { tone: enabled ? "success" : "warning" }, enabled ? "Cad\xEAncia ativa" : "Aguardando aprova\xE7\xE3o")
      }
    ), /* @__PURE__ */ React.createElement("section", { style: { ..._surface, padding: 18, marginBottom: 16, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 18, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 12, alignItems: "center" } }, /* @__PURE__ */ React.createElement("span", { style: {
      width: 38,
      height: 38,
      borderRadius: 8,
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      background: enabled ? "var(--success-fade)" : "var(--warning-fade)",
      color: enabled ? "var(--success)" : "var(--primary)"
    } }, /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-rotate-right" })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("strong", { style: { display: "block", fontSize: 13 } }, "Automa\xE7\xE3o de reativa\xE7\xE3o"), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--muted-foreground)", fontSize: 11 } }, "Janela de 72h \xB7 opt-out e takeover respeitados"))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 10 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 600 } }, enabled ? "Ligada" : "Desligada"), /* @__PURE__ */ React.createElement(WhatsAyaToggle, { checked: enabled, onChange: () => setEnabled(!enabled), label: "Alternar automa\xE7\xE3o de reativa\xE7\xE3o" }))), /* @__PURE__ */ React.createElement("section", { style: { ..._surface, padding: 18 } }, /* @__PURE__ */ React.createElement(
      WhatsAyaSectionHeader,
      {
        title: "Fila preparada",
        subtitle: "3 contatos \xB7 nenhuma mensagem foi enviada nesta pr\xE9via",
        action: /* @__PURE__ */ React.createElement(Button, { variant: "outline", size: "sm", icon: "settings" }, "Editar pol\xEDtica")
      }
    ), /* @__PURE__ */ React.createElement("div", { style: { overflowX: "auto" } }, /* @__PURE__ */ React.createElement("table", { style: { width: "100%", borderCollapse: "collapse", minWidth: 620 } }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", { style: { background: "var(--muted-solid)" } }, ["Lead", "Etapa", "Programado para", "Estado", "A\xE7\xE3o"].map((label) => /* @__PURE__ */ React.createElement("th", { key: label, style: { padding: "10px 12px", textAlign: "left", fontSize: 10, fontWeight: 700, borderBottom: "1px solid var(--border-solid)" } }, label)))), /* @__PURE__ */ React.createElement("tbody", null, jobs.map((job) => /* @__PURE__ */ React.createElement("tr", { key: job.id, style: { borderBottom: "1px solid var(--border-solid)" } }, /* @__PURE__ */ React.createElement("td", { style: { padding: 12, fontSize: 12, fontWeight: 600 } }, job.name), /* @__PURE__ */ React.createElement("td", { style: { padding: 12, fontSize: 11 } }, job.step), /* @__PURE__ */ React.createElement("td", { style: { padding: 12, font: "600 11px/1.4 var(--font-numeric)" } }, job.scheduled), /* @__PURE__ */ React.createElement("td", { style: { padding: 12 } }, /* @__PURE__ */ React.createElement(WhatsAyaStatus, { tone: job.paused ? "warning" : job.state === "Pronto" ? "success" : "neutral" }, job.state)), /* @__PURE__ */ React.createElement("td", { style: { padding: 12 } }, /* @__PURE__ */ React.createElement(Button, { variant: "ghost", size: "sm", icon: job.paused ? "play" : "pause", onClick: () => toggleJob(job.id) }, job.paused ? "Retomar" : "Pausar")))))))));
  }
  function WhatsAyaSettingRow({ icon, title, description, checked, onChange, detail }) {
    return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 12, padding: "14px 0", borderTop: "1px solid var(--border-solid)" } }, /* @__PURE__ */ React.createElement("span", { style: { width: 32, height: 32, borderRadius: 6, background: "var(--muted-solid)", display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0 } }, /* @__PURE__ */ React.createElement("i", { className: `fi fi-rr-${icon}`, style: { fontSize: 14 } })), /* @__PURE__ */ React.createElement("span", { style: { flex: 1, minWidth: 0 } }, /* @__PURE__ */ React.createElement("strong", { style: { display: "block", fontSize: 12 } }, title), /* @__PURE__ */ React.createElement("small", { style: { display: "block", marginTop: 3, color: "var(--muted-foreground)", lineHeight: 1.45 } }, description)), detail || /* @__PURE__ */ React.createElement(WhatsAyaToggle, { checked, onChange, label: `Alternar ${title}` }));
  }
  function WhatsAyaOperations({ botPaused, onToggleBot }) {
    const [rejectCalls, setRejectCalls] = useWhatsAyaState(true);
    const [groups, setGroups] = useWhatsAyaState(false);
    const [audio, setAudio] = useWhatsAyaState(true);
    const [media, setMedia] = useWhatsAyaState(true);
    const [notifications, setNotifications] = useWhatsAyaState(true);
    const [rollout, setRollout] = useWhatsAyaState("10");
    return /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(
      WhatsAyaPageHeader,
      {
        eyebrow: "Opera\xE7\xE3o",
        title: "Configura\xE7\xF5es",
        subtitle: "Controles seguros para conex\xE3o, automa\xE7\xE3o e integra\xE7\xF5es do fluxo Cl\xEDnica Horizonte.",
        actions: /* @__PURE__ */ React.createElement(Button, { variant: "primary", icon: "disk" }, "Salvar altera\xE7\xF5es")
      }
    ), /* @__PURE__ */ React.createElement("section", { style: { ..._surface, padding: 18, marginBottom: 16, borderColor: botPaused ? "var(--primary)" : "var(--success)" } }, /* @__PURE__ */ React.createElement(WhatsAyaSectionHeader, { title: "Estado geral", subtitle: "O kill switch interrompe respostas autom\xE1ticas para todos os leads." }), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 10 } }, /* @__PURE__ */ React.createElement(WhatsAyaStatus, { tone: botPaused ? "warning" : "success" }, botPaused ? "IA pausada globalmente" : "IA ativa"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--muted-foreground)" } }, "WhatsApp conectado \xB7 bridge saud\xE1vel")), /* @__PURE__ */ React.createElement(Button, { variant: botPaused ? "primary" : "outline", icon: botPaused ? "play" : "pause", onClick: onToggleBot }, botPaused ? "Retomar atendimento" : "Pausar IA"))), /* @__PURE__ */ React.createElement("div", { className: "wa-settings-grid", style: { display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 } }, /* @__PURE__ */ React.createElement("section", { style: { ..._surface, padding: 18 } }, /* @__PURE__ */ React.createElement(WhatsAyaSectionHeader, { title: "WhatsApp", subtitle: "Aplicado pela ponte em tempo real" }), /* @__PURE__ */ React.createElement(WhatsAyaSettingRow, { icon: "phone-call", title: "Recusar liga\xE7\xF5es", description: "Evita que chamadas interrompam o atendimento.", checked: rejectCalls, onChange: () => setRejectCalls(!rejectCalls) }), /* @__PURE__ */ React.createElement(WhatsAyaSettingRow, { icon: "users-alt", title: "Processar grupos", description: "Mant\xE9m a AYA fora de grupos por padr\xE3o.", checked: groups, onChange: () => setGroups(!groups) }), /* @__PURE__ */ React.createElement(
      WhatsAyaSettingRow,
      {
        icon: "hourglass-end",
        title: "Espera inicial",
        description: "Agrupa mensagens picadas antes de responder.",
        detail: /* @__PURE__ */ React.createElement("span", { style: { font: "600 11px/1 var(--font-numeric)", padding: "8px 10px", background: "var(--muted-solid)", borderRadius: 4 } }, "8 segundos")
      }
    )), /* @__PURE__ */ React.createElement("section", { style: { ..._surface, padding: 18 } }, /* @__PURE__ */ React.createElement(WhatsAyaSectionHeader, { title: "Intelig\xEAncia", subtitle: "Comportamento do atendimento" }), /* @__PURE__ */ React.createElement(WhatsAyaSettingRow, { icon: "waveform-path", title: "Transcrever \xE1udios", description: "Usa transcri\xE7\xE3o antes de seguir o funil.", checked: audio, onChange: () => setAudio(!audio) }), /* @__PURE__ */ React.createElement(WhatsAyaSettingRow, { icon: "picture", title: "M\xEDdia e prova social", description: "Libera apenas os materiais aprovados no manifesto.", checked: media, onChange: () => setMedia(!media) }), /* @__PURE__ */ React.createElement(WhatsAyaSettingRow, { icon: "bell", title: "Avisar Dr. Exemplo", description: "Notifica em handoff, agenda e falha silenciosa.", checked: notifications, onChange: () => setNotifications(!notifications) })), /* @__PURE__ */ React.createElement("section", { style: { ..._surface, padding: 18 } }, /* @__PURE__ */ React.createElement(WhatsAyaSectionHeader, { title: "Rollout gradual", subtitle: "Percentual determin\xEDstico de novos leads atendidos pela IA" }), /* @__PURE__ */ React.createElement("div", { className: "wa-form-row", style: { display: "grid", gridTemplateColumns: "1fr 120px", gap: 12, alignItems: "end" } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { height: 8, borderRadius: 999, background: "var(--muted-solid)", overflow: "hidden", marginBottom: 8 } }, /* @__PURE__ */ React.createElement("div", { style: { width: `${rollout}%`, height: "100%", background: "var(--primary)" } })), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--muted-foreground)" } }, rollout, "% autom\xE1tico \xB7 ", 100 - Number(rollout), "% direto para atendimento humano")), /* @__PURE__ */ React.createElement(Select, { full: true, label: "Percentual", value: rollout, onChange: (event) => setRollout(event.target.value), options: [
      { value: "5", label: "5%" },
      { value: "10", label: "10%" },
      { value: "25", label: "25%" },
      { value: "50", label: "50%" },
      { value: "100", label: "100%" }
    ] }))), /* @__PURE__ */ React.createElement("section", { style: { ..._surface, padding: 18 } }, /* @__PURE__ */ React.createElement(WhatsAyaSectionHeader, { title: "Agenda e hor\xE1rios", subtitle: "Requer reconcilia\xE7\xE3o antes do corte para produ\xE7\xE3o" }), /* @__PURE__ */ React.createElement(
      WhatsAyaSettingRow,
      {
        icon: "calendar",
        title: "Google Calendar",
        description: "Disponibilidade e cria\xE7\xE3o de evento.",
        detail: /* @__PURE__ */ React.createElement(WhatsAyaStatus, { tone: "warning" }, "Autoriza\xE7\xE3o pendente")
      }
    ), /* @__PURE__ */ React.createElement(
      WhatsAyaSettingRow,
      {
        icon: "clock",
        title: "Hor\xE1rio comercial",
        description: "Segunda a sexta \xB7 America/Sao_Paulo",
        detail: /* @__PURE__ */ React.createElement("span", { style: { font: "600 11px/1 var(--font-numeric)" } }, "09:00\u201319:00")
      }
    ))));
  }
  var AGENDA_DAYS = [
    { id: 1, name: "Seg", date: "08 Set", full: "Segunda-feira", isToday: false },
    { id: 2, name: "Ter", date: "09 Set", full: "Ter\xE7a-feira", isToday: true },
    { id: 3, name: "Qua", date: "10 Set", full: "Quarta-feira", isToday: false },
    { id: 4, name: "Qui", date: "11 Set", full: "Quinta-feira", isToday: false },
    { id: 5, name: "Sex", date: "12 Set", full: "Sexta-feira", isToday: false },
    { id: 6, name: "S\xE1b", date: "13 Set", full: "S\xE1bado", isToday: false, dim: true },
    { id: 7, name: "Dom", date: "14 Set", full: "Domingo", isToday: false, dim: true }
  ];
  var AGENDA_EVENTS = [
    {
      id: "ev-1",
      dayId: 1,
      start: "09:00",
      end: "10:00",
      startHour: 9,
      startMin: 0,
      durationMin: 60,
      kind: "busy",
      title: "Ocupado",
      subtitle: "Compromisso particular"
    },
    {
      id: "ev-2",
      dayId: 1,
      start: "11:00",
      end: "11:50",
      startHour: 11,
      startMin: 0,
      durationMin: 50,
      kind: "slot",
      title: "Hor\xE1rio livre",
      subtitle: "Dispon\xEDvel para oferta da IA"
    },
    {
      id: "ev-3",
      dayId: 2,
      start: "10:00",
      end: "10:50",
      startHour: 10,
      startMin: 0,
      durationMin: 50,
      kind: "slot",
      title: "Hor\xE1rio livre",
      subtitle: "Dispon\xEDvel para oferta da IA"
    },
    {
      id: "ev-4",
      dayId: 2,
      start: "15:00",
      end: "15:50",
      startHour: 15,
      startMin: 0,
      durationMin: 50,
      kind: "booking",
      title: "Marina Costa",
      subtitle: "Sess\xE3o individual confirmada",
      leadPhone: "(11) 9 8123-4401",
      meetUrl: "https://meet.google.com/abc-defg-hij",
      gcalUrl: "https://calendar.google.com"
    },
    {
      id: "ev-5",
      dayId: 3,
      start: "10:00",
      end: "10:50",
      startHour: 10,
      startMin: 0,
      durationMin: 50,
      kind: "booking",
      title: "Paula Mendes",
      subtitle: "Sess\xE3o inicial agendada",
      leadPhone: "(21) 9 7402-1830",
      meetUrl: "https://meet.google.com/xyz-uvwx-rst",
      gcalUrl: "https://calendar.google.com"
    },
    {
      id: "ev-6",
      dayId: 3,
      start: "13:00",
      end: "14:30",
      startHour: 13,
      startMin: 0,
      durationMin: 90,
      kind: "block",
      title: "Bloqueado",
      subtitle: "Supervis\xE3o cl\xEDnica"
    },
    {
      id: "ev-7",
      dayId: 4,
      start: "14:00",
      end: "14:50",
      startHour: 14,
      startMin: 0,
      durationMin: 50,
      kind: "slot",
      title: "Hor\xE1rio livre",
      subtitle: "Dispon\xEDvel para oferta da IA"
    },
    {
      id: "ev-8",
      dayId: 4,
      start: "16:00",
      end: "16:50",
      startHour: 16,
      startMin: 0,
      durationMin: 50,
      kind: "booking",
      title: "Renata Lima",
      subtitle: "Follow-up de alinhamento",
      leadPhone: "(41) 9 5330-1188",
      meetUrl: "https://meet.google.com/mnp-qrst-uvw",
      gcalUrl: "https://calendar.google.com"
    },
    {
      id: "ev-9",
      dayId: 5,
      start: "11:00",
      end: "11:50",
      startHour: 11,
      startMin: 0,
      durationMin: 50,
      kind: "slot",
      title: "Hor\xE1rio livre",
      subtitle: "Dispon\xEDvel para oferta da IA"
    },
    {
      id: "ev-10",
      dayId: 5,
      start: "15:00",
      end: "15:50",
      startHour: 15,
      startMin: 0,
      durationMin: 50,
      kind: "slot",
      title: "Hor\xE1rio livre",
      subtitle: "Dispon\xEDvel para oferta da IA"
    }
  ];
  function WhatsAyaAgenda() {
    const [selectedEvent, setSelectedEvent] = useWhatsAyaState(null);
    const [showSettings, setShowSettings] = useWhatsAyaState(false);
    const [mode, setMode] = useWhatsAyaState("explicit_slots");
    const [slotDuration, setSlotDuration] = useWhatsAyaState("50");
    const HOURS = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18];
    const HOUR_HEIGHT = 56;
    return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 20 } }, /* @__PURE__ */ React.createElement(
      WhatsAyaPageHeader,
      {
        eyebrow: "Agenda & Hor\xE1rios",
        title: "Agenda de Atendimento",
        subtitle: "Integra\xE7\xE3o bidirecional com Google Calendar. Vagas de consulta e sess\xF5es agendadas automaticamente pela AYA.",
        actions: /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8 } }, /* @__PURE__ */ React.createElement(Button, { variant: "outline", icon: "settings", onClick: () => setShowSettings(!showSettings) }, showSettings ? "Ocultar regras" : "Regras da agenda"), /* @__PURE__ */ React.createElement(Button, { variant: "primary", icon: "refresh" }, "Sincronizar Google"))
      }
    ), /* @__PURE__ */ React.createElement("section", { style: {
      ..._surface,
      padding: "14px 18px",
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      flexWrap: "wrap",
      gap: 12,
      background: "var(--card)",
      borderColor: "var(--border-solid)"
    } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 12 } }, /* @__PURE__ */ React.createElement("span", { style: {
      width: 34,
      height: 34,
      borderRadius: 8,
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      background: "var(--success-fade)",
      color: "var(--success)"
    } }, /* @__PURE__ */ React.createElement("i", { className: "fi fi-rr-calendar-check", style: { fontSize: 16 } })), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 13, fontWeight: 700 } }, "Google Agenda Conectado"), /* @__PURE__ */ React.createElement(WhatsAyaStatus, { tone: "success" }, "Ativo")), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--muted-foreground)", marginTop: 2 } }, "Sincronizando com ", /* @__PURE__ */ React.createElement("strong", null, "primary"), " (agenda@clinica-exemplo.com.br) \xB7 Fuso: America/Sao_Paulo"))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12, color: "var(--muted-foreground)" } }, "Modo: ", /* @__PURE__ */ React.createElement("strong", null, mode === "explicit_slots" ? 'Vagas expl\xEDcitas ("Livre")' : "Intervalos livres")))), showSettings && /* @__PURE__ */ React.createElement("section", { style: { ..._surface, padding: 18, background: "var(--card-subtle, var(--card))" } }, /* @__PURE__ */ React.createElement(
      WhatsAyaSectionHeader,
      {
        title: "Regras de Disponibilidade e Agendamento",
        subtitle: "Configura\xE7\xE3o at\xF4mica compartilhada entre o painel e o rob\xF4 sem necessidade de reiniciar cont\xEAineres."
      }
    ), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16, marginTop: 12 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { style: { fontSize: 11, fontWeight: 700, display: "block", marginBottom: 6 } }, "Modo de Disponibilidade"), /* @__PURE__ */ React.createElement(Select, { full: true, value: mode, onChange: (e) => setMode(e.target.value), options: [
      { value: "explicit_slots", label: 'Vagas expl\xEDcitas (Palavra "Livre")' },
      { value: "freebusy_gaps", label: "Intervalos livres do expediente (FreeBusy)" }
    ] }), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--muted-foreground)", display: "block", marginTop: 4 } }, mode === "explicit_slots" ? 'Apenas hor\xE1rios marcados com "Livre" na agenda do profissional s\xE3o oferecidos aos leads.' : "Qualquer buraco na agenda durante o expediente pode ser oferecido.")), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { style: { fontSize: 11, fontWeight: 700, display: "block", marginBottom: 6 } }, "Dura\xE7\xE3o da Sess\xE3o"), /* @__PURE__ */ React.createElement(Select, { full: true, value: slotDuration, onChange: (e) => setSlotDuration(e.target.value), options: [
      { value: "30", label: "30 minutos" },
      { value: "50", label: "50 minutos (padr\xE3o cl\xEDnica)" },
      { value: "60", label: "60 minutos (1 hora)" }
    ] }), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--muted-foreground)", display: "block", marginTop: 4 } }, "Tempo reservado em cada agendamento no Google Calendar.")), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { style: { fontSize: 11, fontWeight: 700, display: "block", marginBottom: 6 } }, "Anteced\xEAncia M\xEDnima"), /* @__PURE__ */ React.createElement(Select, { full: true, value: "120", options: [
      { value: "60", label: "1 hora de anteced\xEAncia" },
      { value: "120", label: "2 horas de anteced\xEAncia" },
      { value: "360", label: "6 horas de anteced\xEAncia" },
      { value: "1440", label: "24 horas de anteced\xEAncia" }
    ] }), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "var(--muted-foreground)", display: "block", marginTop: 4 } }, "Evita que a IA marque reuni\xF5es em cima da hora sem tempo h\xE1bil.")))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "inline-flex", borderRadius: 6, border: "1px solid var(--border-solid)", overflow: "hidden" } }, /* @__PURE__ */ React.createElement(Button, { variant: "ghost", icon: "angle-left" }), /* @__PURE__ */ React.createElement(Button, { variant: "ghost", icon: "angle-right" })), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 14, fontWeight: 700 } }, "08 de Setembro \u2013 14 de Setembro de 2026"), /* @__PURE__ */ React.createElement(Button, { variant: "outline" }, "Hoje")), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, fontSize: 11, fontWeight: 600, color: "var(--muted-foreground)" } }, /* @__PURE__ */ React.createElement("span", { style: { width: 10, height: 10, borderRadius: 3, background: "var(--primary)", display: "inline-block" } }), /* @__PURE__ */ React.createElement("span", null, "Agendado pela AYA")), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, fontSize: 11, fontWeight: 600, color: "var(--muted-foreground)" } }, /* @__PURE__ */ React.createElement("span", { style: { width: 10, height: 10, borderRadius: 3, background: "rgba(76, 222, 89, 0.2)", border: "1px dashed var(--success)", display: "inline-block" } }), /* @__PURE__ */ React.createElement("span", null, "Vaga livre")), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6, fontSize: 11, fontWeight: 600, color: "var(--muted-foreground)" } }, /* @__PURE__ */ React.createElement("span", { style: { width: 10, height: 10, borderRadius: 3, background: "var(--muted-solid)", display: "inline-block" } }), /* @__PURE__ */ React.createElement("span", null, "Compromisso / Bloqueio")))), /* @__PURE__ */ React.createElement("div", { style: { ..._surface, overflow: "hidden" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "60px repeat(7, minmax(120px, 1fr))", borderBottom: "1px solid var(--border-solid)" } }, /* @__PURE__ */ React.createElement("div", { style: { padding: 10, borderRight: "1px solid var(--border-solid)" } }), AGENDA_DAYS.map((d) => /* @__PURE__ */ React.createElement("div", { key: d.id, style: {
      padding: "10px 8px",
      textAlign: "center",
      borderRight: "1px solid var(--border-solid)",
      background: d.isToday ? "var(--muted-solid)" : d.dim ? "hsl(var(--shadow-tint) / .03)" : "transparent"
    } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, textTransform: "uppercase", fontWeight: 700, color: "var(--muted-foreground)" } }, d.name), /* @__PURE__ */ React.createElement("div", { style: {
      fontSize: 14,
      fontWeight: 800,
      marginTop: 2,
      display: "inline-flex",
      width: 26,
      height: 26,
      alignItems: "center",
      justifyContent: "center",
      borderRadius: "50%",
      background: d.isToday ? "var(--primary)" : "transparent",
      color: d.isToday ? "var(--primary-foreground)" : "inherit"
    } }, d.date.split(" ")[0])))), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "60px repeat(7, minmax(120px, 1fr))", position: "relative", minHeight: HOURS.length * HOUR_HEIGHT } }, /* @__PURE__ */ React.createElement("div", { style: { borderRight: "1px solid var(--border-solid)" } }, HOURS.map((h) => /* @__PURE__ */ React.createElement("div", { key: h, style: {
      height: HOUR_HEIGHT,
      boxSizing: "border-box",
      borderTop: "1px solid var(--border-solid)",
      fontSize: 10,
      fontWeight: 600,
      color: "var(--muted-foreground)",
      paddingRight: 6,
      paddingTop: 2,
      textAlign: "right"
    } }, String(h).padStart(2, "0"), ":00"))), AGENDA_DAYS.map((day) => {
      const dayEvents = AGENDA_EVENTS.filter((ev) => ev.dayId === day.id);
      return /* @__PURE__ */ React.createElement("div", { key: day.id, style: {
        position: "relative",
        borderRight: "1px solid var(--border-solid)",
        background: day.isToday ? "rgb(242 110 34 / .05)" : day.dim ? "hsl(var(--shadow-tint) / .02)" : "transparent"
      } }, HOURS.map((h) => /* @__PURE__ */ React.createElement("div", { key: h, style: { height: HOUR_HEIGHT, boxSizing: "border-box", borderTop: "1px solid var(--border-solid)" } })), dayEvents.map((ev) => {
        const top = (ev.startHour - HOURS[0] + ev.startMin / 60) * HOUR_HEIGHT;
        const height = ev.durationMin / 60 * HOUR_HEIGHT - 3;
        const isBooking = ev.kind === "booking";
        const isSlot = ev.kind === "slot";
        return /* @__PURE__ */ React.createElement(
          "div",
          {
            key: ev.id,
            onClick: () => setSelectedEvent(ev),
            style: {
              position: "absolute",
              top: `${top}px`,
              left: "4px",
              right: "4px",
              height: `${height}px`,
              borderRadius: 6,
              padding: "4px 6px",
              boxSizing: "border-box",
              cursor: "pointer",
              background: isBooking ? "var(--warning-fade)" : isSlot ? "rgba(76, 222, 89, 0.09)" : "var(--muted-solid)",
              border: isBooking ? "1px solid var(--primary)" : isSlot ? "1.5px dashed var(--success)" : "1px solid var(--border-solid)",
              color: isBooking ? "var(--foreground)" : isSlot ? "var(--success)" : "var(--muted-foreground)",
              fontSize: 11,
              display: "flex",
              flexDirection: "column",
              gap: 1,
              overflow: "hidden",
              boxShadow: isBooking ? "0 1px 2px var(--primary-20), var(--shadow-hairline)" : "none"
            }
          },
          /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between" } }, /* @__PURE__ */ React.createElement("span", { style: { font: "700 10px/1 var(--font-numeric)" } }, ev.start, " \u2013 ", ev.end), isBooking && /* @__PURE__ */ React.createElement("span", { style: { background: "var(--primary)", color: "var(--primary-foreground)", fontSize: 8, fontWeight: 800, padding: "1px 4px", borderRadius: 4 } }, "AYA")),
          /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 700, textOverflow: "ellipsis", whiteSpace: "nowrap", overflow: "hidden" } }, ev.title),
          /* @__PURE__ */ React.createElement("div", { style: { fontSize: 9.5, opacity: 0.85, textOverflow: "ellipsis", whiteSpace: "nowrap", overflow: "hidden" } }, ev.subtitle)
        );
      }));
    }))), selectedEvent && /* @__PURE__ */ React.createElement("div", { style: {
      position: "fixed",
      inset: 0,
      zIndex: "var(--z-modal)",
      background: "var(--backdrop)",
      animation: "aya-fade var(--duration-fast) var(--ease-out)",
      display: "flex",
      justifyContent: "flex-end"
    } }, /* @__PURE__ */ React.createElement("div", { style: {
      width: 380,
      maxWidth: "92vw",
      height: "100%",
      background: "var(--dialog)",
      boxShadow: "var(--shadow-lg)",
      padding: 24,
      display: "flex",
      flexDirection: "column",
      gap: 16,
      overflowY: "auto"
    } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 700, textTransform: "uppercase", color: "var(--muted-foreground)" } }, "Detalhes do hor\xE1rio"), selectedEvent.kind === "booking" && /* @__PURE__ */ React.createElement(WhatsAyaStatus, { tone: "warning" }, "Agendado pela AYA"), selectedEvent.kind === "slot" && /* @__PURE__ */ React.createElement(WhatsAyaStatus, { tone: "success" }, "Vaga Livre")), /* @__PURE__ */ React.createElement(Button, { variant: "ghost", icon: "cross", onClick: () => setSelectedEvent(null) })), /* @__PURE__ */ React.createElement("h2", { style: { margin: 0, font: "600 20px/1.2 var(--font-sans)" } }, selectedEvent.title), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, color: "var(--muted-foreground)" } }, selectedEvent.subtitle), /* @__PURE__ */ React.createElement("div", { style: { ..._surface, padding: 14, display: "flex", flexDirection: "column", gap: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "space-between", fontSize: 12 } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--muted-foreground)" } }, "Hor\xE1rio:"), /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700 } }, selectedEvent.start, " \xE0s ", selectedEvent.end)), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "space-between", fontSize: 12 } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--muted-foreground)" } }, "Dura\xE7\xE3o:"), /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700 } }, selectedEvent.durationMin, " minutos")), selectedEvent.leadPhone && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "space-between", fontSize: 12 } }, /* @__PURE__ */ React.createElement("span", { style: { color: "var(--muted-foreground)" } }, "WhatsApp do Lead:"), /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700, fontVariantNumeric: "tabular-nums" } }, selectedEvent.leadPhone))), selectedEvent.meetUrl && /* @__PURE__ */ React.createElement("a", { href: selectedEvent.meetUrl, target: "_blank", rel: "noreferrer", style: { textDecoration: "none" } }, /* @__PURE__ */ React.createElement(Button, { variant: "primary", full: true, icon: "video-camera" }, "Entrar na Sess\xE3o (Google Meet)")), selectedEvent.gcalUrl && /* @__PURE__ */ React.createElement("a", { href: selectedEvent.gcalUrl, target: "_blank", rel: "noreferrer", style: { textDecoration: "none" } }, /* @__PURE__ */ React.createElement(Button, { variant: "outline", full: true, icon: "calendar" }, "Ver no Google Agenda")), /* @__PURE__ */ React.createElement("div", { style: { marginTop: "auto", paddingTop: 16, borderTop: "1px solid var(--border-solid)" } }, /* @__PURE__ */ React.createElement(Button, { variant: "ghost", full: true, icon: "trash", onClick: () => setSelectedEvent(null) }, "Fechar detalhes")))));
  }
  function WhatsAyaLogin() {
    const [username, setUsername] = useWhatsAyaState("admin");
    const [password, setPassword] = useWhatsAyaState("");
    const [showPassword, setShowPassword] = useWhatsAyaState(false);
    const [loading, setLoading] = useWhatsAyaState(false);
    const [feedback, setFeedback] = useWhatsAyaState(null);
    const handleLogin = (e) => {
      e.preventDefault();
      setLoading(true);
      setFeedback(null);
      setTimeout(() => {
        setLoading(false);
        if (password === "correta" || password.length > 5) {
          setFeedback({ type: "success", text: "Autenticado com sucesso! Redirecionando para o painel\u2026" });
        } else {
          setFeedback({ type: "error", text: "Usu\xE1rio ou senha incorretos. Verifique suas credenciais." });
        }
      }, 800);
    };
    return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 20 } }, /* @__PURE__ */ React.createElement(
      WhatsAyaPageHeader,
      {
        eyebrow: "Seguran\xE7a & Acesso",
        title: "Tela de Autentica\xE7\xE3o (Login)",
        subtitle: "Apresenta\xE7\xE3o da interface de login mobile-first com cookie seguro HMAC-SHA256 e identidade visual customiz\xE1vel por cliente.",
        actions: /* @__PURE__ */ React.createElement(Button, { variant: "outline", icon: "shield-check" }, "Sess\xE3o Segura (30 dias)")
      }
    ), /* @__PURE__ */ React.createElement("div", { style: {
      minHeight: 520,
      borderRadius: 12,
      padding: "40px 20px",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: "radial-gradient(at 50% 0%, rgba(242, 110, 34, 0.08) 0px, transparent 65%), radial-gradient(at 90% 100%, rgba(76, 222, 89, 0.06) 0px, transparent 55%), var(--muted-solid)",
      border: "1px solid var(--border-solid)"
    } }, /* @__PURE__ */ React.createElement("div", { style: { width: "100%", maxWidth: 360, display: "flex", flexDirection: "column", gap: 14 } }, /* @__PURE__ */ React.createElement("div", { style: {
      alignSelf: "center",
      display: "inline-flex",
      alignItems: "center",
      gap: 8,
      padding: "6px 14px",
      borderRadius: 999,
      background: "rgba(255, 255, 255, 0.85)",
      backdropFilter: "blur(10px)",
      border: "1px solid var(--border-solid)",
      fontSize: 11.5,
      fontWeight: 700,
      color: "var(--foreground)",
      boxShadow: "var(--shadow-xs)"
    } }, /* @__PURE__ */ React.createElement("span", { style: { width: 7, height: 7, borderRadius: "50%", background: "var(--success)" } }), /* @__PURE__ */ React.createElement("span", null, "Acesso seguro com criptografia")), /* @__PURE__ */ React.createElement("div", { style: {
      background: "var(--card)",
      border: "1px solid var(--border-solid)",
      borderRadius: 12,
      padding: "28px 24px",
      boxShadow: "var(--shadow-lg)",
      display: "flex",
      flexDirection: "column",
      gap: 18
    } }, /* @__PURE__ */ React.createElement("div", { style: { textAlign: "center" } }, /* @__PURE__ */ React.createElement("div", { style: {
      width: 44,
      height: 44,
      borderRadius: 10,
      background: "var(--primary)",
      color: "var(--primary-foreground)",
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      fontWeight: 900,
      fontSize: 18,
      marginBottom: 10
    } }, "A"), /* @__PURE__ */ React.createElement("h2", { style: { margin: 0, font: "700 20px/1.2 var(--font-sans)", letterSpacing: "-0.02em" } }, "WhatsAYA"), /* @__PURE__ */ React.createElement("p", { style: { margin: "4px 0 0", fontSize: 12, color: "var(--muted-foreground)" } }, "Entre para gerenciar leads, conversas e agenda")), feedback && /* @__PURE__ */ React.createElement("div", { style: {
      padding: "10px 12px",
      borderRadius: 6,
      fontSize: 12,
      fontWeight: 600,
      background: feedback.type === "success" ? "var(--success-fade)" : "var(--warning-fade)",
      border: `1px solid ${feedback.type === "success" ? "var(--success)" : "var(--warning)"}`,
      color: feedback.type === "success" ? "var(--success)" : "var(--primary)"
    } }, feedback.text), /* @__PURE__ */ React.createElement("form", { onSubmit: handleLogin, style: { display: "flex", flexDirection: "column", gap: 14 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { style: { fontSize: 11.5, fontWeight: 700, display: "block", marginBottom: 5 } }, "Usu\xE1rio"), /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "text",
        value: username,
        onChange: (e) => setUsername(e.target.value),
        style: {
          width: "100%",
          height: 38,
          borderRadius: 6,
          border: "1px solid var(--hairline-strong)",
          padding: "0 12px",
          fontSize: 13,
          background: "var(--input-bg)",
          color: "var(--foreground)",
          boxSizing: "border-box"
        }
      }
    )), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "space-between", marginBottom: 5 } }, /* @__PURE__ */ React.createElement("label", { style: { fontSize: 11.5, fontWeight: 700 } }, "Senha"), /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        onClick: () => setShowPassword(!showPassword),
        style: { background: "transparent", border: 0, fontSize: 11, color: "var(--primary)", cursor: "pointer", padding: 0 }
      },
      showPassword ? "Ocultar" : "Mostrar"
    )), /* @__PURE__ */ React.createElement(
      "input",
      {
        type: showPassword ? "text" : "password",
        value: password,
        placeholder: "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022",
        onChange: (e) => setPassword(e.target.value),
        style: {
          width: "100%",
          height: 38,
          borderRadius: 6,
          border: "1px solid var(--hairline-strong)",
          padding: "0 12px",
          fontSize: 13,
          background: "var(--input-bg)",
          color: "var(--foreground)",
          boxSizing: "border-box"
        }
      }
    )), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 11.5 } }, /* @__PURE__ */ React.createElement("label", { style: { display: "flex", alignItems: "center", gap: 6, cursor: "pointer" } }, /* @__PURE__ */ React.createElement("input", { type: "checkbox", defaultChecked: true, style: { accentColor: "var(--primary)", width: 16, height: 16, margin: 0 } }), /* @__PURE__ */ React.createElement("span", null, "Lembrar neste dispositivo")), /* @__PURE__ */ React.createElement("span", { style: { color: "var(--muted-foreground)" } }, "30 dias")), /* @__PURE__ */ React.createElement(Button, { type: "submit", variant: "primary", full: true, loading, icon: "arrow-right" }, loading ? "Autenticando\u2026" : "Acessar painel"))))));
  }
  Object.assign(window, {
    WhatsAyaOverview,
    WhatsAyaConversations,
    WhatsAyaPipeline,
    WhatsAyaAgenda,
    WhatsAyaReactivation,
    WhatsAyaOperations,
    WhatsAyaLogin
  });
})();
