import { StrategyDraftCard } from './StrategyDraftCard';
import type { ChatMessage } from './types';

export function ChatMessageList({
  messages,
  onRunDraft
}: {
  messages: ChatMessage[];
  onRunDraft: (messageId: string) => void;
}) {
  return (
    <div className="space-y-6">
      {messages.map((message) => {
        if (message.role === 'user') {
          return (
            <div key={message.id} className="flex justify-end">
              <div className="app-button-primary max-w-3xl rounded-[28px] px-5 py-4 text-sm leading-6 shadow-lg shadow-cyan-950/20">
                {message.text}
              </div>
            </div>
          );
        }

        const hasDraftConfig =
          Boolean(message.draft) &&
          message.draft?.response_type !== 'ANSWER' &&
          message.draft?.response_type !== 'VALIDATION_ERROR' &&
          Boolean(message.draft?.config);

        return (
          <div key={message.id} className="flex justify-start">
            <div className="app-card app-shadow w-full max-w-5xl rounded-[32px] border p-4">
              <div className="app-label mb-3 text-xs font-semibold uppercase tracking-[0.22em]">
                Strategy Assistant
              </div>
              {hasDraftConfig && message.draft ? (
                <StrategyDraftCard
                  draft={message.draft}
                  onRun={() => onRunDraft(message.id)}
                  isRunning={message.isRunning}
                  runError={message.runError}
                />
              ) : (
                <p className="app-title whitespace-pre-wrap text-sm">{message.text}</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}