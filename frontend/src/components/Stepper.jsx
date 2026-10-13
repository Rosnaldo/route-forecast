// Numbered steps, [{ id, label, content, disabled }], with the `active` index controlled
// by the parent. Every step stays mounted (hidden when inactive) so forms inside keep
// their state when the user moves between steps.
export default function Stepper({ steps, active, onChange, label }) {
  return (
    <div className="stepper">
      <ol className="stepper-header" aria-label={label}>
        {steps.map((step, index) => {
          const status = index < active ? "done" : index === active ? "current" : "upcoming";
          return (
            <li key={step.id} className={`stepper-step ${status}`}>
              <button
                type="button"
                className="stepper-button"
                aria-current={index === active ? "step" : undefined}
                disabled={step.disabled}
                onClick={() => onChange(index)}
              >
                <span className="stepper-number" aria-hidden="true">
                  {status === "done" ? "✓" : index + 1}
                </span>
                <span className="stepper-label">{step.label}</span>
              </button>
            </li>
          );
        })}
      </ol>
      {steps.map((step, index) => (
        <div key={step.id} className="stepper-panel" hidden={index !== active}>
          {step.content}
        </div>
      ))}
    </div>
  );
}
