(function () {
  const tabs = Array.from(document.querySelectorAll('.settings-tab'));
  const panels = Array.from(document.querySelectorAll('.settings-content'));

  const toastContainer = document.getElementById('toast-container');
  function showToast(message, kind = "success") {
    if (!toastContainer) return;
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.setAttribute('role', 'status');
    el.textContent = message;
    toastContainer.appendChild(el);

    setTimeout(() => { // Auto-remove after 5s
      el.remove();
    }, 5000);
  }

  const fields = {
    hour_format: document.getElementById('hour-format'),
    language: document.getElementById('language'),
    jf_host: document.getElementById('jf-host'),
    jf_port: document.getElementById('jf-port'),
    jf_api_key: document.getElementById('jf-api-key'),
  };

  const API_MASK = '*'.repeat(32);
  const clearBtn = document.getElementById('jf-api-clear');
  let isApiMasked = false;

  const lastKnown = {
    hour_format: null,
    language: null,
    jf_host: null,
    jf_port: null,
    jf_api_key: null,
  };

  async function loadSettings() {
    try {
      const resp = await fetch('/api/settings');
      if (!resp.ok) throw new Error(`GET failed: ${resp.status}`);
      const data = await resp.json();
      if (fields.hour_format) fields.hour_format.value = data.hour_format || '24';
      if (fields.language) fields.language.value = data.language || 'en';
      if (fields.jf_host) fields.jf_host.value = data.jf_host || '';
      if (fields.jf_port) fields.jf_port.value = data.jf_port || '';
      if (fields.jf_api_key) {
        if (typeof data.jf_api_key === 'string' && data.jf_api_key.length > 0) {
          fields.jf_api_key.value = API_MASK;
          fields.jf_api_key.disabled = true;
          isApiMasked = true;
          if (clearBtn) clearBtn.hidden = false;
        } else {
          fields.jf_api_key.value = '';
          fields.jf_api_key.disabled = false;
          isApiMasked = false;
          if (clearBtn) clearBtn.hidden = true;
        }
      }

      lastKnown.hour_format = fields.hour_format ? fields.hour_format.value : null;
      lastKnown.language = fields.language ? fields.language.value : null;
      lastKnown.jf_host = fields.jf_host ? fields.jf_host.value.trim() : null;
      lastKnown.jf_port = fields.jf_port ? fields.jf_port.value.trim() : null;
      lastKnown.jf_api_key = typeof data.jf_api_key === 'string' && data.jf_api_key.length > 0
        ? data.jf_api_key
        : null;

    } catch (err) {
      showToast('Failed to load settings', 'error');
      console.error(err);
    }
  }

  let saveTimer = null;
  function scheduleSave(payload) {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => saveSettings(payload), 200);
  }

  async function saveSettings(payload) {
    try {
      if ('jf_api_key' in payload) {
        const v = payload.jf_api_key || '';
        if (v === API_MASK) {
          delete payload.jf_api_key;
        }
      }
      const resp = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) throw new Error(`PUT failed: ${resp.status}`);
      const updated = await resp.json();

      if (fields.hour_format && 'hour_format' in updated) {
        fields.hour_format.value = updated.hour_format;
        lastKnown.hour_format = updated.hour_format;
      }
      if (fields.language && 'language' in updated) {
        fields.language.value = updated.language;
        lastKnown.language = updated.language;
      }
      if (fields.jf_host && 'jf_host' in updated) {
        fields.jf_host.value = updated.jf_host || '';
        lastKnown.jf_host = (updated.jf_host || '').trim();
      }
      if (fields.jf_port && 'jf_port' in updated) {
        fields.jf_port.value = updated.jf_port || '';
        lastKnown.jf_port = (updated.jf_port || '').trim();
      }
      if (fields.jf_api_key && 'jf_api_key' in updated) {
        if (typeof updated.jf_api_key === 'string' && updated.jf_api_key.length > 0) {
          fields.jf_api_key.value = API_MASK;
          fields.jf_api_key.disabled = true;
          isApiMasked = true;
          lastKnown.jf_api_key = updated.jf_api_key;
          if (clearBtn) clearBtn.hidden = false;
        } else {
          fields.jf_api_key.value = '';
          fields.jf_api_key.disabled = false;
          isApiMasked = false;
          lastKnown.jf_api_key = null;
          if (clearBtn) clearBtn.hidden = true;
        }
      }
      showToast('Settings saved', 'success');
    } catch (err) {
      showToast('Failed to save settings', 'error');
      console.error(err);
    }
  }

  function bindAutosave() {
    if (fields.hour_format) {
      fields.hour_format.addEventListener('blur', () => {
        const v = fields.hour_format.value;
        if (v !== lastKnown.hour_format) {
          scheduleSave({ hour_format: v });
        }
      });
      fields.hour_format.addEventListener('change', () => {
        const v = fields.hour_format.value;
        if (v !== lastKnown.hour_format) {
          scheduleSave({ hour_format: v });
        }
      });
    }
    if (fields.language) {
      fields.language.addEventListener('blur', () => {
        const v = fields.language.value;
        if (v !== lastKnown.language) {
          scheduleSave({ language: v });
        }
      });
      fields.language.addEventListener('change', () => {
        const v = fields.language.value;
        if (v !== lastKnown.language) {
          scheduleSave({ language: v });
        }
      });
    }
    if (fields.jf_host) {
      fields.jf_host.addEventListener('blur', () => {
        const v = fields.jf_host.value.trim();
        if (v !== lastKnown.jf_host) {
          scheduleSave({ jf_host: v });
        }
      });
    }
    if (fields.jf_port) {
      fields.jf_port.addEventListener('blur', () => {
        const v = fields.jf_port.value.trim();
        if (v !== lastKnown.jf_port) {
          scheduleSave({ jf_port: v });
        }
      });
    }
    if (fields.jf_api_key) {
      fields.jf_api_key.addEventListener('blur', () => {
        if (isApiMasked || fields.jf_api_key.disabled) return;
        const val = fields.jf_api_key.value.trim();
        if (val && val !== API_MASK && val !== (lastKnown.jf_api_key || '')) {
          scheduleSave({ jf_api_key: val });
        }
      });
    }
    if (clearBtn) {
      clearBtn.addEventListener('click', async () => {
        try {
          await saveSettings({ jf_api_key: '' });
          showToast('API key cleared', 'success');
        } catch (e) {
          showToast('Failed to clear API key', 'error');
        } finally {
          fields.jf_api_key.value = '';
          fields.jf_api_key.disabled = false;
          isApiMasked = false;
          clearBtn.hidden = true;
          fields.jf_api_key.focus();
        }
      });
    }
  }

  function activate(id) {
    tabs.forEach(t => {
      const isActive = t.getAttribute('href') === `#${id}`;
      t.classList.toggle('active', isActive);
      t.setAttribute('aria-selected', String(isActive));
      t.setAttribute('tabindex', isActive ? '0' : '-1');
    });
    panels.forEach(p => {
      p.hidden = p.id !== id;
    });
  }

  function fromHash() {
    const id = (location.hash || '#general').slice(1);
    const known = panels.some(p => p.id === id);
    activate(known ? id : 'general');
  }

  tabs.forEach(t => {
    t.addEventListener('click', (e) => {
      e.preventDefault();
      const id = t.getAttribute('href').slice(1);
      history.replaceState(null, '', `#${id}`);
      activate(id);
    });
  });

  window.addEventListener('hashchange', fromHash);
  fromHash();

  loadSettings().then(bindAutosave);
})();

