declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp;
    };
  }

  interface TelegramWebApp {
    initData: string;
    initDataUnsafe: {
      user?: { id: number; username?: string; first_name?: string; last_name?: string };
      auth_date?: number;
      query_id?: string;
      start_param?: string;
      chat?: { id: number; type: string; title?: string; username?: string };
      chat_type?: string;
      chat_instance?: string;
    };
    colorScheme: 'light' | 'dark';
    themeParams: Record<string, string>;
    isExpanded: boolean;
    viewportHeight: number;
    viewportStableHeight: number;
    headerColor: string;
    backgroundColor: string;
    ready: () => void;
    expand: () => void;
    close: () => void;
    MainButton: {
      text: string;
      show: () => void;
      hide: () => void;
      enable: () => void;
      disable: () => void;
      onClick: (fn: () => void) => void;
      offClick: (fn: () => void) => void;
      setText: (text: string) => void;
      showProgress: (leave?: boolean) => void;
      hideProgress: () => void;
    };
    BackButton: {
      show: () => void;
      hide: () => void;
      onClick: (fn: () => void) => void;
      offClick: (fn: () => void) => void;
    };
    HapticFeedback: {
      impactOccurred: (style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft') => void;
      notificationOccurred: (type: 'error' | 'success' | 'warning') => void;
    };
    showAlert: (message: string) => void;
    showConfirm: (message: string, cb: (ok: boolean) => void) => void;
  }
}

export {};
