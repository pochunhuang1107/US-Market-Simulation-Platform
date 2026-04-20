import { StrategyDraftCard } from './StrategyDraftCard';
import type { ChatMessage } from './types';

function AssistantMessageCard({
  tone,
  title,
  text
}: {
  tone: 'default' | 'info' | 'warning';
  title: string;
  text: string;
}) {
  const toneClass =
    tone === 'warning'
      ? 'border-amber-500/30 bg-amber-500/10 text-amber-100'
      : tone === 'info'
        ? 'border-cyan-500/30 bg-cyan-500/10 text-cyan-100'
        : 'app-card app-shadow border';

  const eyebrowClass =
    tone === 'warning'
      ? 'text-amber-200'
      : tone === 'info'
        ? 'text-cyan-200'
        : 'app-label';

  const bodyClass =
    tone === 'warning'
      ? 'text-amber-100/90'
      : tone === 'info'
        ? 'text-cyan-100/90'
        : 'app-title';

  return (
    <div className={`w-full max-w-5xl rounded-[32px] p-4 ${toneClass}`}>
      <div className={`mb-3 text-xs font-semibold uppercase tracking-[0.22em] ${eyebrowClass}`}>
        {title}
      </div>
      <p className={`whitespace-pre-wrap text-sm leading-6 ${bodyClass}`}>{text}</p>
    </div>
  );
}

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

        if (hasDraftConfig && message.draft) {
          return (
            <div key={message.id} className="flex justify-start">
              <div className="w-full max-w-5xl">
                <StrategyDraftCard
                  draft={message.draft}
                  onRun={() => onRunDraft(message.id)}
                  isRunning={message.isRunning}
                  runError={message.runError}
                />
              </div>
            </div>
          );
        }

        const responseType = message.draft?.response_type;
        const tone =
          responseType === 'VALIDATION_ERROR'
            ? 'warning'
            : responseType === 'ANSWER'
              ? 'info'
              : 'default';

        const title =
          responseType === 'VALIDATION_ERROR'
            ? 'Validation guidance'
            : responseType === 'ANSWER'
              ? 'Strategy Assistant'
              : 'Strategy Assistant';

        return (
          <div key={message.id} className="flex justify-start">
            <AssistantMessageCard tone={tone} title={title} text={message.text} />
          </div>
        );
      })}
    </div>
  );
}