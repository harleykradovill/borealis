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
    
        setTimeout(() => { // Auto-remove after 3s
          el.remove();
        }, 3000);
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
          }
          if (fields.language && 'language' in updated) {
            fields.language.value = updated.language;
          }
          if (fields.jf_host && 'jf_host' in updated) {
            fields.jf_host.value = updated.jf_host || '';
          }
          if (fields.jf_port && 'jf_port' in updated) {
            fields.jf_port.value = updated.jf_port || '';
          }
          if (fields.jf_api_key && 'jf_api_key' in updated) {
            if (typeof updated.jf_api_key === 'string' && updated.jf_api_key.length > 0) {
              fields.jf_api_key.value = API_MASK;
              fields.jf_api_key.disabled = true;
              isApiMasked = true;
              if (clearBtn) clearBtn.hidden = false;
            } else {
              // Key cleared
              fields.jf_api_key.value = '';
              fields.jf_api_key.disabled = false;
              isApiMasked = false;
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
            scheduleSave({ hour_format: fields.hour_format.value });
          });
          fields.hour_format.addEventListener('change', () => {
            scheduleSave({ hour_format: fields.hour_format.value });
          });
        }
        if (fields.language) {
          fields.language.addEventListener('blur', () => {
            scheduleSave({ language: fields.language.value });
          });
          fields.language.addEventListener('change', () => {
            scheduleSave({ language: fields.language.value });
          });
        }
        if (fields.jf_host) {
          fields.jf_host.addEventListener('blur', () => {
            scheduleSave({ jf_host: fields.jf_host.value.trim() });
          });
        }
        if (fields.jf_port) {
          fields.jf_port.addEventListener('blur', () => {
            scheduleSave({ jf_port: fields.jf_port.value.trim() });
          });
        }
        if (fields.jf_api_key) {
          fields.jf_api_key.addEventListener('blur', () => {
            if (isApiMasked || fields.jf_api_key.disabled) return;
            const val = fields.jf_api_key.value.trim();
            if (val && val !== API_MASK) {
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


      /**
       * Activate the tab + panel associated with the provided ID.
       * @param {*} id Panel ID to activate
       */
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

      /**
       * Reads the current URL hash and activates the matching panel.
       */
      function fromHash() {
        const id = (location.hash || '#general').slice(1);
        const known = panels.some(p => p.id === id);
        activate(known ? id : 'general');
      }

      // Handle clicking the tabs
      tabs.forEach(t => {
        t.addEventListener('click', (e) => {
          e.preventDefault();
          const id = t.getAttribute('href').slice(1);
          history.replaceState(null, '', `#${id}`);
          activate(id);
        });
      });

      window.addEventListener('hashchange', fromHash); // Sync with hash changes
      fromHash(); // Initialize

      loadSettings().then(bindAutosave);
    })();

(function () {
  const testBtn = document.querySelector('#jellyfin .form-actions .btn');
  if (!testBtn) return;

  testBtn.addEventListener('click', async () => {
    // Disable while testing to prevent duplicate requests
    const originalText = testBtn.textContent;
    testBtn.disabled = true;
    testBtn.textContent = 'Testing...';
    try {
      const resp = await fetch('/api/test-connection', { method: 'GET' });
      const data = await resp.json();
      const kind = data.ok ? 'success' : 'error';
      const statusInfo = typeof data.status === 'number' ? ` (status: ${data.status})` : '';
      const msg = (data.message || (data.ok ? 'Connection successful.' : 'Connection failed.')) + statusInfo;

      const toastContainer = document.getElementById('toast-container');
      if (toastContainer) {
        const el = document.createElement('div');
        el.className = `toast ${kind}`;
        el.setAttribute('role', 'status');
        el.textContent = msg;
        toastContainer.appendChild(el);
        setTimeout(() => el.remove(), 3000);
      } else {
        console[data.ok ? 'log' : 'error'](msg);
      }
    } catch (err) {
      const toastContainer = document.getElementById('toast-container');
      const msg = 'Failed to test connection';
      if (toastContainer) {
        const el = document.createElement('div');
        el.className = 'toast error';
        el.setAttribute('role', 'status');
        el.textContent = msg;
        toastContainer.appendChild(el);
        setTimeout(() => el.remove(), 3000);
      }
      console.error(err);
    } finally {
      // Restore button state
      testBtn.disabled = false;
      testBtn.textContent = originalText;
    }
  });
})();