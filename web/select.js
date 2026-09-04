// Theme-aware, select-only comboboxes. Native selects remain the form data source.
// Enhancement is explicit at render boundaries; option/disabled updates are observed.
const controls = new WeakMap();
let active = null, serial = 0;

export function nextOption(options, current, direction) {
  const enabled = options.map((o, i) => !o.disabled && !o.hidden ? i : -1).filter(i => i >= 0);
  if (!enabled.length) return -1;
  if (direction === 'first') return enabled[0];
  if (direction === 'last') return enabled.at(-1);
  const index = enabled.indexOf(current);
  return enabled[Math.max(0, Math.min(enabled.length - 1, index < 0 ? 0 : index + direction))];
}

export function menuPosition(rect, viewport, desiredHeight) {
  const gap = 6, edge = 8;
  const width = Math.min(Math.max(rect.width, 240), viewport.width - edge * 2);
  const below = viewport.height - rect.bottom - gap - edge, above = rect.top - gap - edge;
  const flip = below < Math.min(desiredHeight, 180) && above > below;
  const maxHeight = Math.max(0, Math.min(320, flip ? above : below));
  return {left: Math.max(edge, Math.min(rect.left, viewport.width - width - edge)),
    top: flip ? rect.top - gap - Math.min(desiredHeight, maxHeight) : rect.bottom + gap,
    width, maxHeight};
}

