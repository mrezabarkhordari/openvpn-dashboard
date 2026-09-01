/**
 * Shared UI: sidebar drawer, inline action rows, Lucide icons.
 */
(function() {
    'use strict';

    function refreshIcons() {
        if (window.lucide) {
            window.lucide.createIcons();
        }
    }

    function setSidebarOpen(open) {
        var sidebar = document.getElementById('sidebar');
        var overlay = document.getElementById('sidebar-overlay');
        if (!sidebar) return;
        sidebar.classList.toggle('open', open);
        if (overlay) overlay.classList.toggle('open', open);
        document.body.classList.toggle('sidebar-open', open);
    }

    function closeActionDrawers(except) {
        document.querySelectorAll('.account-group.drawer-open').forEach(function(el) {
            if (el !== except) {
                el.classList.remove('drawer-open');
                var trigger = el.querySelector('.action-drawer-trigger');
                if (trigger) trigger.setAttribute('aria-expanded', 'false');
            }
        });
    }

    function initSidebar() {
        var toggle = document.getElementById('sidebar-toggle');
        var overlay = document.getElementById('sidebar-overlay');
        var closeBtn = document.getElementById('sidebar-close');
        if (toggle) {
            toggle.addEventListener('click', function() {
                var sidebar = document.getElementById('sidebar');
                setSidebarOpen(sidebar && !sidebar.classList.contains('open'));
            });
        }
        if (overlay) {
            overlay.addEventListener('click', function() {
                setSidebarOpen(false);
            });
        }
        if (closeBtn) {
            closeBtn.addEventListener('click', function() {
                setSidebarOpen(false);
            });
        }
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                setSidebarOpen(false);
                closeActionDrawers();
                closeConfigQr();
            }
        });
        window.addEventListener('resize', function() {
            if (window.innerWidth >= 768) {
                setSidebarOpen(false);
            }
        });
    }

    function configImportUrl(accountNumber) {
        return window.location.origin + '/download/' + encodeURIComponent(accountNumber) + '/?import=1';
    }

    function configQrUrl(accountNumber) {
        return '/download/' + encodeURIComponent(accountNumber) + '/qr/?t=' + Date.now();
    }

    function closeConfigQr() {
        var modal = document.getElementById('qr-modal');
        if (modal) modal.classList.remove('active');
    }

    function showConfigQr(accountNumber) {
        var modal = document.getElementById('qr-modal');
        if (!modal) return;

        var img = document.getElementById('qr-modal-image');
        var nameEl = document.getElementById('qr-modal-account');
        var urlEl = document.getElementById('qr-modal-url');
        var errorEl = document.getElementById('qr-modal-error');
        var frameEl = document.getElementById('qr-modal-frame');
        var importUrl = configImportUrl(accountNumber);

        if (nameEl) nameEl.textContent = accountNumber;
        if (urlEl) urlEl.textContent = importUrl;
        if (errorEl) {
            errorEl.classList.add('hidden');
            errorEl.textContent = '';
        }
        if (frameEl) frameEl.classList.remove('hidden');
        if (img) {
            img.style.display = 'none';
            img.onload = function() {
                img.style.display = 'block';
            };
            img.onerror = function() {
                if (frameEl) frameEl.classList.add('hidden');
                if (errorEl) {
                    errorEl.classList.remove('hidden');
                    errorEl.textContent = 'Configuration file not found for account "' + accountNumber + '". The .ovpn file may not have been generated yet.';
                }
            };
            img.src = configQrUrl(accountNumber);
        }

        modal.classList.add('active');
        refreshIcons();
    }

    function copyQrUrl() {
        var urlEl = document.getElementById('qr-modal-url');
        var url = urlEl ? urlEl.textContent : '';
        if (!url) return;

        function copied() {
            if (typeof window.showToast === 'function') {
                window.showToast('Download link copied', 'success');
            }
        }

        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(url).then(copied).catch(function() {
                window.prompt('Copy this download link:', url);
            });
        } else {
            window.prompt('Copy this download link:', url);
        }
    }

    function initQrModal() {
        var modal = document.getElementById('qr-modal');
        if (!modal) return;
        var closeBtn = document.getElementById('qr-modal-close');
        var copyBtn = document.getElementById('qr-modal-copy');
        if (closeBtn) closeBtn.addEventListener('click', closeConfigQr);
        if (copyBtn) copyBtn.addEventListener('click', copyQrUrl);
        modal.addEventListener('click', function(e) {
            if (e.target === modal) closeConfigQr();
        });
    }

    function initActionDrawers() {
        document.addEventListener('click', function(e) {
            var trigger = e.target.closest('.action-drawer-trigger');
            if (trigger) {
                e.preventDefault();
                e.stopPropagation();
                var group = trigger.closest('.account-group');
                if (!group) return;
                var willOpen = !group.classList.contains('drawer-open');
                closeActionDrawers(group);
                group.classList.toggle('drawer-open', willOpen);
                trigger.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
                refreshIcons();
            }
        });
    }

    function init() {
        initSidebar();
        initActionDrawers();
        initQrModal();
        refreshIcons();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.refreshIcons = refreshIcons;
    window.showConfigQr = showConfigQr;
    window.closeConfigQr = closeConfigQr;
})();