(function () {
  const buttons = Array.from(document.querySelectorAll('#jellyfin .form-actions .btn'));
  if (buttons.length === 0) return;

  const testConnectionBtn = buttons[0] || null;
  const testSystemInfoBtn = buttons[1] || null;

  function showToast(message, kind = "success") {
    const toastContainer = document.getElementById('toast-container');
    if (!toastContainer) return;
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.setAttribute('role', 'status');
    el.textContent = message;
    toastContainer.appendChild(el);
    setTimeout(() => el.remove(), 3000);
  }

  if (testConnectionBtn) {
    testConnectionBtn.addEventListener('click', async () => {
      const originalText = testConnectionBtn.textContent;
      testConnectionBtn.disabled = true;
      testConnectionBtn.textContent = 'Testing...';
      try {
        const resp = await fetch('/api/test-connection', { method: 'GET' });
        const data = await resp.json();
        const kind = data.ok ? 'success' : 'error';
        const statusInfo = typeof data.status === 'number' ? ` (status: ${data.status})` : '';
        const msg = (data.message || (data.ok ? 'Connection successful.' : 'Connection failed.')) + statusInfo;
        showToast(msg, kind);
      } catch (err) {
        showToast('Failed to test connection', 'error');
        console.error(err);
      } finally {
        testConnectionBtn.textContent = originalText;
        const COOLDOWN_MS = 5000;
        setTimeout(() => { testConnectionBtn.disabled = false; }, COOLDOWN_MS);
      }
    });
  }

  if (testSystemInfoBtn) {
    testSystemInfoBtn.addEventListener('click', async () => {
      const originalText = testSystemInfoBtn.textContent;
      testSystemInfoBtn.disabled = true;
      testSystemInfoBtn.textContent = 'Fetching...';
      try {
        const resp = await fetch('/api/jellyfin/system-info', { method: 'GET' });
        const result = await resp.json();

        if (result && result.ok) {
          const d = result.data || {};
          const name = d.ServerName || d.ServerId || 'Unknown';
          const ver = d.Version || d.ProductVersion || 'n/a';
          const os = d.OperatingSystem || d.System || 'n/a';
          const msg = `SystemInfo: name=${name}, version=${ver}, os=${os} (status: ${result.status})`;
          showToast(msg, 'success');
        } else {
          const status = result?.status ?? resp.status;
          const message = result?.message || 'Failed to fetch SystemInfo.';
          showToast(`${message} (status: ${status})`, 'error');
        }
      } catch (err) {
        showToast('Failed to fetch SystemInfo', 'error');
        console.error(err);
      } finally {
        testSystemInfoBtn.textContent = originalText;
        const COOLDOWN_MS = 5000;
        setTimeout(() => { testSystemInfoBtn.disabled = false; }, COOLDOWN_MS);
      }
    });
  }
})();