function svg(path) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="${path}"/></svg>`;
}

class SelectControl {
  constructor(select) {
    this.select = select;
    this.document = select.ownerDocument;
    const doc = this.document, id = `choice-${++serial}`;
    const hadFocus = doc.activeElement === select;
    this.wrapper = doc.createElement('div');
    this.wrapper.className = 'select-control';
    select.before(this.wrapper);
    this.wrapper.append(select);
    this.button = doc.createElement('button');
    this.button.type = 'button';
    this.button.id = `${id}-button`;
    this.button.className = 'select-trigger';
    this.button.setAttribute('role', 'combobox');
    this.button.setAttribute('aria-haspopup', 'listbox');
    this.button.setAttribute('aria-expanded', 'false');
    this.button.setAttribute('aria-controls', `${id}-list`);
    this.button.innerHTML = `<span class="select-value"></span>${svg('m7 10 5 5 5-5')}`;
    this.value = this.button.querySelector('.select-value');
    const labels = [...select.labels];
    labels.forEach((label, i) => {
      if (!label.id) label.id = `${id}-label-${i}`;
      label.htmlFor = this.button.id;
    });
    this.labelIds = select.getAttribute('aria-labelledby') || labels.map(l => l.id).join(' ');
    this.menu = doc.createElement('div');
    this.menu.id = `${id}-list`;
    this.menu.className = 'select-menu';
    this.menu.setAttribute('role', 'listbox');
    this.menu.setAttribute('popover', 'manual');
    this.menu.hidden = true;
    this.wrapper.append(this.button, this.menu);
    select.classList.add('select-native');
    select.hidden = true;
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');
    this.button.addEventListener('click', () => this.opened ? this.close() : this.open());
    this.button.addEventListener('keydown', event => this.keydown(event));
    this.button.addEventListener('blur', () => this.close());
    this.menu.addEventListener('pointerdown', event => event.preventDefault());
    this.menu.addEventListener('click', event => {
      const row = event.target.closest('[data-option]');
      if (row) this.commit(Number(row.dataset.option));
    });
    this.menu.addEventListener('pointermove', event => {
      const row = event.target.closest('[data-option]');
      if (row && !this.options[Number(row.dataset.option)].disabled) this.highlight(Number(row.dataset.option), false);
    });
    select.addEventListener('change', () => this.sync());
    select.addEventListener('input', () => this.sync());
    select.addEventListener('focus', () => this.button.focus());
    select.addEventListener('invalid', event => {
      event.preventDefault();
      this.button.setAttribute('aria-invalid', 'true');
      if (!this.error) {
        this.error = doc.createElement('small');
        this.error.className = 'select-error';
        this.error.id = `${id}-error`;
        this.error.setAttribute('role', 'alert');
        this.wrapper.append(this.error);
      }
      this.error.textContent = select.validationMessage;
      this.button.setAttribute('aria-describedby', [select.getAttribute('aria-describedby'), this.error.id].filter(Boolean).join(' '));
      this.button.focus();
    });
    select.form?.addEventListener('reset', () => queueMicrotask(() => this.sync()));
    this.observer = new MutationObserver(() => this.sync());
    this.observer.observe(select, {subtree: true, childList: true, characterData: true, attributes: true,
      attributeFilter: ['disabled', 'selected', 'label', 'value', 'hidden', 'required', 'aria-label', 'aria-describedby']});
    this.sync();
    if (hadFocus) this.button.focus();
  }

  sync() {
    const select = this.select;
    this.options = [...select.options].map(o => ({label: o.label, disabled: o.disabled || !!o.closest('optgroup[disabled]'), hidden: o.hidden}));
    this.value.textContent = select.selectedOptions[0]?.label || 'Select an option';
    this.button.disabled = select.matches(':disabled');
    this.button.setAttribute('aria-required', String(select.required));
    if (this.labelIds) {
      this.button.setAttribute('aria-labelledby', this.labelIds);
      this.menu.setAttribute('aria-labelledby', this.labelIds);
    } else {
      const label = select.getAttribute('aria-label') || select.name || 'Choose an option';
      this.button.setAttribute('aria-label', label);
      this.menu.setAttribute('aria-label', label);
    }
    if (select.validity.valid) {
      this.button.removeAttribute('aria-invalid');
      if (this.error) this.error.textContent = '';
      const description = select.getAttribute('aria-describedby');
      if (description) this.button.setAttribute('aria-describedby', description);
      else this.button.removeAttribute('aria-describedby');
    }
    if (this.button.disabled) this.close();
    else if (this.opened) { this.renderOptions(); this.highlight(select.selectedIndex); this.position(); }
  }

  renderOptions() {
    this.menu.replaceChildren();
    this.rows = this.options.map((option, index) => {
      const row = this.document.createElement('div');
      row.id = `${this.menu.id}-${index}`;
      row.className = 'select-option';
      row.setAttribute('role', 'option');
      row.setAttribute('aria-selected', String(index === this.select.selectedIndex));
      row.setAttribute('aria-disabled', String(option.disabled));
      row.dataset.option = String(index);
      row.hidden = option.hidden;
      const label = this.document.createElement('span');
      label.textContent = option.label;
      row.append(label);
      row.insertAdjacentHTML('beforeend', svg('m5 12 4 4L19 6'));
      this.menu.append(row);
      return row;
    });
  }

  open() {
    this.sync();
    if (this.button.disabled || !this.options.length) return;
    active?.close();
    active = this;
    this.opened = true;
    this.typed = '';
    this.button.setAttribute('aria-expanded', 'true');
    this.renderOptions();
    this.menu.hidden = false;
    // Popover top layer escapes scrolling dialog bodies without leaving the modal.
    if (this.menu.showPopover) this.menu.showPopover();
    else (this.select.closest('dialog') || this.document.body).append(this.menu);
    this.position();
    this.highlight(this.select.selectedIndex >= 0 ? this.select.selectedIndex : nextOption(this.options, -1, 'first'));
    this.openEvents = new AbortController();
    const options = {capture: true, signal: this.openEvents.signal};
    this.document.addEventListener('pointerdown', event => {
      if (!this.wrapper.contains(event.target) && !this.menu.contains(event.target)) this.close();
    }, options);
    this.document.addEventListener('scroll', event => { if (!this.menu.contains(event.target)) this.close(); }, options);
    this.document.addEventListener('close', () => this.close(), options);
    this.document.defaultView.addEventListener('resize', () => this.close(), options);
    this.removalObserver = new MutationObserver(() => { if (!this.button.isConnected) this.close(); });
    this.removalObserver.observe(this.document.body, {childList: true, subtree: true});
  }

  position() {
    const doc = this.document.documentElement;
    const rect = this.button.getBoundingClientRect();
    // Measure natural wrapped text height before choosing above/below placement.
    const size = menuPosition(rect, {width: doc.clientWidth, height: doc.clientHeight}, 320);
    this.menu.style.width = `${size.width}px`;
    const position = menuPosition(rect, {width: doc.clientWidth, height: doc.clientHeight}, this.menu.scrollHeight + 2);
    for (const [key, value] of Object.entries(position)) this.menu.style[key] = `${value}px`;
  }

  highlight(index, scroll = true) {
    if (index < 0 || !this.rows[index]) { this.button.removeAttribute('aria-activedescendant'); return; }
    this.current = index;
    this.rows.forEach((row, i) => row.classList.toggle('is-active', i === index));
    this.button.setAttribute('aria-activedescendant', this.rows[index].id);
    if (scroll) this.rows[index].scrollIntoView({block: 'nearest'});
  }

  commit(index = this.current) {
    if (!this.options[index] || this.options[index].disabled || this.options[index].hidden) return;
    const changed = this.select.selectedIndex !== index;
    this.select.selectedIndex = index;
    this.close();
    this.sync();
    this.button.focus();
    if (changed) {
      this.select.dispatchEvent(new Event('input', {bubbles: true}));
      this.select.dispatchEvent(new Event('change', {bubbles: true}));
    }
  }

  close() {
    if (!this.opened) return;
    this.opened = false;
    this.openEvents?.abort();
    this.removalObserver?.disconnect();
    if (this.menu.hidePopover && this.menu.matches(':popover-open')) this.menu.hidePopover();
    this.menu.hidden = true;
    if (!this.wrapper.contains(this.menu)) this.wrapper.append(this.menu);
    this.button.setAttribute('aria-expanded', 'false');
    this.button.removeAttribute('aria-activedescendant');
    if (active === this) active = null;
  }

  keydown(event) {
    const key = event.key;
    if (Date.now() - (this.lastTyped || 0) > 700) this.typed = '';
    if (key === 'Tab') { this.close(); return; }
    if (key === 'Escape') {
      if (this.opened) { event.preventDefault(); event.stopPropagation(); this.close(); }
      return;
    }
    if (event.ctrlKey || event.metaKey || (event.altKey && !['ArrowDown', 'ArrowUp'].includes(key))) return;
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(key)) {
      event.preventDefault();
      const wasOpen = this.opened;
      if (!wasOpen) this.open();
      if (!this.opened) return;
      if (event.altKey && key === 'ArrowUp') { this.close(); return; }
      if (wasOpen || key === 'Home' || key === 'End') this.highlight(nextOption(this.options, this.current,
        key === 'Home' ? 'first' : key === 'End' ? 'last' : key === 'ArrowDown' ? 1 : -1));
    } else if (key === 'Enter' || (key === ' ' && !this.typed)) {
      event.preventDefault();
      if (this.opened) this.commit(); else this.open();
    } else if (key.length === 1) {
      event.preventDefault();
      if (!this.opened) this.open();
      if (!this.opened) return;
      const now = Date.now();
      this.typed = now - (this.lastTyped || 0) > 700 ? key : this.typed + key;
      this.lastTyped = now;
      const term = [...this.typed].every(c => c === key) ? key : this.typed;
      const start = term.length === 1 ? this.current + 1 : this.current;
      for (let offset = 0; offset < this.options.length; offset++) {
        const index = (start + offset + this.options.length) % this.options.length, option = this.options[index];
        if (!option.disabled && !option.hidden && option.label.toLocaleLowerCase().startsWith(term.toLocaleLowerCase())) { this.highlight(index); break; }
      }
    }
  }
}

export function enhanceSelects(root = document) {
  root.querySelectorAll('select:not([multiple])').forEach(select => {
    if (!controls.has(select)) controls.set(select, new SelectControl(select));
    else controls.get(select).sync();
  });
}
