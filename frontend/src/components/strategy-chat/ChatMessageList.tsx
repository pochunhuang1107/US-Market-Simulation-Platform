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
              <div className="max-w-3xl rounded-[28px] bg-cyan-500 px-5 py-4 text-sm leading-6 text-slate-950 shadow-lg shadow-cyan-950/30">
                {message.text}
              </div>
            </div>
          );
        }

        return (
          <div key={message.id} className="flex justify-start">
            <div className="w-full max-w-5xl rounded-[32px] border border-slate-800 bg-slate-900/70 p-4 shadow-2xl shadow-black/20">
              <div className="mb-3 text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">
                Strategy Assistant
              </div>
              {message.draft ? (
                <StrategyDraftCard
                  draft={message.draft}
                  onRun={() => onRunDraft(message.id)}
                  isRunning={message.isRunning}
                  runError={message.runError}
                />
              ) : (
                <p className="text-sm text-slate-200">{message.text}</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
