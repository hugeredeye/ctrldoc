import { useState } from "react";
import type { KeyboardEvent } from "react";

export function CtrlKeycap({ small = false }: { small?: boolean }) {
  const [pressed, setPressed] = useState(false);

  const release = () => setPressed(false);
  const press = () => setPressed(true);

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "Enter" || event.key === " ") press();
  };

  const handleKeyUp = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "Enter" || event.key === " ") release();
  };

  const openProduct = () => {
    document.getElementById("product")?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <div className={`ctrl-keycap-stage${small ? " ctrl-keycap-stage-small" : ""}`}>
      <div className="ctrl-keycap-shadow" aria-hidden="true" />
      <button
        aria-label="Перейти к проверке CTRL"
        className={`ctrl-keycap${pressed ? " is-pressed" : ""}`}
        data-motion="css-reduced-motion-aware"
        data-pressed={pressed}
        onBlur={release}
        onClick={openProduct}
        onKeyDown={handleKeyDown}
        onKeyUp={handleKeyUp}
        onPointerCancel={release}
        onPointerDown={press}
        onPointerLeave={release}
        onPointerUp={release}
        type="button"
      >
        <span className="ctrl-keycap-face">
          <span className="ctrl-keycap-label">CTRL</span>
          <span className="ctrl-keycap-corner">⌃</span>
        </span>
      </button>
    </div>
  );
}
