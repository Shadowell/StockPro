import { createElement as h, Fragment } from 'react';

function classNames(...values) {
  return values.filter(Boolean).join(' ');
}

export function BitProTheme({ children, className, colorScheme = 'red-up-green-down' }) {
  return h(
    'section',
    {
      className: classNames('bp-theme', className),
      'data-bitpro-color-scheme': colorScheme,
    },
    children,
  );
}

export function DataPanel({ title, subtitle, actions, children, className }) {
  const header = title || subtitle || actions
    ? h('header', { key: 'header', className: 'bp-panel__header' }, [
        h('div', { key: 'copy', className: 'bp-panel__copy' }, [
          title ? h('h2', { key: 'title', className: 'bp-panel__title' }, title) : null,
          subtitle ? h('p', { key: 'subtitle', className: 'bp-panel__subtitle' }, subtitle) : null,
        ]),
        actions ? h('div', { key: 'actions', className: 'bp-panel__actions' }, actions) : null,
      ])
    : null;

  return h('section', { className: classNames('bp-panel', className) }, [
    header,
    h(Fragment, { key: 'content' }, children),
  ]);
}

export function MetricCard({ label, value, icon, color = 'neutral', detail, className }) {
  return h('section', { className: classNames('bp-metric-card', className) }, [
    h('div', { key: 'header', className: 'bp-metric-card__header' }, [
      icon ? h('span', { key: 'icon', className: `bp-tone-${color}` }, icon) : null,
      h('span', { key: 'label', className: 'bp-metric-card__label' }, label),
    ]),
    h('div', { key: 'value', className: classNames('bp-metric-card__value', `bp-tone-${color}`) }, value),
    detail ? h('div', { key: 'detail', className: 'bp-metric-card__detail' }, detail) : null,
  ]);
}

export function StatusBadge({ children, tone = 'neutral', className }) {
  return h('span', { className: classNames('bp-status-badge', `bp-status-badge--${tone}`, className) }, children);
}

export function LogStream({ items, emptyText, className }) {
  if (!items.length) {
    return h('div', { className: classNames('bp-log-stream__empty', className) }, emptyText);
  }

  return h('div', { className: classNames('bp-log-stream', className) }, [
    h('div', { key: 'header', className: 'bp-log-stream__header' }, [
      h('span', { key: 'time' }, '时间'),
      h('span', { key: 'level' }, '级别'),
      h('span', { key: 'message' }, '运行信息'),
    ]),
    h('div', { key: 'body', className: 'bp-log-stream__body' }, items.map((item) =>
      h('div', { key: item.id, className: 'bp-log-stream__row' }, [
        h('time', { key: 'time', className: 'bp-log-stream__time' }, item.time),
        h(StatusBadge, {
          key: 'level',
          tone: item.tone || 'neutral',
          className: 'bp-log-stream__badge',
        }, item.label),
        h('div', { key: 'content', className: 'bp-log-stream__content' }, [
          h('div', {
            key: 'message',
            className: classNames('bp-log-stream__message', item.tone === 'red' && 'bp-log-stream__message--error'),
          }, item.message),
          item.meta ? h('div', { key: 'meta', className: 'bp-log-stream__meta' }, item.meta) : null,
        ]),
      ]),
    )),
  ]);
}
