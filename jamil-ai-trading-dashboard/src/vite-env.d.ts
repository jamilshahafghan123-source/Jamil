/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_FORCE_DEMO_DATA?: string;
  readonly VITE_TRADING_ENABLED?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
