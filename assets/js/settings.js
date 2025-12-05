(function () {
      const tabs = Array.from(document.querySelectorAll('.settings-tab'));
      const panels = Array.from(document.querySelectorAll('.settings-content'));

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
    })();