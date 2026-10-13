import { useId, useRef } from "react";

// Accessible tabs: [{ id, label, content }], with the `active` tab id controlled by the
// parent. Every panel stays mounted (hidden when inactive) so inputs inside keep their
// state when the user switches tabs.
export default function Tabs({ tabs, label, active, onChange: setActive }) {
  const buttons = useRef({});
  const prefix = useId();

  // Arrow keys move between tabs, Home/End jump to the first/last one.
  const onKeyDown = (event) => {
    const index = tabs.findIndex((tab) => tab.id === active);
    const next = {
      ArrowRight: (index + 1) % tabs.length,
      ArrowLeft: (index - 1 + tabs.length) % tabs.length,
      Home: 0,
      End: tabs.length - 1,
    }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    setActive(tabs[next].id);
    buttons.current[tabs[next].id]?.focus();
  };

  return (
    <div className="tabs">
      <div className="tab-list" role="tablist" aria-label={label} onKeyDown={onKeyDown}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            ref={(button) => {
              buttons.current[tab.id] = button;
            }}
            type="button"
            role="tab"
            id={`${prefix}-tab-${tab.id}`}
            aria-controls={`${prefix}-panel-${tab.id}`}
            aria-selected={tab.id === active}
            tabIndex={tab.id === active ? 0 : -1}
            className="tab"
            onClick={() => setActive(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {tabs.map((tab) => (
        <div
          key={tab.id}
          role="tabpanel"
          id={`${prefix}-panel-${tab.id}`}
          aria-labelledby={`${prefix}-tab-${tab.id}`}
          hidden={tab.id !== active}
          className="tab-panel"
        >
          {tab.content}
        </div>
      ))}
    </div>
  );
}
