import { useCallback, useLayoutEffect, useRef } from 'react';

type PromptComposerProps = {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  submitting: boolean;
  disabled?: boolean;
  placeholder?: string;
  submitLabel?: string;
};

export function PromptComposer({
  value,
  onChange,
  onSubmit,
  submitting,
  disabled = false,
  placeholder = 'Describe your strategy...',
  submitLabel
}: PromptComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const resizeTextarea = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    textarea.style.height = '0px';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
  }, []);

  useLayoutEffect(() => {
    resizeTextarea();
  }, [value, resizeTextarea]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();

        if (!submitting && !disabled && value.trim()) {
          onSubmit();
        }
      }
    },
    [disabled, onSubmit, submitting, value]
  );

  const isButtonDisabled = disabled || submitting || !value.trim();

  return (
    <div className="app-card rounded-[28px] border shadow-[0_0_0_1px_rgba(255,255,255,0.02)]">
      <div className="flex items-center gap-3 px-4 py-3">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onInput={resizeTextarea}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={1}
          disabled={disabled || submitting}
          className="w-full resize-none overflow-y-auto border-0 bg-transparent text-base leading-6 app-title outline-none placeholder:text-[var(--text-soft)]"
        />

        <button
          type="button"
          onClick={onSubmit}
          disabled={isButtonDisabled}
          aria-label={submitLabel ?? 'Send'}
          className="app-button-primary flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting ? (
            <span className="text-xs font-semibold">...</span>
          ) : (
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.4"
              className="h-4 w-4"
            >
              <path d="M12 19V5" />
              <path d="m5 12 7-7 7 7" />
            </svg>
          )}
        </button>
      </div>
    </div>
  );
}
