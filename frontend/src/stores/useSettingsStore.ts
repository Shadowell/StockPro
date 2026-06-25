import { create } from 'zustand';

export type ColorScheme = 'greenUpRedDown' | 'redUpGreenDown';

interface ColorPair {
  upColor: string;
  downColor: string;
}

const COLOR_SCHEMES: Record<ColorScheme, ColorPair> = {
  greenUpRedDown: {
    upColor: '#00C853',
    downColor: '#FF1744',
  },
  redUpGreenDown: {
    upColor: '#FF1744',
    downColor: '#00C853',
  },
};

interface SettingsState {
  colorScheme: ColorScheme;
  setColorScheme: (scheme: ColorScheme) => void;
  getColors: () => ColorPair;
}

const STORAGE_KEY = 'stockpro_settings';

function loadColorScheme(): ColorScheme {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return 'redUpGreenDown';
    const parsed = JSON.parse(raw);
    if (parsed.colorScheme === 'greenUpRedDown' || parsed.colorScheme === 'redUpGreenDown') {
      return parsed.colorScheme;
    }
  } catch {
    return 'redUpGreenDown';
  }
  return 'redUpGreenDown';
}

function applyCSSVariables(scheme: ColorScheme) {
  if (typeof document === 'undefined') return;
  const { upColor, downColor } = COLOR_SCHEMES[scheme];
  const root = document.documentElement;
  root.style.setProperty('--color-up', upColor);
  root.style.setProperty('--color-down', downColor);
  root.style.setProperty('--color-up-bg', `${upColor}1A`);
  root.style.setProperty('--color-down-bg', `${downColor}1A`);
}

export const useSettingsStore = create<SettingsState>((set, get) => {
  const initial = loadColorScheme();
  applyCSSVariables(initial);

  return {
    colorScheme: initial,
    setColorScheme: (scheme) => {
      set({ colorScheme: scheme });
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ colorScheme: scheme }));
      applyCSSVariables(scheme);
    },
    getColors: () => COLOR_SCHEMES[get().colorScheme],
  };
});

export { COLOR_SCHEMES };
