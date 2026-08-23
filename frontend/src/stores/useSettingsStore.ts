import { create } from 'zustand';

/**
 * K线颜色方案
 * - greenUpRedDown: 绿涨红跌（欧美习惯）
 * - redUpGreenDown: 红涨绿跌（中国习惯）
 */
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
  /** 获取当前涨跌颜色 */
  getColors: () => ColorPair;
}

const STORAGE_KEY = 'bitpro_settings';

function loadColorScheme(): ColorScheme {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed.colorScheme === 'greenUpRedDown' || parsed.colorScheme === 'redUpGreenDown') {
        return parsed.colorScheme;
      }
    }
  } catch {
    // ignore
  }
  return 'redUpGreenDown'; // 默认红涨绿跌
}

function saveSettings(state: { colorScheme: ColorScheme }) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // ignore
  }
}

/** 将颜色注入 CSS 变量，供全局样式类使用 */
function applyCSSVariables(scheme: ColorScheme) {
  const { upColor, downColor } = COLOR_SCHEMES[scheme];
  const root = document.documentElement;
  root.style.setProperty('--color-up', upColor);
  root.style.setProperty('--color-down', downColor);
  // 半透明版本用于背景
  root.style.setProperty('--color-up-bg', upColor + '1A'); // 10% opacity
  root.style.setProperty('--color-down-bg', downColor + '1A');
}

export const useSettingsStore = create<SettingsState>((set, get) => {
  const initial = loadColorScheme();
  // 初始化时立即注入 CSS 变量
  applyCSSVariables(initial);

  return {
    colorScheme: initial,

    setColorScheme: (scheme) => {
      set({ colorScheme: scheme });
      saveSettings({ colorScheme: scheme });
      applyCSSVariables(scheme);
    },

    getColors: () => {
      return COLOR_SCHEMES[get().colorScheme];
    },
  };
});

/** 直接获取颜色的工具函数（无需 hook，在非 React 上下文也可使用） */
export function getCandleColors(): ColorPair {
  return useSettingsStore.getState().getColors();
}

export { COLOR_SCHEMES };
