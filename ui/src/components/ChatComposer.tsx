import { useId, useState, type FormEvent, type KeyboardEvent } from "react";
import "./components.css";

export const AVAILABLE_MODELS = [
  { id: "dle-13axis-strict", label: "dle-13axis-strict (Governed Strict)" },
  { id: "dle-13axis-advisory", label: "dle-13axis-advisory (Governed Advisory)" },
  { id: "gemini-4-carbon", label: "gemini-4-carbon (Pass-through)" },
  { id: "gemini-4-neon", label: "gemini-4-neon (Pass-through Fast)" },
] as const;

export interface ComposerSubmitPayload {
  prompt: string;
  model: string;
  streaming: boolean;
}

interface ChatComposerProps {
  initialPrompt?: string;
  initialModel?: string;
  initialStreaming?: boolean;
  sending?: boolean;
  disabled?: boolean;
  onSubmit?: (payload: ComposerSubmitPayload) => void | Promise<void>;
}

export function ChatComposer({
  initialPrompt = "",
  initialModel = "dle-13axis-strict",
  initialStreaming = true,
  sending = false,
  disabled = false,
  onSubmit,
}: ChatComposerProps) {
  const [prompt, setPrompt] = useState(initialPrompt);
  const [model, setModel] = useState(initialModel);
  const [streaming, setStreaming] = useState(initialStreaming);
  const modelId = useId();
  const promptId = useId();
  const streamId = useId();

  const isLocked = disabled || sending;
  const canSend = !isLocked && prompt.trim().length > 0;

  const submitForm = () => {
    if (!canSend) {
      return;
    }
    const text = prompt.trim();
    setPrompt("");
    void onSubmit?.({ prompt: text, model, streaming });
  };

  const handleFormSubmit = (e: FormEvent) => {
    e.preventDefault();
    submitForm();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitForm();
    }
  };

  return (
    <form className="dle-composer" onSubmit={handleFormSubmit} aria-label="Message composer">
      <div className="dle-composer-row">
        <label className="dle-composer-field" htmlFor={modelId}>
          <span>Model</span>
          <select
            id={modelId}
            className="dle-select"
            value={model}
            disabled={isLocked}
            onChange={(e) => setModel(e.target.value)}
          >
            {AVAILABLE_MODELS.map((opt) => (
              <option key={opt.id} value={opt.id}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>

        <label className="dle-composer-field" htmlFor={streamId}>
          <input
            id={streamId}
            type="checkbox"
            className="dle-checkbox"
            checked={streaming}
            disabled={isLocked}
            onChange={(e) => setStreaming(e.target.checked)}
          />
          <span>Stream SSE (keepalives)</span>
        </label>
      </div>

      <label className="dle-sr-only" htmlFor={promptId}>
        Prompt
      </label>
      <textarea
        id={promptId}
        className="dle-textarea"
        placeholder="Ask DataLogicEngine or a Gemini model..."
        value={prompt}
        disabled={isLocked}
        onChange={(e) => setPrompt(e.target.value)}
        onKeyDown={handleKeyDown}
      />

      <div className="dle-composer-row">
        <span className="dle-bubble-meta">Enter sends, Shift+Enter adds a newline.</span>
        <button type="submit" className="dle-btn-primary" disabled={!canSend}>
          {sending ? "Sending..." : "Send"}
        </button>
      </div>
    </form>
  );
}
