/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AUTH_PROVIDER?: string;
  readonly VITE_AUTH0_DOMAIN?: string;
  readonly VITE_AUTH0_CLIENT_ID?: string;
  readonly VITE_AUTH0_AUDIENCE?: string;
  readonly VITE_AUTH0_REDIRECT_URI?: string;
  readonly VITE_AUTH0_CACHE_LOCATION?: string;
  readonly VITE_AUTH0_USE_REFRESH_TOKENS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
