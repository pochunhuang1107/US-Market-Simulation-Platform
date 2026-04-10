import type { StrategyBuilderGenerateResponse } from '../../types/api';

export type ChatMessage =
  | {
      id: string;
      role: 'user';
      text: string;
    }
  | {
      id: string;
      role: 'assistant';
      text: string;
      draft?: StrategyBuilderGenerateResponse;
      isRunning?: boolean;
      runError?: string | null;
    };
